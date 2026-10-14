#!/usr/bin/env python3
"""Cross-check 3DS Files/source/btracksel.c, track select, against the retail
image, SLES_507.31.

**The model** is retail's own: TrackSelectScreenCallback (0x001a0920) and
everything under it -- SelectTrackScreen's constructor, destructor,
ScreenCallback, HandleLapSelection, ResyncScreen, ResyncData, DoTick,
DoRender, the lap selector and StartRace (0x001a0790); SelectableTrack and
its TimeOfDayTracks, SelectableTrackManager's BuildList and the rest, the
slideshow, TODMenuManager, TrackRecordDisplayer, TrackLockedDisplayer;
IsTrackUnavailable, CalculateTrackNumberToLoad, GetTrackInfo over GLOBALB's
track table; FormatUnlockBlurbForTrack; feAlphaAnimation and AnimationGroup
with cPoint's SplineSeek; bRandom on bDefaultSeed; and under all of them the
Flailer runtime on FRONTB's Flailer chunk. The static initializer
(0x001a09e8) puts the camera's eye and look-at in place first. The harness
(tools/src/tracksel_test.c) runs btracksel.c over flailer.c, banim.c,
nfsrewards.c and bmath.c on the same files.

**The stubs** are what the screen does not own, scripted the same on both
sides and logged in the same words: GetTranslatedString (each id its own
buffer), the speech's fade, SPCH_AddEventV and ConvertTrackNumber (which
answers the track), IsTrackUnlocked, the easter eggs' test (0x0024f930),
IsTrackAnEventReward and FindEventThatTrackIsARewardFor,
RenderTextIntoRectangle, SetActiveMenuItem and GetActiveMenuItem, the
TexturePack (its constructor, LoadTextureTableFromFile, its destructor,
UnloadAllTexturesFromFile, GetTexture by rule and LoadTexturesFromFile,
whose callback the script runs), tHighlightAnimation's constructor,
SetCurrentMenuItem and Animate (its destructor silent),
GetSelectedCarClass, GetBestLapTimesTable, GetBestTotalTimesTable,
LookupPlayerNameFromTable, Timer's PrintToString, FrontendDatabase's
StartRace; and the 3D: StillCameraMover's constructor and destructor,
eModel's Init (its Solid scripted), destructor and Render, bOMalloc for the
eModel slot pool. eIdentity and eRotateZ run for real, and the frame-malloc
inline over a scripted buffer.

**One choice** the port makes where retail reads garbage: the slideshow's
time-of-day name for time of day 4 (tracks 44 to 46) is read one entry
past a four-entry stack table, onto the first word of the sprintf buffer.
The model puts a pointer to "" there (the hook at 0x0019e294), which is what
the port reads.

**Compared** are the stubs' logs, what the callback leaves in the
ScreenCallbackData, and after each op every line that changed: the screen,
its two splines, the track list with each track's times of day and model,
the camera, the slideshow, the time-of-day menu, the records, the locked
box (its slide and its blurb), the model's angle, Fred's
SelectTrackScreenData, the race parameters, the frame buffer and every
Flailer object's bytes.

**The script** runs a single race with one player across the strip both
ways, every time of day, the lap selector and every way out of it, SQUARE's
speech, the slideshow through its cross-fades and every texture rule, and
the records through their rotation; locked, egged and event tracks with the
locked box sliding on; the knockout and Be A Cop's game types with point to
point tracks hidden, two players, the lap counts StartRace works out; both
units, both languages, the main menu's no-records option; the frame buffer
full and the model without a solid.

    python tools/tracksel_check.py
    python tools/tracksel_check.py --mutate [--only a,b] [--jobs N]
    python tools/tracksel_check.py --dump out/tracksel

The model's transcript is cached (tools/mutpar.py), so a run after one
that changed only the port, the harness or the mutations skips the model.
"""
import argparse
import os
import struct
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import flailer_check as fc              # noqa: E402
import hostbuild                        # noqa: E402
import mutpar                           # noqa: E402
import physicscar_check as pcc          # noqa: E402
from mipsemu import M32, s32            # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

HARNESS = "tools/src/tracksel_test.c"
BTRACKSEL = "3DS Files/source/btracksel.c"
SOURCES = [HARNESS, BTRACKSEL, "3DS Files/source/nfsrewards.c",
           "3DS Files/source/banim.c", "3DS Files/source/bmath.c",
           "3DS Files/source/bmathtab.c", "3DS Files/source/flailer.c",
           "3DS Files/source/bprintf.c", "3DS Files/source/bui.c",
           "3DS Files/source/bchunk.c", "3DS Files/source/langtab.c", "3DS Files/source/portlang.c",
           "3DS Files/source/emath.c", "3DS Files/source/bmatrix.c",
           "3DS Files/source/bvector.c"]

GLOBALB = ROOT / "extracted-retail" / "GLOBAL" / "GLOBALB.BUN"
FRONTB = fc.SD / "FRONTEND" / "FRONTB.BUN"

GP = fc.GP
FRED = 0x002fc050
F_OPTS = FRED + 28                      # MainMenuOpts[0]
F_UNITS = FRED + 333
F_DATA = FRED + 340                     # SelectTrackScreenData[4]
F_GT = FRED + 67372
F_NP = FRED + 67380
F_FPI = FRED + 67384
FRED_SIZE = 70936
FPI_SIZE = 1744
RP = 0x0031a898                         # TheRaceParameters
RP_SIZE = 640
LANGUAGE = 0x0031c1c8                   # CurrLanguage
TRACK_CHUNK = 0x34201
TRACK_SIZE = 164

G_RTIMER = GP - 19608
G_RELAPSED = GP - 19596
G_SCREEN = GP - 19760                   # the SelectTrackScreen
G_ANGLE = GP - 19700                    # the model's angle
G_SEED = GP - 14472                     # bDefaultSeed
G_HIGHEST = GP - 21944                  # HighestTrackNumber
G_TABLE = GP - 21948                    # TrackInfoTable
G_FPOS = GP - 19388                     # CurrentBufferPos
G_FEND = GP - 19384                     # CurrentBufferEnd
G_FFAIL = GP - 19372                    # FrameMallocFailed
G_FAMOUNT = GP - 19368                  # FrameMallocFailAmount

F_CALLBACK = 0x001a0920
F_SINIT = 0x001a09e8                    # the camera's two vectors
H_PICK_TOD = 0x0019e294                 # the slideshow's bRandom call

S_XL = 0x0021e560
S_SPEECH = 0x00209ef0
S_FADE = 0x0020a290
S_SPEAK = 0x002919d0
S_CONVERT = 0x002233d8
S_UNLOCKED = 0x0024b760
S_EGG = 0x0024f930
S_ISEVENT = 0x001ffaa8
S_FINDEVENT = 0x001ffa38
S_RTEXT = 0x001451e0
S_SETACTIVE = 0x0016d3d0
S_GETACTIVE = 0x0016d3f0
S_PACK_NEW = 0x001ac0a8
S_PACK_TABLE = 0x001ac608
S_PACK_DTOR = 0x001ac178
S_PACK_UNLOAD = 0x001acf98
S_PACK_HAS = 0x001ac468
S_PACK_LOAD = 0x001acc98
S_HL_INIT = 0x00248870
S_HL_ITEM = 0x002488d0
S_HL_ANIM = 0x00248970
S_HL_DTOR = 0x002488b0
S_CLASS = 0x00187970
S_LAPTABLE = 0x00186dd0
S_TOTTABLE = 0x00186d98
S_NAME = 0x00186a20
S_PRINT = 0x001a3b98
S_STARTRACE = 0x00184f68
S_MOVER = 0x0015e6a0
STILL_VT = 0x002b1850                   # _vt$16StillCameraMover
S_OMALLOC = 0x00257c80
S_MODEL_INIT = 0x0010c558
S_MODEL_DTOR = 0x00114cf0
S_MODEL_RENDER = 0x0010dc80
SILENT = [
    0x0016ad88,                         # FlailerScreenConfig's constructor
    0x00114e98, 0x00114e90,             # delete
    0x00257ca0,                         # bFree(SlotPool *, void *)
]

MOVER_SIZE = 112

SCREEN = 0x15417b53
MENUITEM_1 = 0x52e039f3
MENUITEM_2 = 0x52e039f4

SELECT, HIGHLIGHT, LEFT, RIGHT, UP, DOWN, SQUARE = 1, 4, 6, 7, 8, 9, 10
ACTIVATE, UNACTIVATE, START, L1, BACK, TICK, RENDER = 11, 12, 13, 15, 17, \
    18, 19

FRAME = 1 << 16

# The blurbs' ids, FormatUnlockBlurbForTrack's.
LANG_TRACK_CHAMP = 0xd6d9
LANG_TRACK_HP = 0xd6da


def F(v):
    return "%#x" % struct.unpack("<I", struct.pack("<f", v))[0]


def cx(v):
    """C's %#x."""
    return "0x%x" % v if v else "0"


# ================================================================ the data

def track_table():
    data = GLOBALB.read_bytes()
    off = 0
    while off + 8 <= len(data):
        cid, size = struct.unpack_from("<II", data, off)
        if cid == TRACK_CHUNK:
            return data[off + 8:off + 8 + size]
        off += 8 + size
    raise SystemExit("no track table in %s" % GLOBALB)


class Track(object):
    def __init__(self, n, r):
        self.n = n
        self.named = r[0] != 0
        self.number = struct.unpack_from("<b", r, 65)[0]
        self.same = struct.unpack_from("<b", r, 66)[0]
        self.p2p = struct.unpack_from("<b", r, 67)[0]
        self.tod = struct.unpack_from("<h", r, 68)[0]


def tracks():
    d = track_table()
    out = {}
    for i in range(len(d) // TRACK_SIZE):
        t = Track(i + 1, d[TRACK_SIZE * i:TRACK_SIZE * (i + 1)])
        if t.named and t.n != 54:
            out[t.n] = t
    return out


# ================================================================== script

class Script(object):
    def __init__(self):
        self.ops = []
        self.rtimer = 1000
        self.tracks = tracks()
        self.bases = sorted(n for n, t in self.tracks.items()
                            if t.same == t.number)

    def add(self, *ops):
        self.ops += list(ops)

    def g(self, name, v):
        self.ops.append("g|%s|%s" % (name, v))

    def msg(self, m, item=0, port=0, param=-1, noise=-1):
        self.ops.append("msg|%d|%s|%d|%d|%d" % (m, cx(item), port, param,
                                                noise))

    def wait(self, ticks):
        self.rtimer += ticks
        self.g("rtimer", self.rtimer)

    def tick(self, n=1, step=400, render=True):
        for _ in range(n):
            self.wait(step)
            self.msg(TICK, param=0, noise=0)
            if render:
                self.msg(RENDER, param=0, noise=0)

    def data(self, track, laps, d, tod):
        self.ops.append("data|%d|%d|%d|%d" % (track, laps, d, tod))

    def activate(self):
        self.msg(ACTIVATE, SCREEN)

    def unactivate(self):
        self.msg(UNACTIVATE, param=0, noise=0)


def common(s):
    s.add("load|%s" % FRONTB, "tracks|%s" % GLOBALB)
    for i, t in ((0xd6eb, "Elev %.0f to %.0f %s"),
                 (0xd994, "Circuit"), (0xd995, "Point to point"),
                 (0xd6f1, "Best Total Time (%d Laps)"),
                 (0xd6e9, "Best Total Time"),
                 (LANG_TRACK_CHAMP, "Win championship event %d"),
                 (LANG_TRACK_HP, "Win hot pursuit event %d"),
                 (0, "Zero %d")):
        s.add("xl|%s|%s" % (cx(i), t))
    for k, v in (("units", 0), ("lang", 0), ("opts", 0), ("gametype", 3),
                 ("players", 1), ("tex", 1), ("solid", 1), ("seed", 12345),
                 ("active", MENUITEM_2)):
        s.g(k, v)
    s.g("relapsed", F(1.0 / 60))
    s.g("rtimer", s.rtimer)
    s.add("frame|%d" % FRAME)


def s_single(s):
    """A single race, one player: the strip, the times of day, the
    slideshow, the records and the lap selector."""
    s.add("cls|0|2")
    s.add("lap|11|2|0|123456|3", "tot|11|2|0|2|222222|4",
          "tot|11|2|0|8|888888|5", "tot|11|2|0|4|0|6",
          "lap|12|2|0|0|1", "tot|12|2|0|1|111111|7",
          "lap|11|2|1|654321|9", "tot|11|2|1|1|101010|10",
          "tot|11|2|1|2|202020|11", "tot|11|2|1|4|404040|12")
    s.data(11, 2, 0, 0)
    s.activate()
    s.tick(3)
    # The slideshow: the first picture loads, four seconds go by, the
    # cross-fade, and the next.
    s.add("texloaded")
    s.tick(2)
    s.wait(4 * 4000)
    s.tick(4, step=1000)
    s.add("texloaded")
    s.tick(3, step=2000)
    # The records' rotation: three totals, each five seconds, a fade out
    # and in between.
    s.wait(5 * 4000)
    s.tick(6, step=500)
    s.wait(6 * 4000)
    s.tick(6, step=500)
    s.msg(HIGHLIGHT, MENUITEM_1)
    # The times of day: both ways round.
    s.msg(DOWN, MENUITEM_2)
    s.tick(2)
    s.msg(DOWN, MENUITEM_1)
    s.msg(UP, MENUITEM_2)
    s.msg(UP, MENUITEM_1)
    # The strip: left at the first stops.
    s.msg(LEFT)
    for _ in range(3):
        s.msg(RIGHT)
        s.tick(2)
    s.msg(LEFT)
    s.tick(4, step=100)
    s.msg(SQUARE)
    s.msg(SQUARE)
    s.msg(SQUARE)
    s.msg(RIGHT)
    s.msg(START)
    s.msg(L1)
    # The lap selector: not for other pads, then round its counts.
    s.msg(SELECT, port=2)
    s.msg(SELECT, port=1)
    s.msg(SELECT)
    for m in (LEFT, LEFT, LEFT, LEFT, RIGHT, RIGHT, RIGHT, RIGHT, UP, DOWN,
              HIGHLIGHT, SQUARE):
        s.msg(m, 0x7e544804)
    s.tick(2)
    s.msg(BACK, param=0, noise=0)
    s.tick(1)
    s.msg(SELECT)
    s.msg(SELECT, port=1)
    s.msg(START)
    s.unactivate()
    # Back on the same track, the other way: the data Fred kept.
    s.data(11, 4, 1, 1)
    s.activate()
    s.tick(2)
    s.msg(RIGHT)
    s.msg(LEFT)
    s.msg(LEFT)
    s.msg(SELECT)
    s.msg(START)
    s.unactivate()
    # A point to point track goes straight to the race.
    s.data(13, 2, 0, 0)
    s.activate()
    s.msg(SELECT)
    s.unactivate()


def s_locked(s):
    """Locked tracks, an egg, and the events that unlock them."""
    for t, d in ((12, 0), (13, 0), (21, 0), (22, 0), (23, 0), (11, 1),
                 (31, 1), (43, 0), (62, 1)):
        s.add("unl|%d|%d|0" % (t, d))
    s.add("egg|22|0|1", "egg|63|1|1")
    s.add("ev|12|0|0|3", "ev|13|0|1|5", "ev|21|0|2|-2", "ev|11|1|1|130",
          "ev|31|1|0|0")
    s.g("tex", 2)
    s.data(12, 2, 0, 1)
    s.activate()
    s.tick(2)
    s.wait(1500)
    s.tick(4, step=600)
    s.msg(SELECT)
    s.msg(SQUARE)
    for _ in range(4):
        s.msg(RIGHT)
        s.tick(3, step=800)
    s.msg(LEFT)
    s.msg(LEFT)
    s.tick(5, step=900)
    s.unactivate()
    # The other way's first track is locked; its neighbours are not.
    s.data(11, 2, 1, 0)
    s.activate()
    s.tick(3, step=1000)
    s.msg(DOWN)
    s.msg(SQUARE)
    s.msg(RIGHT)
    s.tick(2)
    s.msg(SELECT)
    s.unactivate()
    for t, d in ((12, 0), (13, 0), (21, 0), (22, 0), (23, 0), (11, 1),
                 (31, 1), (43, 0), (62, 1)):
        s.add("unl|%d|%d|1" % (t, d))
    s.add("egg|22|0|0", "egg|63|1|0")
    s.g("tex", 1)


def s_games(s):
    """The game types' tracks and StartRace's lap counts."""
    # Knockout (5): point to point hidden; the data's track is one of them.
    s.g("gametype", 5)
    s.g("rpnp", 1)
    s.g("rpnai", 3)
    s.data(13, 2, 0, 0)
    s.activate()
    s.tick(1)
    s.msg(RIGHT)
    s.msg(SELECT)
    s.g("rpnai", 0)
    s.msg(SELECT)
    s.unactivate()
    # Be A Cop's (7) with one player, then two.
    s.g("gametype", 7)
    s.g("rpnp", 1)
    s.data(23, 4, 0, 1)
    s.activate()
    s.msg(SELECT)
    s.msg(SELECT, port=1)
    s.unactivate()
    s.g("players", 2)
    s.g("rpnp", 2)
    s.add("cls|0|3", "cls|1|1", "lap|21|1|0|333333|2",
          "tot|21|1|0|8|777777|8")
    s.data(21, 8, 0, 0)
    s.activate()
    s.tick(2)
    s.msg(SELECT, port=1)
    s.msg(RIGHT, 0x7e544804, port=1)
    s.msg(SELECT, port=2)
    s.msg(START, port=1)
    s.unactivate()
    s.add("cls|0|1", "cls|1|4")
    s.data(21, 2, 0, 0)
    s.activate()
    s.msg(SELECT, port=0)
    s.msg(BACK, param=0, noise=0)
    s.msg(SELECT, port=1)
    s.msg(SELECT, port=0)
    s.unactivate()
    s.g("players", 1)
    s.g("rpnp", 1)
    # Hot Pursuit (4): a point to point's one lap, a circuit's two.
    s.g("gametype", 4)
    s.data(33, 2, 0, 2)
    s.activate()
    s.msg(SELECT)
    s.msg(LEFT)
    s.msg(SELECT)
    s.unactivate()
    # 6: no laps.
    s.g("gametype", 6)
    s.data(62, 2, 1, 2)
    s.activate()
    s.msg(SELECT)
    s.unactivate()
    s.g("gametype", 3)


def s_unavailable(s):
    """A locked point to point track in the knockout: not in the game at
    all, which comes before locked; and the knockout with nobody in it."""
    s.add("unl|13|0|0", "unl|23|1|0")
    s.g("gametype", 5)
    s.g("rpnp", 0)
    s.g("rpnai", 0)
    s.data(12, 2, 0, 0)
    s.activate()
    s.msg(RIGHT)
    s.msg(SELECT)
    s.unactivate()
    s.add("unl|13|0|1", "unl|23|1|1")
    s.g("gametype", 3)
    s.g("rpnp", 1)


def s_ends(s):
    """The strip's last track: RIGHT stops there, and there is no more on
    the right."""
    last = s.bases[-1]
    s.data(last, 2, 1, 0)
    s.activate()
    s.msg(RIGHT)
    s.msg(RIGHT)
    s.msg(LEFT)
    s.msg(RIGHT)
    s.unactivate()


def s_slideshow(s):
    """The slideshow, cycle after cycle: the picture holds four seconds
    once loaded, cross-fades for two, and the next is never the last."""
    s.g("tex", 1)
    s.g("seed", 0x13579bd)
    s.data(22, 2, 0, 0)
    s.activate()
    s.tick(1, render=False)
    for k in range(14):
        # Not loaded yet: past four seconds and nothing starts.
        if k == 0:
            s.wait(4 * 4400)
            s.tick(1, step=1, render=False)
        s.add("texloaded")
        s.wait(4 * 3500)
        s.tick(1, step=1, render=False)
        s.wait(4 * 600)
        s.tick(1, step=1, render=False)
        s.wait(4 * 1000)
        s.tick(1, step=1, render=False)
        s.wait(4 * 1100)
        s.tick(1, step=1, render=False)
    s.unactivate()


def s_records(s):
    """The totals' rotation in fine steps, three times round two records,
    and a single record, which only starts its clock again."""
    s.add("cls|0|2")
    s.data(11, 2, 0, 0)
    s.activate()
    for _ in range(3):
        s.wait(4 * 4900)
        s.tick(52, step=100, render=False)
    s.msg(RIGHT)                        # track 12: one total
    s.wait(4 * 4900)
    s.tick(52, step=100, render=False)
    s.unactivate()


def s_options(s):
    """Metric, French, no records, the start data's variants, the texture
    rules and the slideshow's fourth time of day."""
    s.g("units", 1)
    s.g("lang", 1)
    s.add("cls|0|2")
    s.add("lap|31|2|0|313131|13", "tot|31|2|0|2|626262|14")
    s.data(34, 2, 0, 2)                 # a variant: track 31 at sunset
    s.activate()
    s.tick(2)
    s.msg(DOWN, MENUITEM_1)
    s.g("opts", 1)
    s.msg(UP, MENUITEM_2)
    s.tick(2)
    s.g("opts", 0)
    s.unactivate()
    s.g("units", 0)
    s.g("lang", 0)
    # Track 41's other time of day is 4: the slideshow's past-the-table
    # name. Every texture rule over it.
    s.g("tex", 0)
    s.data(41, 2, 0, 3)                 # no such time of day: the first
    s.activate()
    s.tick(1)
    s.msg(DOWN, MENUITEM_2)
    s.g("tex", 1)
    s.msg(RIGHT)
    s.msg(LEFT)
    s.msg(DOWN, MENUITEM_1)
    s.msg(DOWN, MENUITEM_2)
    s.add("texloaded")
    s.wait(5 * 4000)
    s.tick(3, step=3000)
    s.g("tex", 2)
    s.g("seed", 0x7654321)
    for _ in range(5):
        s.msg(RIGHT)
        s.add("texloaded")
        s.wait(5 * 4000)
        s.tick(2, step=3000)
    s.unactivate()
    s.g("tex", 1)


def s_render(s):
    """The frame buffer full, the model without a solid, and a fast tick."""
    s.add("frame|96")
    s.data(42, 2, 0, 0)
    s.activate()
    s.tick(3)
    s.g("solid", 0)
    s.msg(RIGHT)
    s.tick(2)
    s.msg(LEFT)
    s.tick(1)
    s.add("frame|0")
    s.tick(1)
    s.add("frame|%d" % FRAME)
    s.g("relapsed", F(0.25))
    s.tick(8, step=100)
    s.g("relapsed", F(1.0 / 60))
    s.unactivate()
    # Models made without a solid draw nothing.
    s.data(42, 2, 0, 0)
    s.activate()
    s.tick(2)
    s.unactivate()
    s.g("solid", 1)
    # The angle wraps at 2 pi: 629 ticks of 0.01, each one drawn.
    s.add("frame|%d" % (FRAME * 2))
    s.data(61, 2, 0, 0)
    s.activate()
    s.tick(640, step=10)
    s.unactivate()


def script():
    s = Script()
    common(s)
    s_single(s)
    s_locked(s)
    s_games(s)
    s_unavailable(s)
    s_ends(s)
    s_slideshow(s)
    s_records(s)
    s_options(s)
    s_render(s)
    return s.ops


# =================================================================== model

class Model(fc.Model):
    def __init__(self):
        fc.Model.__init__(self)
        e = self.e
        self.lines = {}
        e.write(FRED, bytes(FRED_SIZE))
        e.write(RP, bytes(RP_SIZE))
        for g in (G_RTIMER, G_RELAPSED, G_SCREEN, G_ANGLE, G_SEED, LANGUAGE,
                  G_FPOS, G_FEND, G_FFAIL, G_FAMOUNT, G_HIGHEST, G_TABLE):
            e.put32(g, 0)
        self.frame = 0
        self.solid = 1
        self.texmode = 1
        self.active = 0
        self.speech = e.alloc(64, align=16)
        self.data = e.alloc(16, align=16)
        self.empty = e.alloc(16, align=16)
        e.write(self.empty, bytes(16))
        self.packmem = e.alloc(16, align=16)
        self.texmem = e.alloc(16, align=16)
        self.xlbuf = {}
        self.xl = {}
        self.cls = [0, 0]
        self.unl = {}
        self.eggs = {}
        self.ev = {}
        self.laprec = {}
        self.totrec = {}
        self.names = {}
        self.load_cb = None
        self.table = 0
        stubs = {
            S_XL: self.s_xl, S_SPEECH: lambda em: self.speech,
            S_FADE: self.s_fade, S_SPEAK: self.s_speak,
            S_CONVERT: lambda em: em.reg[4] & M32,
            S_UNLOCKED: self.s_unlocked, S_EGG: self.s_egg,
            S_ISEVENT: self.s_isevent, S_FINDEVENT: self.s_findevent,
            S_RTEXT: self.s_rtext, S_SETACTIVE: self.s_setactive,
            S_GETACTIVE: self.s_getactive, S_PACK_NEW: self.s_pack_new,
            S_PACK_TABLE: self.s_pack_table, S_PACK_DTOR: self.s_pack_dtor,
            S_PACK_UNLOAD: self.s_pack_unload, S_PACK_HAS: self.s_pack_has,
            S_PACK_LOAD: self.s_pack_load, S_HL_INIT: self.s_hl_init,
            S_HL_ITEM: self.s_hl_item,
            S_HL_ANIM: lambda em: self.emit("  hl_anim"),
            S_HL_DTOR: lambda em: 0, S_CLASS: self.s_class,
            S_LAPTABLE: self.s_laptable, S_TOTTABLE: self.s_tottable,
            S_NAME: self.s_name, S_PRINT: self.s_print,
            S_STARTRACE: lambda em: self.emit("  startrace"),
            S_MOVER: self.s_mover, S_OMALLOC: self.s_omalloc,
            S_MODEL_INIT: self.s_model_init,
            S_MODEL_DTOR: self.s_model_dtor,
            S_MODEL_RENDER: self.s_model_render,
        }
        for a, fn in stubs.items():
            e.stub(a, fn)
        for a in SILENT:
            e.stub(a, lambda em: 0)
        # The mover's virtual destructor, as ~SelectTrackScreen calls it.
        e.stub(e.u32(STILL_VT + 12), lambda em: self.emit("  cam delete"))
        e.hook(H_PICK_TOD, self.h_pick_tod)
        e.call(F_SINIT)

    # ---- stubs

    def string(self, a):
        mem = self.e.mem
        n = 0
        while mem[a + n]:
            n += 1
        return bytes(mem[a:a + n]).decode("latin-1")

    def cstr(self, s):
        a = self.e.alloc(len(s) + 16, align=16)
        self.e.write(a, s.encode("latin-1") + b"\0")
        return a

    def s_xl(self, em):
        i = s32(em.reg[4] & M32)
        t = self.xl.get(i, "M%x" % (i & M32))
        self.emit("  xl %s -> %s" % (cx(i & M32), t))
        if i not in self.xlbuf:
            self.xlbuf[i] = self.e.alloc(128, align=16)
        self.e.write(self.xlbuf[i], t.encode("latin-1") + b"\0")
        return self.xlbuf[i]

    def s_fade(self, em):
        self.emit("  fade %08x" % (em.fpr[12] & M32))

    def s_speak(self, em):
        self.emit("  speak %d %d %d" % tuple(s32(em.reg[i] & M32)
                                             for i in (4, 5, 6)))

    def s_unlocked(self, em):
        t, d = s32(em.reg[4] & M32), s32(em.reg[5] & M32)
        v = self.unl.get((t, d & 1), 1)
        self.emit("  unlocked? %d %d -> %d" % (t, d, v))
        return v

    def s_egg(self, em):
        t, d = s32(em.reg[5] & M32), s32(em.reg[6] & M32)
        v = self.eggs.get((t, d & 1), 0)
        self.emit("  egg? %d %d -> %d" % (t, d, v))
        return v

    def s_isevent(self, em):
        t, d = s32(em.reg[4] & M32), s32(em.reg[5] & M32)
        v = 1 if (t, d & 1) in self.ev else 0
        self.emit("  event? %d %d -> %d" % (t, d, v))
        return v

    def s_findevent(self, em):
        e = self.e
        tree, num = self.ev[(s32(em.reg[4] & M32), s32(em.reg[5] & M32) & 1)]
        ev = e.alloc(64, align=16)
        tr = e.alloc(16, align=16)
        e.write(ev, bytes(64))
        e.write(tr, bytes(16))
        e.put32(ev, tr)
        e.put32(tr + 8, tree & M32)
        e.mem[ev + 40] = num & 0xff
        return ev

    def s_rtext(self, em):
        self.emit('  rtext %08x %08x %08x "%s" %08x' % (
            em.reg[5] & M32, em.reg[6] & M32, em.reg[7] & M32,
            self.string(em.reg[8] & M32), em.fpr[12] & M32))

    def s_setactive(self, em):
        self.emit("  setactive %08x" % (em.reg[4] & M32))

    def s_getactive(self, em):
        self.emit("  getactive -> %08x" % (self.active & M32))
        return self.active & M32

    def s_pack_new(self, em):
        self.emit("  pack new %s" % self.string(em.reg[5] & M32))
        return em.reg[4] & M32

    def s_pack_table(self, em):
        self.emit("  pack table %s" % self.string(em.reg[5] & M32))

    def s_pack_dtor(self, em):
        self.emit("  pack delete")

    def s_pack_unload(self, em):
        self.emit("  pack unload %d" % (1 if em.reg[4] & M32 else 0))

    def s_pack_has(self, em):
        h = em.reg[5] & M32
        v = 1 if self.texmode == 1 or (self.texmode == 2 and h & 1) else 0
        self.emit("  pack has %08x -> %d" % (h, v))
        return self.texmem if v else 0

    def s_pack_load(self, em):
        self.emit("  pack load %08x" % self.e.u32(em.reg[5] & M32))
        self.load_cb = (em.reg[7] & M32, em.reg[8] & M32)

    def s_hl_init(self, em):
        self.emit("  hl_init %08x %08x %x" % (em.reg[5] & M32,
                                              em.reg[6] & M32,
                                              em.reg[7] & M32))

    def s_hl_item(self, em):
        self.emit("  hl_item %08x" % (em.reg[5] & M32))

    def s_class(self, em):
        p = ((em.reg[4] & M32) - F_FPI) // FPI_SIZE
        v = self.cls[p] if 0 <= p < 2 else 0
        self.emit("  class %d -> %d" % (p, v))
        return v & M32

    def record(self, store, key):
        if key not in store:
            a = self.e.alloc(16, align=16)
            self.e.write(a, struct.pack("<Ihh", 0x7fffffff, 0, 0))
            store[key] = a
        return store[key]

    @staticmethod
    def laps_index(laps):
        return {1: 0, 2: 1, 4: 2}.get(laps, 3)

    def s_laptable(self, em):
        t, c, d = (s32(em.reg[i] & M32) for i in (5, 6, 7))
        self.emit("  laptable %d %d %d" % (t, c, d))
        return self.record(self.laprec, (t % 70, c & 7, d & 1))

    def s_tottable(self, em):
        t, c, d, n = (s32(em.reg[i] & M32) for i in (5, 6, 7, 8))
        self.emit("  tottable %d %d %d %d" % (t, c, d, n))
        return self.record(self.totrec, (t % 70, c & 7, d & 1,
                                         self.laps_index(n)))

    def s_name(self, em):
        i = s32(em.reg[5] & M32)
        self.emit("  name %d" % i)
        if i < 0 or i >= 128:
            return 0
        if i not in self.names:
            self.names[i] = self.cstr("P%d" % i)
        return self.names[i]

    def s_print(self, em):
        t = self.e.u32(em.reg[4] & M32)
        self.emit("  print %d %d" % (t, s32(em.reg[6] & M32)))
        self.e.write(em.reg[5] & M32, ("T%d" % t).encode("latin-1") + b"\0")

    def s_mover(self, em):
        a = em.reg[4] & M32
        self.e.write(a, bytes(MOVER_SIZE))
        self.e.put32(a + 40, STILL_VT)
        self.emit("  cam init view %d" % s32(em.reg[5] & M32))
        return a

    def s_omalloc(self, em):
        a = self.e.alloc(256, align=16)
        self.e.write(a, bytes(256))
        return a

    def s_model_init(self, em):
        a = em.reg[4] & M32
        self.e.put32(a + 8, em.reg[5])
        self.e.put32(a + 12, self.solid)
        self.emit("  model init %08x" % (em.reg[5] & M32))

    def s_model_dtor(self, em):
        self.emit("  model delete %08x" % self.e.u32((em.reg[4] & M32) + 8))

    def s_model_render(self, em):
        e = self.e
        m = em.reg[5] & M32
        self.emit("  model render %08x at %d light %d flags %d matrix %s" % (
            e.u32((em.reg[4] & M32) + 8), s32((m - self.frame) & M32),
            1 if em.reg[6] & M32 else 0, em.reg[7] & M32,
            bytes(e.mem[m:m + 64]).hex()))

    def h_pick_tod(self, em):
        """Time of day 4 reads one past the stack's table: "", as the port."""
        self.e.put32((em.reg[29] & M32) + 32, self.empty)

    # ---- output

    def note(self, key, text):
        if self.lines.get(key) != text:
            self.lines[key] = text
            self.emit("  %s %s" % (key, text))

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
                mem[a + 43] = 0

    def nodes(self, head):
        """A bList's nodes, from its head."""
        g = self.e.u32
        out = []
        n = g(head)
        while n and n != head and len(out) < 256:
            out.append(n)
            n = g(n)
        return out

    def ti_index(self, ti):
        return (ti - self.table) // TRACK_SIZE + 1 if ti else 0

    @staticmethod
    def index(lst, a):
        return lst.index(a) if a in lst else -1

    def dump_screen(self, p):
        e = self.e
        g = e.u32
        si = lambda o: s32(g(p + o))      # noqa: E731
        self.note("scr", (
            "present 1 normal %d data %d %d %d %d screen %08x speaking %d "
            "bm %s %s %s %s %s %s phase %08x") % (
            si(0), si(4), si(8), si(12), si(16), g(p + 20), si(24),
            *[self.name(g(p + 32 + 4 * k)) for k in range(6)], g(p + 168)))
        self.note("splines", bytes(e.mem[p + 56:p + 152]).hex())
        m = p + 152
        trk = self.nodes(m)
        self.note("mgr", "n %d cur %d spacing %08x" % (
            len(trk), self.index(trk, g(m + 8)), g(m + 12)))
        for i, t in enumerate(trk):
            tods = self.nodes(t + 28)
            mdl = g(t + 40)
            text = ("vis %d dir %d thumb %08x x %08x cur %d ti %d "
                    "height %08x model %08x %d tods") % (
                s32(g(t + 8)), s32(g(t + 12)), g(t + 16), g(t + 20),
                self.index(tods, g(t + 24)), self.ti_index(g(t + 36)),
                g(t + 44), g(mdl + 8) if mdl else 0,
                1 if mdl and g(mdl + 12) else 0)
            text += "".join(" %d:%08x" % (self.ti_index(g(n + 8)),
                                          g(n + 12)) for n in tods)
            self.note("trk%d" % i, text)
        mv = g(p + 172)
        if mv:
            self.note("cam", "eye %s look %s" % (
                bytes(e.mem[mv + 48:mv + 60]).hex(),
                bytes(e.mem[mv + 64:mv + 76]).hex()))
        s = p + 176
        self.note("show", (
            "screen %08x pack %d track %d t0 %d t1 %d tex %08x loaded %d "
            "state %d") % (
            g(s), 1 if g(s + 4) else 0, self.index(trk, g(s + 8)),
            s32(g(s + 12)), s32(g(s + 16)), g(s + 20), s32(g(s + 24)),
            s32(g(s + 28))))
        self.note("todm", "screen %08x track %d" % (
            g(p + 232), self.index(trk, g(p + 236))))
        r = p + 240
        recs = self.nodes(r + 12)
        self.note("rec", (
            "screen %08x track %d time %d cur %d n %d flag %d list%s") % (
            g(r), self.index(trk, g(r + 4)), s32(g(r + 8)),
            self.index(recs, g(r + 20)), s32(g(r + 24)), s32(g(r + 28)),
            "".join(" %d:%08x:%d" % (s32(g(n + 8)), g(g(n + 12)),
                                     struct.unpack("<h", bytes(
                                         e.mem[g(n + 12) + 4:
                                               g(n + 12) + 6]))[0])
                    for n in recs)))
        lk = p + 272
        sl = lk + 16
        self.note("lock", (
            "track %d screen %08x x %08x alpha %d start %d "
            "slide %08x %08x %08x %d %d %s \"%s\"") % (
            self.index(trk, g(lk)), g(lk + 4), g(lk + 8), s32(g(lk + 12)),
            s32(g(lk + 348)), g(sl + 8), g(sl + 12), g(sl + 16),
            s32(g(sl + 20)), s32(g(sl + 24)),
            bytes(e.mem[sl + 28:sl + 76]).hex(), self.string(lk + 92)))

    def dump(self):
        g = self.e.u32
        p = g(G_SCREEN)
        if p:
            self.dump_screen(p)
        else:
            self.note("scr", "present 0")
        self.note("angle", "%08x" % g(G_ANGLE))
        self.note("fred", "%d %d %d %d" % tuple(s32(g(F_DATA + 4 * k))
                                                for k in range(4)))
        self.note("rp", (
            "track %d dir %d type %d p2p %d laps %d np %d nai %d tree %d") % (
            s32(g(RP)), s32(g(RP + 12)), s32(g(RP + 32)), s32(g(RP + 40)),
            s32(g(RP + 44)), s32(g(RP + 48)), s32(g(RP + 52)),
            s32(g(RP + 600))))
        self.note("frame", "used %d failed %d amount %d" % (
            s32((g(G_FPOS) - self.frame) & M32), s32(g(G_FFAIL)),
            g(G_FAMOUNT)))
        self.dump_objects()

    # ---- ops

    def load_tracks(self, path):
        e = self.e
        d = Path(path).read_bytes()
        off = 0
        while off + 8 <= len(d):
            cid, size = struct.unpack_from("<II", d, off)
            if cid == TRACK_CHUNK:
                break
            off += 8 + size
        self.table = e.alloc(size, align=16)
        e.write(self.table, d[off + 8:off + 8 + size])
        n = size // TRACK_SIZE
        e.put32(G_TABLE, self.table)
        e.put32(G_HIGHEST, n)
        hidden = self.table + 53 * TRACK_SIZE
        if n >= 54 and e.mem[hidden]:
            e.write(hidden, bytes(TRACK_SIZE))
        self.emit("  tracks %d" % n)

    def op(self, a):
        e = self.e
        o = a[0]
        v = lambda i: int(a[i], 0)      # noqa: E731
        if o == "load":
            self.load(a[1])
            return
        if o == "tracks":
            self.load_tracks(a[1])
            return
        if o == "g":
            k = a[1]
            if k == "units":
                e.mem[F_UNITS] = v(2) & 0xff
            elif k == "tex":
                self.texmode = v(2)
            elif k == "solid":
                self.solid = v(2)
            elif k == "active":
                self.active = v(2)
            else:
                e.put32({"gametype": F_GT, "players": F_NP,
                         "lang": LANGUAGE, "opts": F_OPTS,
                         "rtimer": G_RTIMER, "relapsed": G_RELAPSED,
                         "seed": G_SEED, "rpnp": RP + 48,
                         "rpnai": RP + 52}[k], v(2) & M32)
        elif o == "data":
            for k in range(4):
                e.put32(F_DATA + 4 * k, v(1 + k) & M32)
        elif o == "cls":
            self.cls[v(1) & 1] = v(2)
        elif o == "unl":
            self.unl[(v(1), v(2) & 1)] = v(3)
        elif o == "egg":
            self.eggs[(v(1), v(2) & 1)] = v(3)
        elif o == "ev":
            if v(3) == -1:
                self.ev.pop((v(1), v(2) & 1), None)
            else:
                self.ev[(v(1), v(2) & 1)] = (v(3), v(4))
        elif o == "lap":
            r = self.record(self.laprec, (v(1) % 70, v(2) & 7, v(3) & 1))
            e.write(r, struct.pack("<Ih", v(4) & M32, v(5)))
        elif o == "tot":
            r = self.record(self.totrec, (v(1) % 70, v(2) & 7, v(3) & 1,
                                          self.laps_index(v(4))))
            e.write(r, struct.pack("<Ih", v(5) & M32, v(6)))
        elif o == "xl":
            self.xl[s32(v(1) & M32)] = a[2]
        elif o == "frame":
            n = v(1)
            self.frame = e.alloc(n, align=16) if n else 0
            if n:
                e.write(self.frame, bytes(n))
            for g, x in ((G_FPOS, self.frame), (G_FEND, self.frame + n),
                         (G_FFAIL, 0), (G_FAMOUNT, 0)):
                e.put32(g, x)
        elif o == "msg":
            d = self.data
            e.write(d, struct.pack("<Iiii", v(2) & M32, v(3), v(4), v(5)))
            e.call(F_CALLBACK, v(1), d, limit=200000000)
            self.emit("  data %d %d" % (s32(e.u32(d + 8)),
                                        s32(e.u32(d + 12))))
        elif o == "texloaded":
            if self.load_cb:
                e.call(self.load_cb[0], self.load_cb[1], limit=1000000)
        else:
            raise ValueError(o)
        # The set-up ops change nothing until the next action shows it.
        if o in ("msg", "texloaded"):
            self.dump()


def model(lines):
    return Model().run(lines)


# The line the mutations start at, spelt so that this one does not match.
MUTATIONS_HEADER = "# " + "=" * 61 + " mutations" + NL


def model_cached(lines):
    """model(lines), or its last transcript when nothing it reads has
    changed. Nothing past the mutations' header is the model's."""
    return mutpar.model_cached(
        lines, model, data=[GLOBALB, FRONTB] + [fc.SD / r for r in fc.LOADS],
        cut=MUTATIONS_HEADER)


# ================================================================= build

def build_harness(tmp, name="tracksel_test"):
    return hostbuild.build(tmp, SOURCES, name=name)


run_harness = fc.run_harness
diff = pcc.diff
write_script = fc.write_script


# ============================================================= mutations

H = BTRACKSEL


def M(name, before, after, rel=H):
    return (name, rel, before, after)


MUTATIONS = [
    # The names and the constants.
    M("obj-tod-bar", "#define OBJ_TOD_BAR        0x724e34b0u",
      "#define OBJ_TOD_BAR        0x724e34b1u"),
    M("obj-more-left", "#define OBJ_MORE_LEFT      0x84f544f3u",
      "#define OBJ_MORE_LEFT      0x84f544f4u"),
    M("obj-locked-fade", "#define OBJ_LOCKED_FADE    0xbea3c79cu",
      "#define OBJ_LOCKED_FADE    0xbea3c79du"),
    M("lang-p2p", "#define LANG_POINT2POINT   0xd995",
      "#define LANG_POINT2POINT   0xd994"),
    M("lang-laps-1", "#define LANG_BEST_LAPS_1   0xd6e9",
      "#define LANG_BEST_LAPS_1   0xd6f1"),
    M("bm-pulse-b", "#define BM_PULSE_B 3", "#define BM_PULSE_B 1"),
    M("ticks", "#define TICKS        0.00025f",
      "#define TICKS        0.00026f"),
    M("tod-icon-x", "#define TOD_ICON_X   530.0f",
      "#define TOD_ICON_X   531.0f"),
    M("tod-bar-x", "#define TOD_BAR_X    525.0f",
      "#define TOD_BAR_X    526.0f"),
    M("thumb-y", "#define THUMB_Y      401.0f",
      "#define THUMB_Y      400.0f"),
    M("list-y", "#define LIST_Y       130.0f", "#define LIST_Y       131.0f"),
    M("thumb-centre", "#define THUMB_CENTRE 244.0f",
      "#define THUMB_CENTRE 245.0f"),
    M("tod-row", "#define TOD_ROW      50.0f", "#define TOD_ROW      51.0f"),
    M("lock-start", "#define LOCK_START   650.0f",
      "#define LOCK_START   651.0f"),
    M("lock-slide", "#define LOCK_SLIDE   640.0f",
      "#define LOCK_SLIDE   641.0f"),
    M("lock-delay", "#define LOCK_DELAY   0.4f",
      "#define LOCK_DELAY   0.3f"),
    M("lock-time", "#define LOCK_TIME    0.5f",
      "#define LOCK_TIME    0.6f"),
    M("pulse-rate", "#define PULSE_RATE   9.0f",
      "#define PULSE_RATE   8.0f"),
    M("two-pi", "#define TWO_PI       0x1.921fb4p+2f",
      "#define TWO_PI       0x1.921fb6p+2f"),
    M("rad-to-bam", "#define RAD_TO_BAM   0x1.45f306p+13f",
      "#define RAD_TO_BAM   0x1.45f308p+13f"),
    M("angle-step", "#define ANGLE_STEP   0.01f",
      "#define ANGLE_STEP   0.011f"),
    M("km", "#define KM_PER_MILE  1.6093f", "#define KM_PER_MILE  1.609f"),
    M("feet", "#define M_PER_FOOT   0.3f", "#define M_PER_FOOT   0.3048f"),
    M("tod-icon-1", "0x132521f5u, 0xa05ac96cu,", "0x132521f5u, 0xa05ac96du,"),
    M("tod-icon-3", "0xdaa55f27u, 0x72da223fu,", "0xdaa55f27u, 0x72da223eu,"),
    M("tod-lang-2", "0xd6e1, 0xd6e2, 0xd6e3", "0xd6e1, 0xd6e3, 0xd6e3"),
    M("tod-lang-4", "0xd6e3, 0xd70a}", "0xd6e3, 0xd6e4}"),
    M("difficulty-lang", "{0xd6dc, 0xd6dd, 0xd6de}",
      "{0xd6dc, 0xd6de, 0xd6dd}"),
    M("pick-letter", '{"A", "B", "C"}', '{"A", "C", "B"}'),
    M("pick-tod", '"_OVERCAST", "_SUNSET"', '"_SUNSET", "_OVERCAST"'),
    M("pick-tod-4", '"_NIGHT",\n                                        ""}',
      '"_NIGHT",\n                                        "_NIGHT"}'),
    M("eye", "{25.12f, -2.564f, 16.9f, 0.0f}",
      "{25.12f, -2.564f, 16.8f, 0.0f}"),
    M("look", "{2.56f, -0.512f, 0.512f, 0.0f}",
      "{2.56f, 0.512f, 0.512f, 0.0f}"),
    # bStringHash's carry.
    M("hash-onto", "h = h * 33u + (unsigned char)*s++;",
      "h = h * 31u + (unsigned char)*s++;"),
    # feAlphaAnimation.
    M("fade-any", "flailer_find_object(f->screen, object, FLAILER_TYPE_ANY);",
      "flailer_find_object(f->screen, object, FLAILER_TYPE_BITMAP);"),
    M("fade-scale-bitmap",
      "ee_trunc_w(f->el[n].alpha[i] * s), i);",
      "ee_trunc_w(f->el[n].alpha[0] * s), i);"),
    M("fade-restore", "ee_trunc_w(f->el[n].alpha[i]), i);",
      "ee_trunc_w(f->el[n].alpha[i] * 0.5f), i);"),
    M("fade-restore-object",
      "flailerobject_set_alpha(o, ee_trunc_w(f->el[n].alpha[0]));",
      "(void)o;"),
    # AnimationGroup.
    M("slide-group", "    if (a->group)\n", "    if (!a->group)\n"),
    M("slide-aim", "if (v != s->val) s->state = 2;",
      "if (v != s->val) s->state = 1;"),
    M("slide-threshold", "a->spline.arrivalThreshold = 1.0f;",
      "a->spline.arrivalThreshold = 2.0f;"),
    M("slide-duration", "a->spline.duration = duration;",
      "a->spline.duration = 1.0f;"),
    M("slide-saved-y", "slidePlace(a, ee_trunc_w(a->spline.val), a->savedY);",
      "slidePlace(a, ee_trunc_w(a->spline.val), a->savedX);"),
    M("slide-restore", "slidePlace(a, a->savedX, a->savedY);",
      "(void)a;"),
    # The track table.
    M("unavail-gt5", "if (Fred.GameType == 5 || Fred.GameType == 7) {",
      "if (Fred.GameType == 4 || Fred.GameType == 7) {"),
    M("unavail-gt7", "Fred.GameType == 5 || Fred.GameType == 7) {",
      "Fred.GameType == 5 || Fred.GameType == 6) {"),
    M("load-tod", "ti->TimeOfDay == d[3])", "ti->TimeOfDay == d[2])"),
    M("load-same", "ti->SameAsTrackNumber == d[0] &&",
      "ti->TrackNumber == d[0] &&"),
    M("vis-order", "if (isTrackUnavailable(track)) v = 1;",
      "if (v == 0 && isTrackUnavailable(track)) v = 1;"),
    # SelectableTrack.
    M("scroll-wrap-up", "t->curTOD = old + 1 < t->nTOD ? old + 1 : 0;",
      "t->curTOD = old + 1 < t->nTOD ? old + 1 : old;"),
    M("scroll-wrap-down", "t->curTOD = old > 0 ? old - 1 : t->nTOD - 1;",
      "t->curTOD = old > 0 ? old - 1 : 0;"),
    M("track-tod-4", "ti->SameAsTrackNumber != base->TrackNumber) continue;",
      "ti->SameAsTrackNumber != base->TrackNumber || ti->TimeOfDay > 3) "
      "continue;"),
    M("track-height", "    t->height = off;\n",
      "    t->height = off - TOD_ROW;\n"),
    M("track-model", 'hashf("TRACK%d_MINI", base->TrackNumber)',
      'hashf("TRACK%d_MINI", base->TrackNumber + 1)'),
    M("draw-tod-y", "flailerobject_set_top_left_y(o, y + t->tod[i].offset);",
      "flailerobject_set_top_left_y(o, y);"),
    M("draw-tod-bar", "ee_trunc_w(y + t->tod[t->curTOD].offset - 5.0f));",
      "ee_trunc_w(y + t->tod[t->curTOD].offset - 4.0f));"),
    # SelectableTrackManager.
    M("build-base", "if (!ti || ti->SameAsTrackNumber != ti->TrackNumber) "
      "continue;", "if (!ti) continue;"),
    M("build-thumb-r", 'hashf("TN_TRACK%dR", (int)track)',
      'hashf("TN_TRACK%d", (int)track)'),
    M("build-hidden-step", "                flailer_set_visibility(screen, "
      "thumb, 0);\n                continue;",
      "                flailer_set_visibility(screen, thumb, 0);\n"
      "                x += m->spacing;\n                continue;"),
    M("build-egg", "if (h->eggActive && h->eggActive(h->user, track, dir)) "
      "vis = 0;", "(void)0;"),
    M("build-egg-dir", "h->eggActive(h->user, track, dir)",
      "h->eggActive(h->user, track, 0)"),
    M("find-dir", "&& m->tracks[i].dir == dir)", ")"),
    M("set-first", "if (i < 0) i = m->count ? 0 : -1;",
      "if (i < 0) i = m->count ? m->count - 1 : -1;"),
    M("set-tod-fallback", "if (!setTimeOfDay(&m->tracks[i], tod)) "
      "setTimeOfDay(&m->tracks[i], 0);", "setTimeOfDay(&m->tracks[i], tod);"),
    M("scroll-stop-right", "if (n + 1 < m->count) n++;",
      "n = n + 1 < m->count ? n + 1 : 0;"),
    M("scroll-stop-left", "if (n > 0) n--;",
      "n = n > 0 ? n - 1 : m->count - 1;"),
    M("thumbs-step", "        x += m->spacing;\n    }\n    if (mgrCur(m))",
      "        x += m->spacing + 1.0f;\n    }\n    if (mgrCur(m))"),
    # The slideshow.
    M("pick-dir", 'const char*     dir = t->dir == 1 ? "R_" : "";',
      'const char*     dir = t->dir == 1 ? "R" : "";'),
    M("pick-random", "int32_t         r   = bRandomI(3, &bDefaultSeed);",
      "int32_t         r   = bRandomI(2, &bDefaultSeed);"),
    M("pick-name", '"TRACK%d%s%s%s", t->ti->TrackNumber, dir,',
      '"TRACK%d%s%s%s", t->ti->SameAsTrackNumber + 1, dir,'),
    M("load-tries", "for (i = 0; i < 10; i++) {\n        uint32_t hash = "
      "showPick", "for (i = 0; i < 1; i++) {\n        uint32_t hash = "
      "showPick"),
    M("load-same-tex", "if (hash == 0 || hash == s->tex) continue;",
      "if (hash == 0) continue;"),
    M("load-loaded", "        s->loaded = 0;\n        if (h->packLoad)",
      "        if (h->packLoad)"),
    M("show-same", "    if (t == s->track) return;\n    s->track = t;\n"
      "    flailer_change_texture",
      "    s->track = t;\n    flailer_change_texture"),
    M("show-front", "fadeScale(&s->front, 1.0f);\n    fadeScale(&s->back, "
      "0.0f);", "fadeScale(&s->back, 0.0f);"),
    M("show-unload", "    if (h->packUnloadAll) h->packUnloadAll(h->user, "
      "s->pack);\n    showMaybeLoad(s, h);\n}",
      "    showMaybeLoad(s, h);\n}"),
    M("show-wait", "4.0f < (float)(now - s->t0) * TICKS && s->loaded",
      "3.0f < (float)(now - s->t0) * TICKS && s->loaded"),
    M("show-wait-loaded", "(float)(now - s->t0) * TICKS && s->loaded)",
      "(float)(now - s->t0) * TICKS)"),
    M("show-xfade", "float f = (float)(now - s->t1) * TICKS * 0.5f;",
      "float f = (float)(now - s->t1) * TICKS;"),
    M("show-back-tex", "flailer_change_texture(s->screen, OBJ_SHOW_BACK, "
      "s->tex);", "(void)0;"),
    M("show-end-t0", "            s->t0    = now;\n",
      "            s->t0    = s->t1;\n"),
    M("show-destroy-unload", "    if (h->packUnloadAll) h->packUnloadAll("
      "h->user, s->pack);\n    if (s->pack && h->packDelete)",
      "    if (s->pack && h->packDelete)"),
    # The time-of-day menu.
    M("todm-same", "    if (t == m->track) return -1;\n",
      ""),
    M("todm-number", "uint32_t item = hashf(\"MENUITEM_%d\", (int)n);",
      "uint32_t item = hashf(\"MENUITEM_%d\", (int)tod + 1);"),
    M("todm-back-number", "uint32_t back = hashf(\"TOD_BACKING_%d\", "
      "(int)n);", "uint32_t back = hashf(\"TOD_BACKING_%d\", (int)tod + 1);"),
    M("todm-count", "                r = n;\n            }\n            n++;",
      "                r = n;\n            }\n            n += 0;"),
    M("todm-hide-icon", "            flailer_set_visibility(m->screen, "
      "kTODIcon[tod], 0);\n", ""),
    # The records.
    M("valid-zero", "return t->PackedTime != 0 && t->PackedTime != "
      "HIGH_SCORE_NO_TIME;", "return t->PackedTime != HIGH_SCORE_NO_TIME;"),
    M("total-opts", "if (r->cur < 0 || r->n == 0 || Fred.MainMenuOpts[0] "
      "!= 0) {", "if (r->cur < 0 || r->n == 0) {"),
    M("total-laps-2", "if (r->rec[r->cur].laps >= 2)",
      "if (r->rec[r->cur].laps >= 4)"),
    M("rec-cls-2p", "if (Fred.NumPlayerCars == 2) {",
      "if (Fred.NumPlayerCars == 3) {"),
    M("rec-cls-min", "if (b < a) cls = b;", "if (b > a) cls = b;"),
    M("rec-lap-opts", "if (validTime(&time) && Fred.MainMenuOpts[0] == 0) {",
      "if (validTime(&time)) {"),
    M("rec-p2p", "    if (!t->ti->Point2Point) {\n        for (i = 0; i < 4;",
      "    if (1) {\n        for (i = 0; i < 4;"),
    M("rec-laps-table", "{1, 2, 4, 8}", "{1, 2, 3, 8}"),
    M("rec-skip", "if (!validTime(&tbl->Time)) continue;", "(void)0;"),
    M("rec-time", "    r->flag = 1;\n    r->time = RealTimer;\n}",
      "    r->flag = 1;\n}"),
    M("rec-wait", "if (!(5.0f < e)) return;", "if (!(4.0f < e)) return;"),
    M("rec-single", "if (r->n < 2) {", "if (r->n < 1) {"),
    M("rec-fade-out", "ee_trunc_w((5.5f - e) * 2.0f * 128.0f));",
      "ee_trunc_w((5.5f - e) * 2.0f * 127.0f));"),
    M("rec-fade-in", "ee_trunc_w((1.0f - (6.0f - e) * 2.0f) * 128.0f));",
      "ee_trunc_w((1.0f - (6.0f - e) * 2.0f) * 127.0f));"),
    M("rec-next-wrap", "r->cur = r->cur + 1 < r->count ? r->cur + 1 : 0;",
      "r->cur = r->cur + 1 < r->count ? r->cur + 1 : r->cur;"),
    M("rec-flag", "            recDisplayBestTotal(r, h);\n"
      "            r->flag = 0;", "            recDisplayBestTotal(r, h);"),
    # The locked box.
    M("lock-vis-1", "    if (t->vis < 2) {", "    if (t->vis < 1) {"),
    M("lock-arrows", "        flailer_set_visibility(l->screen, OBJ_TOD_UP, "
      "0);\n        flailer_set_visibility(l->screen, OBJ_TOD_DOWN, 0);\n"
      "    }", "    }"),
    M("lock-text-hide", "    flailer_set_visibility(l->screen, "
      "OBJ_LOCKED_TEXT, 0);\n", ""),
    M("lock-blurb-dir", "t->ti->TrackNumber, t->dir);\n    else",
      "t->ti->TrackNumber, 0);\n    else"),
    M("lock-start-time", "    l->start = RealTimer;\n", ""),
    M("lock-delay-cmp", "if (LOCK_DELAY < e) slideAnimate(&l->slide);",
      "if (LOCK_DELAY <= e + 0.05f) slideAnimate(&l->slide);"),
    M("lock-alpha-full", "f < 1.0f ? ee_trunc_w((float)l->alpha * f) : "
      "l->alpha);", "ee_trunc_w((float)l->alpha * f));"),
    M("lock-render-vis", "l->track->vis != 0 && h->renderTextIntoRectangle",
      "l->track->vis == 2 && h->renderTextIntoRectangle"),
    # The screen.
    M("logo-fmt", 'hashf("LOGOTRACK%2d", (int)track)',
      'hashf("LOGOTRACK%d", (int)track)'),
    M("logo-r", 'if (dir == 1) hash = hashOnto("R", hash);', "(void)0;"),
    M("logo-fr", "if (language(h) == 1) hash = hashOnto(\"_FR\", hash);",
      "(void)0;"),
    M("data-tod", "p->data[3] = c ? c->TimeOfDay : 0;",
      "p->data[3] = 0;"),
    M("data-dir", "p->data[2] = t->dir;", "p->data[2] = 0;"),
    M("resync-c-base", "    if (!c) c = base;\n", "    c = base;\n"),
    M("resync-kind", "base->Point2Point ? LANG_POINT2POINT : LANG_CIRCUIT",
      "LANG_CIRCUIT"),
    M("resync-miles", '(double)base->Length, "mi", kind);',
      '(double)base->Length, "km", kind);'),
    M("resync-elev-c", "(double)c->MinElevation, (double)c->MaxElevation,",
      "(double)base->MinElevation, (double)c->MaxElevation,"),
    M("resync-difficulty", "(uint32_t)kDifficultyLang[c->Difficulty]);",
      "(uint32_t)kDifficultyLang[base->Difficulty]);"),
    M("resync-name-dir", "? c->TrackLanguageID\n", "? c->ReverseTrackLanguageID\n"),
    M("resync-tod-arrows", "if (t->nTOD >= 2) {", "if (t->nTOD >= 1) {"),
    M("resync-tod-down", "ee_trunc_w(t->height + LIST_Y));",
      "ee_trunc_w(t->height));"),
    M("resync-more-left", "p->mgr.cur > 0);", "p->mgr.cur >= 0);"),
    M("resync-more-right", "p->mgr.cur + 1 < p->mgr.count);",
      "p->mgr.cur < p->mgr.count);"),
    M("resync-order", "    r = todSetCurrentTrack(&p->todMenu, h, t);\n"
      "    recSetCurrentTrack(&p->records, h, t);",
      "    recSetCurrentTrack(&p->records, h, t);\n"
      "    r = todSetCurrentTrack(&p->todMenu, h, t);"),
    M("laps-gt3", "&& (Fred.GameType == 3\n", "&& (Fred.GameType == 4\n"),
    M("laps-gt7-2p", "(Fred.GameType == 7 && Fred.NumPlayerCars == 2));",
      "(Fred.GameType == 7));"),
    M("laps-p2p", "    return !ti->Point2Point\n           && (",
      "    return ti != NULL\n           && ("),
    M("race-gt3-type", "            rp->RaceType      = 1;\n"
      "            rp->NumLapsInRace = p->data[1];",
      "            rp->RaceType      = 3;\n"
      "            rp->NumLapsInRace = p->data[1];"),
    M("race-gt4-laps", "rp->NumLapsInRace = rp->Point2Point ? 1 : 2;",
      "rp->NumLapsInRace = rp->Point2Point ? 2 : 1;"),
    M("race-gt5-laps", "int32_t laps  = rp->NumAICars + rp->NumPlayerCars - 1;",
      "int32_t laps  = rp->NumAICars + rp->NumPlayerCars;"),
    M("race-gt5-clamp", "rp->NumLapsInRace = laps > 0 ? laps : 0;",
      "rp->NumLapsInRace = laps;"),
    M("race-gt7-laps", "rp->NumLapsInRace = rp->NumPlayerCars == 1 ? 0 : "
      "p->data[1];", "rp->NumLapsInRace = p->data[1];"),
    M("race-track", "rp->TrackNumber   = trackNumberToLoad("
      "Fred.SelectTrackScreenData);", "rp->TrackNumber   = p->data[0];"),
    M("race-dir", "rp->TrackDirection = t->dir;", "(void)0;"),
    M("race-copy", "    memcpy(Fred.SelectTrackScreenData, p->data, "
      "sizeof(p->data));\n    rp->TrackDirection",
      "    rp->TrackDirection"),
    M("new-x-duration", "p->x.duration = 0.5f;", "p->x.duration = 0.6f;"),
    M("new-y-duration", "p->y.duration = 0.5f;", "p->y.duration = 0.6f;"),
    M("new-x-flags", "    p->x.flags    = 0;\n", "    p->x.flags    = 1;\n"),
    M("new-param", "    data->param = resyncScreen(p);\n",
      "    resyncScreen(p);\n"),
    M("new-mover-view", "still_camera_mover_init(&p->mover, 1);",
      "still_camera_mover_init(&p->mover, 0);"),
    M("new-hl-color", "(int32_t)BANIM_BLOOM_COLOR);",
      "(int32_t)BANIM_BLOOM_COLOR + 1);"),
    M("delete-copy", "    memcpy(Fred.SelectTrackScreenData, p->data, "
      "sizeof(p->data));\n    if (p->haveMover)", "    if (p->haveMover)"),
    M("tick-phase-wrap", "if (TWO_PI < p->phase) p->phase -= TWO_PI;",
      "(void)0;"),
    M("tick-pulse", "ee_trunc_w((bSinF(p->phase) + 1.0f) * 64.0f);",
      "ee_trunc_w((bSinF(p->phase) + 1.0f) * 63.0f);"),
    M("tick-angle-wrap", "if (TWO_PI < btracksel_model_angle) "
      "btracksel_model_angle -= TWO_PI;", "(void)0;"),
    M("tick-xy", "mgrDrawThumbnails(&p->mgr, p->screen, p->x.val, p->y.val);",
      "mgrDrawThumbnails(&p->mgr, p->screen, p->x.val, LIST_Y);"),
    M("render-solid", "if (t && t->model.Solid && m) {", "if (t && m) {"),
    M("render-angle", "(uint16_t)ee_trunc_w(btracksel_model_angle * "
      "RAD_TO_BAM));", "(uint16_t)ee_trunc_w(btracksel_model_angle));"),
    M("joy-p2", "(data->port == 1 && Fred.NumPlayerCars == 2)",
      "(data->port == 1)"),
    # The callbacks.
    M("select-vis", "if (!passJoystickTest(data) || !t || t->vis != 0) {",
      "if (!passJoystickTest(data) || !t || t->vis == 2) {"),
    M("select-noise", "                data->noise = 0;\n                "
      "break;\n            }\n            if (canSelectLaps",
      "                break;\n            }\n            if (canSelectLaps"),
    M("tod-up-dir", "scrollTimeOfDay(t, msg == BMSG_MENUITEM_PAD_UP ? -1 : 1)",
      "scrollTimeOfDay(t, msg == BMSG_MENUITEM_PAD_UP ? 1 : -1)"),
    M("tod-noise", "moved(p, data, msg == BMSG_MENUITEM_PAD_UP ? 11 : 10);",
      "moved(p, data, msg == BMSG_MENUITEM_PAD_UP ? 10 : 11);"),
    M("tod-param", "                data->noise = 0;\n                "
      "data->param = 1;\n            }",
      "                data->noise = 0;\n            }"),
    M("lr-noise", "moved(p, data, msg == BMSG_MENUITEM_PAD_LEFT ? 11 : 10);",
      "moved(p, data, msg == BMSG_MENUITEM_PAD_LEFT ? 10 : 11);"),
    M("lr-speaking", "                speechFade(h, 1.0f);\n"
      "                p->speaking = 0;", "                speechFade(h, "
      "1.0f);"),
    M("square-vis", "if (!t || t->vis != 0) break;", "if (!t) break;"),
    M("square-fade", "            } else {\n                speechFade(h, "
      "1.0f);\n            }", "            }"),
    M("start-noise", "        case BMSG_SCREEN_START_BUTTON:\n"
      "            data->noise = 0;\n            break;",
      "        case BMSG_SCREEN_START_BUTTON:\n            break;"),
    M("lap-left-noise", "data->noise = 1;\n            p->data[1] >>= 1;",
      "data->noise = 2;\n            p->data[1] >>= 1;"),
    M("lap-left-wrap", "if (p->data[1] < 2) p->data[1] = 8;",
      "if (p->data[1] < 1) p->data[1] = 8;"),
    M("lap-right-wrap", "if (p->data[1] > 8) p->data[1] = 2;",
      "if (p->data[1] > 8) p->data[1] = 1;"),
    M("lap-ud-param", "            data->noise = 0;\n            "
      "data->param = 1;\n            break;\n        case "
      "BMSG_SCREEN_BACK_BUTTON:", "            data->noise = 0;\n"
      "            break;\n        case BMSG_SCREEN_BACK_BUTTON:"),
    M("back-noise", "data->noise = 6;", "data->noise = 5;"),
    M("back-resync", "            data->noise = 6;\n            "
      "resyncScreen(p);\n", "            data->noise = 6;\n"),
    M("back-active", "highlightItem(p, h->getActiveMenuItem\n",
      "highlightItem(p, 0 && h->getActiveMenuItem\n"),
    M("lap-start-joy", "if (passJoystickTest(data)) startRace(p);",
      "startRace(p);"),
    M("unactivate-fade", "            g_m->screen = NULL;\n"
      "            speechFade(h, 1.0f);\n", "            g_m->screen = NULL;\n"),
]

EQUIVALENT = {
    "lock-slide": "the constructor's resyncScreen sets the slide up again "
                  "from 650 before anything reads it, and the group moves "
                  "by its master, so where it was does not matter",
    "fade-any": "the slideshow's two objects, the only ones faded, are "
                "bitmaps",
    "fade-restore-object": "the same: no object faded is anything but a "
                           "bitmap",
    "todm-back-number": "FRONTB has no TOD_BACKING_ object",
    "lock-vis-1": "BuildList leaves out every track of visibility 1, so no "
                  "track in the list has it",
    "lock-render-vis": "the same: a track's visibility is 0 or 2",
    "select-vis": "the same",
    "logo-fmt": "every track number is two digits",
    "resync-c-base": "every variant has its base track's elevations and "
                     "difficulty, and Select Track's screen has no "
                     "TRACK_NAME object (FRONTB's, 0:857, is another "
                     "screen's)",
    "resync-elev-c": "every variant has its base track's elevations",
    "resync-difficulty": "every variant has its base track's difficulty",
    "resync-name-dir": "Select Track's screen has no TRACK_NAME object",
    "resync-tod-arrows": "every base track has two times of day",
    "tod-up-dir": "the same: round two, up and down are one step",
    "tod-param": "the same, and curTOD is never -1 on a track in the list: "
                 "the scroll never fails",
    "tick-xy": "the y spline is snapped to LIST_Y in the constructor and "
               "never aimed anywhere else",
}


def mutate_pass(only=None, jobs=None):
    todo = [m for m in MUTATIONS if only is None or m[0] in only]
    if only:
        unknown = set(only) - {m[0] for m in MUTATIONS}
        if unknown:
            print("no such mutation: %s" % ", ".join(sorted(unknown)))
            return 1
    lines = script()
    base = model_cached(lines)
    indir = tempfile.TemporaryDirectory()
    scp = write_script(indir.name, lines)
    with tempfile.TemporaryDirectory() as tmp:
        exe = build_harness(tmp)
        out = Path(tmp) / "base.txt"
        t0 = time.monotonic()
        run_harness(exe, scp, out)
        took = time.monotonic() - t0
        got = out.read_text(encoding="latin-1").splitlines()
        if diff(base, got, quiet=True):
            print("base already differs -- fix that before mutating")
            return 1
        print("base: %d ops, %d lines, 0 differ" % (len(lines), len(got)),
              flush=True)

    limit = mutpar.timeout_for(took)
    tally = mutpar.run_pass(
        todo, SOURCES, "tracksel_test",
        lambda exe, out: mutpar.run_exe([exe, scp], out, limit),
        base, diff, EQUIVALENT, jobs)
    indir.cleanup()
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

    lines = script()
    got = model_cached(lines)
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
