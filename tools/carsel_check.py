#!/usr/bin/env python3
"""Cross-check 3DS Files/source/bcarsel.c, car select, against the retail
image, SLES_507.31.

**The model** is retail's own: SelectCarScreen::SelectCarScreenCallback
(0x00198928) and everything under it -- SelectCarScreen's constructor,
ActivateCarSelector, DeactivateCarSelector, SetSelectedCars and
MaybeContinueToNextScreen; CarSelector's constructor, destructor,
ScreenCallback, Tick, the swatches, thumbnails, logo, info bar, help and
popups; VisibleCarSet, its copy and CarListSort through bTList's Sort; the
unlock box and FormatUnlockBlurbForCar; feAlphaAnimation and
AnimationGroup with cPoint's SplineSeek -- the JoyHandler through its
bridge (0x00198e28), as AddJoyHandler would call it; the preload (0x00194898)
and CloseSelectCarScreen; and under all of them the Flailer runtime on
FRONTB's Flailer chunk, with GLOBALB's car records and skins. The harness
(tools/src/carsel_test.c) runs bcarsel.c over flailer.c, banim.c,
blist.c, nfsrewards.c and cartypeinfo.c on the same files.

**The stubs** are what the selector does not own, scripted the same on both
sides and logged in the same words: GetTranslatedString (each id its own
buffer), MakeFrontendSound and StopFrontendSound, SetHelpOverride, the help
menu's IsActive, the popups' Summon and Dismiss, ChangeToScreen and
StartRace, CarLoader's Load, IsLoaded, Unload and BeginLoading (and its two
flags, which the screen's constructor sets), the easter eggs, the event
trees' IsCarAnEventReward, RenderTextIntoRectangle, the commentary's
SPCH_AddEventV and fade, StopMovie, the screen list's per-pad filter and
AssignCarOfType. And the 3D the selector drives (SC-2c): the two
FrontEndRenderingCars' constructor (which only clears and keeps the view),
ReInit and destructor; SelectCarCameraMover's constructor, destructor and
SetMode, logged, and its five setters, which keep what they are given;
eModel's Init (its Solid scripted), UnInit, destructor and Render;
SetSelectCarLighting; and GetTextureInfo, which answers each swatch with a
texture made from its hash, or with one of four kinds of nothing.
UpdateRenderingCarParameters, UpdateCarCover, ShowLoadedCar and the
lighting's sum run for real, as do eIdentity and the rotations under them,
and the frame-malloc inline over a scripted buffer. The spotlights and the
nebula (SC-3) are stubbed silent.

**Compared** are the stubs' logs, what the callback leaves in the
ScreenCallbackData, and after each op every line that changed: the screen,
each selector's fields, its car list in order, the unlock box, the
thumbnails' spline, the swatches, both rendering cars (flags, model,
lights, place and every matrix) and the camera's fields; the frame
buffer; the preload's two cars; the CarLoader's flags; both players'
gearbox and handling; and every Flailer object's bytes.

**The script** runs You're The Cop's player, a single race (a tree event)
and the championship with one player, and two players on both halves;
across locked, covered, egged and hidden cars, every skin, the orbit view
in and out (and its timeout), the unlock box hidden and back, every popup
and every way out of it, the help menu up, both units, three languages and
every event tree; and the preload and the close.

    python tools/carsel_check.py
    python tools/carsel_check.py --mutate [--only a,b] [--jobs N]
    python tools/carsel_check.py --dump out/carsel

The model's transcript is cached (tools/mutpar.py), so a run after one
that changed only the port, the harness or the mutations skips the seven
minutes. The mutants build outside the tree, sixteen at once.
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
import retail_model                     # noqa: E402
from mipsemu import M32, s32            # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

HARNESS = "tools/src/carsel_test.c"
BCARSEL = "3DS Files/source/bcarsel.c"
SOURCES = [HARNESS, BCARSEL, "3DS Files/source/nfsrewards.c",
           "3DS Files/source/banim.c", "3DS Files/source/blist.c",
           "3DS Files/source/bmath.c", "3DS Files/source/bmathtab.c",
           "3DS Files/source/flailer.c", "3DS Files/source/bprintf.c",
           "3DS Files/source/bui.c", "3DS Files/source/bchunk.c",
           "3DS Files/source/cartypeinfo.c", "3DS Files/source/langtab.c",
           "3DS Files/source/emath.c", "3DS Files/source/bmatrix.c",
           "3DS Files/source/bvector.c"]

GLOBALB = ROOT / "extracted-retail" / "GLOBAL" / "GLOBALB.BUN"
FRONTB = fc.SD / "FRONTEND" / "FRONTB.BUN"

GP = fc.GP
FRED = 0x002fc050
F_UNITS = FRED + 333
F_GT = FRED + 67372
F_NP = FRED + 67380
F_FPI = FRED + 67384
FRED_SIZE = 70936
FPI_SIZE = 1744
FPI_SETTINGS = 1604
FPI_RIDES = 1652
FPI_POINTS = 1740
LANGUAGE = 0x0031c1c8                   # CurrLanguage
LOADER = 0x00313a38                     # TheCarLoader
SPECS = 0x0030d578                      # CarLanguageInfo, 50 rows of 28

G_RTIMER = GP - 19608
G_RTIME = GP - 19604
G_RFRAMES = GP - 19600
G_RELAPSED = GP - 19596
G_SOUND = GP - 23056                    # SoundEnabled
G_ALLCARS = GP - 23120
G_SCREEN = GP - 19968                   # pSelectCarScreen
G_PRE = GP - 20104                      # the preload's two cars
G_MENU = GP - 21324                     # CurrentMenuSystem
G_CARS = GP - 20616                     # CarTypeInfoArray
G_SKINS = GP - 20612
G_NSKINS = GP - 20608
G_FPOS = GP - 19388                     # CurrentBufferPos
G_FEND = GP - 19384                     # CurrentBufferEnd
G_FFAIL = GP - 19372                    # FrameMallocFailed
G_FAMOUNT = GP - 19368                  # FrameMallocFailAmount

F_CALLBACK = 0x00198928
F_PRELOAD = 0x00194898
F_CLOSE = 0x00194fb0
F_SELECTOR = 0x001950d0                 # CarSelector's constructor
# selectcar.cpp's static initializer: the camera's three offsets, eight
# vectors nothing here reads, and the two FlailerScreenConfigs, whose
# constructor (0x0016ad88) is stubbed silent.
F_SINIT = 0x00198bc8

S_XL = 0x0021e560
S_XS = 0x0021e508
S_SOUND = 0x0016e038
S_STOPSOUND = 0x0016e0e8
S_HELP = 0x0016d448
S_HELPACTIVE = 0x001e4170
S_SUMMON = 0x0016cd68
S_DISMISS = 0x0016cdc0
S_CHANGE = 0x0014cc78
S_STARTRACE = 0x00184f68
S_LOAD = 0x001b0560
S_ISLOADED = 0x001b06f8
S_UNLOAD = 0x001b07e0
S_BEGIN = 0x001b0b00
S_EGG = 0x0024f8f8
S_ISEVENT = 0x001ff8b8
S_FINDEVENT = 0x001ff9d8
S_RTEXT = 0x001451e0
S_FERC = 0x0011e5c0
S_REINIT = 0x0011e758
S_SPEECH = 0x00209ef0
S_FADE = 0x0020a290
S_SPEAK = 0x002919d0
S_CONVERT = 0x002232f8
S_STOPMOVIE = 0x0016d0a0
S_PERPORT = 0x0016caa8
S_ASSIGN = 0x00187a68
S_ADDJOY = 0x00154140
S_REMOVEJOY = 0x001541e8
S_OMALLOC = 0x00257c80
S_MOVER = 0x0015a698
MOVER_VT = 0x002b1950                   # _vt$20SelectCarCameraMover
S_FERC_DTOR = 0x0011e7d8
S_MODEL_INIT = 0x0010c558
S_MODEL_UNINIT = 0x0010c5b0
S_MODEL_DTOR = 0x00114cf0
S_MODEL_RENDER = 0x0010dc80
S_CAM_MODE = 0x0015aa08
S_CAM_RADIUS = 0x0015a940
S_CAM_OFFSET = 0x0015a948
S_CAM_ORBIT = 0x0015a958
S_CAM_FOV = 0x0015a968
S_CAM_ORIENT = 0x0015a978
S_CAM_DTOR = 0x0015a880
S_LIGHTING = 0x001157c0
S_TEXINFO = 0x001abf48
SILENT = [
    0x0016ad88,                         # FlailerScreenConfig's constructor
    0x0011e858,                         # FrontEndRenderingCar's alpha
    0x001273d8, 0x001274a0, 0x00127688, 0x00124e20, 0x001276a8,  # Acid
    0x001963b8,                         # UpdateNebula
    0x0016c3b0,                         # SetEmitterState
    0x00114e98, 0x00114e90,             # delete
]

FERC_SIZE = 656
MOVER_SIZE = 192

CAR_REC = 1376
CAR_CHUNK, SKIN_CHUNK = 0x34600, 0x34601

SCREEN_1P = 0xb5074ab4
SCREEN_2P = 0x18dc8e52
SCREEN_2P_LO = 0x18dc8e53
CHOOSE = 0x52e039f3

SELECT, LEFT, RIGHT, UP, DOWN = 1, 6, 7, 8, 9
ACTIVATE, UNACTIVATE, BACK, TICK, RENDER, DISMISS = 11, 12, 17, 18, 19, 21

# The frame buffer: room for 400 platforms, then the rest fail, for the
# runs before s_extra; room for all after its own tests.
FRAME_FIRST = 64 * 400 + 32
FRAME = 1 << 16


def F(v):
    return "%#x" % struct.unpack("<I", struct.pack("<f", v))[0]


def cx(v):
    """C's %#x."""
    return "0x%x" % v if v else "0"


# ================================================================ the data

def globalb_chunks():
    data = GLOBALB.read_bytes()
    out = {}
    off = 0
    while off + 8 <= len(data):
        cid, size = struct.unpack_from("<II", data, off)
        if cid in (CAR_CHUNK, SKIN_CHUNK) and cid not in out:
            out[cid] = data[off:off + 8 + size]
        off += 8 + size
    return out


class Car(object):
    def __init__(self, t, r):
        self.type = t
        self.name = r[0:32].split(b"\0")[0].decode("latin-1")
        self.hp = struct.unpack_from("<b", r, 228)[0]
        self.nskins = struct.unpack_from("<b", r, 229)[0]
        self.cls = struct.unpack_from("<b", r, 230)[0]
        self.usage = struct.unpack_from("<i", r, 1336)[0]
        self.skins = list(r[1348:1348 + 10])
        self.default = struct.unpack_from("<i", r, 1364)[0]


def cars():
    d = globalb_chunks()[CAR_CHUNK]
    return [Car(t, d[16 + CAR_REC * t:16 + CAR_REC * (t + 1)])
            for t in range(64)]


def spec_ops():
    """Each car's CarSpecs, as InitCarInfo finds them: the first of the 50
    rows whose CarType is the car's, else the first row."""
    e = retail_model.RetailEmu(ieee=True)
    rows = [struct.unpack("<7i", bytes(e.mem[SPECS + 28 * i:
                                             SPECS + 28 * (i + 1)]))
            for i in range(50)]
    out = []
    for t in range(64):
        row = next((r for r in rows if r[0] == t), rows[0])
        out.append("spec|%d|%s" % (t, "|".join(str(x) for x in row[1:])))
    return out, rows


# ================================================================== script

class Script(object):
    def __init__(self):
        self.ops = []
        self.rtimer = 1000
        self.rframes = 500
        self.cars = cars()

    def add(self, *ops):
        self.ops += list(ops)

    def g(self, name, v):
        self.ops.append("g|%s|%s" % (name, v))

    def msg(self, m, item=0, port=0, param=-1, noise=-1):
        self.ops.append("msg|%d|%s|%d|%d|%d" % (m, cx(item), port, param,
                                                noise))

    def joy(self, port, ev, pressed):
        self.ops.append("joy|%d|%d|%d" % (port, ev, pressed))

    def tick(self, n=1, ports=(0,), step=67, render=False):
        for _ in range(n):
            self.rtimer += step
            self.rframes += 1
            self.g("rtimer", self.rtimer)
            self.g("rframes", self.rframes)
            for p in ports:
                self.msg(TICK, port=p, param=0, noise=0)
                if render:
                    self.msg(RENDER, port=p, param=0, noise=0)

    def frames(self, d):
        self.rframes += d
        self.g("rframes", self.rframes)

    def statuses(self, p, kind):
        """Player p's cars: the traffic and empty records hidden, the rest
        available, locked, covered or hidden by `kind`."""
        out = []
        for c in self.cars:
            if c.usage == 2 or c.nskins <= 0:
                st, n = 3, 0
            else:
                st = kind(c)
                n = c.nskins
            skins = ",".join(str(x) for x in c.skins[:max(n, 0)]) or "0"
            out.append("fs|%d|%d|%d|%d|%s|%d" % (p, c.type, st, n, skins,
                                                 c.type & 1))
            self.cars_status = getattr(self, "cars_status", {})
            self.cars_status[(p, c.type)] = st
        self.ops += out

    def of(self, p, st, usage=None, skins=1):
        """The real cars of player p in status st."""
        return [c for c in self.cars
                if self.cars_status.get((p, c.type)) == st
                and c.usage != 2 and c.nskins >= skins
                and (usage is None or c.usage == usage)]


def kind_a(c):
    return (0, 0, 1, 4, 0, 2, 4)[(c.type * 5 + 1) % 7]


def kind_b(c):
    return (0, 1, 4, 0, 3, 0)[(c.type * 3 + 2) % 6]


def kind_c(c):
    """Every status, the locked (2) and the hidden (3) among them: with
    AllCarsAvailableInCarSelectScreen both are listed, neither available,
    and the light stays lit on a locked one all the same."""
    return (0, 2, 4, 3, 0, 2, 1)[c.type % 7]


def common(s):
    specs, rows = spec_ops()
    s.add("load|%s" % FRONTB, "cars|%s" % GLOBALB)
    s.add(*specs)
    # The full names: each car's own, two of them the same so the sort's
    # tie-break is taken.
    named = {}
    for t, op in enumerate(specs):
        full = int(op.split("|")[6])
        named.setdefault(full, s.cars[t].name or "CAR%d" % t)
    for full, name in named.items():
        s.add("xl|%s|%s" % (cx(full), name))
    real = [c for c in s.cars if c.usage != 2 and c.nskins > 0]
    a, b = real[3], real[4]
    s.add("xl|%s|Twin" % cx(int(specs[a.type].split("|")[6])),
          "xl|%s|Twin" % cx(int(specs[b.type].split("|")[6])))
    for k, v in (("units", 0), ("lang", 0), ("sound", 1), ("allcars", 0),
                 ("help", 0), ("pi", 3), ("gametype", 7), ("players", 1)):
        s.g(k, v)
    s.g("relapsed", F(1.0 / 60))
    s.add("frame|%d" % FRAME_FIRST)
    s.g("rtimer", s.rtimer)
    s.g("rframes", s.rframes)


def walk(s, port, n, d=RIGHT, render=True, ticks=1, ports=None, every=1):
    """n presses of d, each rendered, a tick after every `every`."""
    ports = ports or (port,)
    for i in range(n):
        s.msg(d, port=port)
        if render:
            for p in ports:
                s.msg(RENDER, port=p, param=0, noise=0)
        if (i + 1) % every == 0:
            s.tick(ticks, ports=ports)


def s_cop(s):
    """You're The Cop, one player."""
    s.g("gametype", 7)
    s.g("players", 1)
    s.statuses(0, kind_a)
    cop = s.of(0, 0, usage=1, skins=2)[0]
    s.add("ride|0|7|%d|%d" % (cop.type, cop.skins[1]), "pts|0|123456",
          "isl|%d|0" % cop.type)
    s.msg(ACTIVATE, SCREEN_1P, 0)
    s.tick(3)
    s.add("isl|%d|1" % cop.type)
    s.tick(48, render=True)
    # The camera's blend turns the front wheels straight. At 0.0001 the
    # turn is 4239.58, which truncates.
    for b in (0.5, 1.0, 0.3, 0.0001, 0.0):
        s.add("blend|0|%s" % F(b))
        s.tick(1)
    # The orbit view, the sticks and the rest of the events.
    s.joy(0, 33, 1)
    s.joy(0, 33, 0)
    for port, ev, v in ((0, 35, 1), (0, 35, 0), (1, 36, 1), (0, 37, 1),
                        (0, 38, 0), (0, 38, 1), (1, 41, 200), (0, 42, 10),
                        (0, 41, 0), (0, 42, 255), (0, 43, 128), (0, 39, 1),
                        (0, 40, 1), (0, 34, 1), (0, 44, 1), (1, 41, 128)):
        s.joy(port, ev, v)
    s.tick(36)
    s.msg(LEFT)
    s.msg(SELECT, CHOOSE)
    s.msg(UP)
    s.msg(BACK)
    s.tick(36)
    # Orbit again, left alone: still there at 40 seconds, back a frame later.
    s.joy(1, 33, 1)
    s.tick(36)
    s.frames(2400 - 36 - 1)
    s.tick(1)
    s.tick(1)
    s.tick(36)
    # Not with the help menu up.
    s.g("help", 1)
    s.joy(0, 33, 1)
    s.g("help", 0)
    # Skins, both ways round.
    for d in (UP, UP, DOWN, DOWN, DOWN, UP):
        s.msg(d)
        s.tick(1)
    # One player hears the second pad's presses too.
    s.msg(RIGHT, port=1)
    s.tick(1, ports=(1,))
    s.msg(LEFT, port=1)
    s.tick(36)
    # Across every car to the end and back, rendering each.
    n = len(s.of(0, 0)) + len(s.of(0, 1)) + len(s.of(0, 4)) + 2
    walk(s, 0, n, RIGHT)
    s.tick(60)
    walk(s, 0, 4, LEFT)
    s.tick(10, render=True)
    # On a locked car: no orbit, the box hidden and back.
    s.joy(0, 33, 1)
    s.tick(2, render=True)
    s.joy(0, 33, 0)
    s.joy(0, 35, 1)
    s.tick(2, render=True)
    s.joy(0, 33, 1)
    for m in (LEFT, SELECT, UP, BACK, TICK):
        s.msg(m, CHOOSE)
    s.joy(0, 33, 1)
    s.tick(30, step=200, render=True)
    s.msg(UP)
    s.msg(SELECT, CHOOSE)
    # Back to the cop, and on.
    walk(s, 0, n, LEFT, render=False, every=5)
    s.tick(50)
    s.msg(SELECT, 0)
    s.msg(SELECT, CHOOSE)
    s.msg(DISMISS, param=0)
    s.msg(SELECT, CHOOSE)
    s.msg(SELECT, CHOOSE)
    s.msg(DISMISS, param=6)
    s.msg(DISMISS, param=3)
    s.msg(LEFT)
    s.msg(DISMISS, param=0)
    s.msg(DISMISS, param=2)
    s.msg(DISMISS, param=8)
    s.msg(DISMISS, param=4)
    s.tick(2)
    s.msg(UNACTIVATE, SCREEN_1P, 0)
    # The preload, and in again over it.
    s.add("preload", "preload")
    s.msg(ACTIVATE, SCREEN_1P, 1)
    s.tick(5)
    s.msg(DISMISS, param=7)
    s.msg(SELECT, CHOOSE)
    s.msg(DISMISS, param=1)
    s.msg(DISMISS, param=5)
    s.msg(UNACTIVATE, SCREEN_1P, 1)
    s.add("close", "close")


def s_single(s, gt, lang, units):
    """A single race or the championship, one player: the tree events."""
    s.g("gametype", gt)
    s.g("lang", lang)
    s.g("units", units)
    s.g("allcars", 1 if gt == 8 else 0)
    s.statuses(0, kind_c if gt == 8 else kind_b)
    locked = s.of(0, 1) + s.of(0, 4)
    for c in locked[:2]:
        s.add("egg|%d|1" % c.type)
    for i, c in enumerate(locked[2:6]):
        s.add("ev|%d|%d|%d" % (c.type, (0, 1, 2, 0)[i], (5, -3, 7, 200)[i]))
    # With every car listed, the ride is a locked one, which loads.
    car = s.of(0, 2, usage=0)[0] if gt == 8 else s.of(0, 0, usage=0)[1]
    s.add("ride|0|%d|%d|%d" % (gt, car.type, 99), "pts|0|-5")
    s.msg(ACTIVATE, SCREEN_1P, 1 if gt == 8 else 0)
    s.tick(50, render=True)
    n = len(s.cars) + 2
    walk(s, 0, n, RIGHT, every=6)
    s.g("units", 2)
    walk(s, 0, n, LEFT, every=6)
    s.g("units", units)
    s.g("sound", 0)
    s.joy(0, 33, 1)
    s.tick(40)
    s.msg(BACK)
    s.g("sound", 1)
    s.tick(40)
    s.joy(0, 33, 1)
    s.tick(4)
    s.msg(BACK)
    s.tick(40)
    s.msg(DISMISS, param=0)
    s.msg(SELECT, CHOOSE)
    s.msg(DISMISS, param=1)
    s.msg(DISMISS, param=5)
    s.msg(UNACTIVATE, SCREEN_1P, 0)
    for c in locked[:6]:
        s.add("egg|%d|0" % c.type, "ev|%d|-1|0" % c.type)
    s.g("allcars", 0)


def s_two(s):
    """Two players, one selector on each half."""
    s.g("gametype", 3)
    s.g("players", 2)
    s.g("lang", 0)
    s.statuses(0, kind_a)
    s.statuses(1, kind_b)
    c0 = s.of(0, 0, skins=2)[2]
    c1 = s.of(1, 0, skins=2)[0]
    hp = [c for c in s.of(1, 0) if c.hp][:1]
    s.add("ride|0|3|%d|%d" % (c0.type, c0.skins[0]),
          "ride|1|3|%d|%d" % (c1.type, c1.skins[1]), "pts|1|1500000")
    s.msg(ACTIVATE, SCREEN_2P, -1)
    s.msg(ACTIVATE, SCREEN_2P, 0)
    s.msg(ACTIVATE, SCREEN_2P_LO, 1)
    s.tick(50, ports=(0, 1), render=True)
    s.add("blend|1|%s" % F(0.75))
    s.tick(1, ports=(0, 1))
    s.joy(0, 33, 1)
    s.joy(1, 33, 1)
    s.joy(1, 35, 1)
    s.joy(0, 42, 0)
    s.tick(2, ports=(0, 1))
    walk(s, 1, 6, RIGHT, ports=(0, 1))
    walk(s, 0, 3, LEFT, ports=(0, 1))
    if hp:
        s.add("ride|1|3|%d|%d" % (hp[0].type, hp[0].skins[0]))
    for d in (UP, DOWN, DOWN):
        s.msg(d, port=1)
    s.tick(40, ports=(0, 1), render=True)
    walk(s, 1, 12, LEFT, ports=(0, 1))
    s.tick(40, ports=(0, 1))
    s.msg(SELECT, CHOOSE, 0)
    s.msg(DISMISS, port=0, param=2)
    s.msg(DISMISS, port=0, param=4)
    s.msg(SELECT, CHOOSE, 1)
    s.msg(DISMISS, port=1, param=3)
    s.msg(DISMISS, port=1, param=0)
    s.msg(DISMISS, port=1, param=1)
    s.msg(DISMISS, port=1, param=5)
    s.msg(DISMISS, port=0, param=0)
    s.msg(DISMISS, port=0, param=7)
    s.msg(DISMISS, port=1, param=7)
    s.msg(BACK, port=0)
    s.msg(BACK, port=1)
    s.msg(UNACTIVATE, SCREEN_2P_LO, 1)
    s.tick(2, ports=(0, 1))
    s.msg(UNACTIVATE, SCREEN_2P, -1)
    s.msg(UNACTIVATE, SCREEN_2P, 0)
    s.add("preload")
    s.msg(ACTIVATE, SCREEN_2P_LO, 1)
    s.tick(3, ports=(0, 1))
    s.msg(UNACTIVATE, SCREEN_2P_LO, 1)
    s.add("preload", "close")
    s.g("players", 1)


def s_extra(s):
    """The corners the runs above leave: a race with one player, the
    loader's timing, the skins one way, the popups' pad and two cops."""
    s.g("gametype", 3)
    s.g("players", 1)
    s.g("lang", 0)
    s.g("allcars", 0)
    s.statuses(0, kind_a)
    avail = s.of(0, 0)
    one = [c for c in avail if c.nskins == 1][0]
    many = [c for c in avail if c.nskins >= 3][0]
    hidden = [c for c in s.cars if s.cars_status[(0, c.type)] == 3][0]
    allisl = lambda v: s.add(*["isl|%d|%d" % (c.type, v)  # noqa: E731
                               for c in s.cars])
    # No help; the ride a hidden car, so the list's first is the one.
    s.add("ride|0|3|%d|0" % hidden.type)
    s.msg(ACTIVATE, SCREEN_1P, 0)
    s.tick(50)
    # The platform with no frame buffer, one just too small, room for one
    # and room for two.
    for n in (0, 64, 65, 130):
        s.add("frame|%d" % n)
        for _ in range(3):
            s.msg(RENDER, param=0, noise=0)
    s.add("frame|%d" % FRAME)
    # No swatch texture, and each part of one missing: no light.
    for mode in (0, 2, 3, 4, 1):
        s.add("tex|%d" % mode)
        s.tick(1)
    # Into the orbit view and out with the same button.
    s.joy(0, 33, 1)
    s.tick(4)
    s.joy(0, 33, 1)
    s.tick(40)
    # With the gearbox popup up the pad does nothing.
    s.msg(SELECT, CHOOSE)
    s.joy(0, 33, 1)
    s.tick(2)
    s.msg(DISMISS, param=0)
    s.tick(40)
    # The row at rest at once: the swap still waits for the fade.
    s.g("relapsed", F(1.0))
    s.msg(RIGHT)
    s.tick(3)
    s.g("relapsed", F(1.0 / 60))
    s.tick(40)
    # A car still loading when the next is chosen: loaded, not shown.
    allisl(0)
    s.msg(RIGHT)
    s.tick(40)
    s.msg(RIGHT)
    allisl(1)
    s.tick(60)
    # The last car, locked: the box stays for a release, hides for a
    # press with no orbit, and the back button brings it back.
    # Long enough for it to load and fade in: the button reaches the
    # orbit's test only at fade 0.
    walk(s, 0, len(s.cars) + 2, RIGHT, render=False, every=6)
    s.tick(60)
    s.tick(50, render=True)
    s.joy(0, 33, 0)
    s.tick(2, render=True)
    s.joy(0, 33, 1)
    s.tick(2, render=True)
    s.msg(BACK)
    s.tick(2, render=True)
    # Back to the first, and a manual gearbox chosen.
    walk(s, 0, len(s.cars) + 2, LEFT, render=False, every=6)
    s.tick(50)
    s.msg(SELECT, CHOOSE)
    s.msg(DISMISS, param=3)
    s.msg(DISMISS, param=5)
    s.msg(UNACTIVATE, SCREEN_1P, 0)
    # One skin: up does nothing. Three or more: up is the one before.
    for c in (one, many):
        s.add("ride|0|3|%d|%d" % (c.type, c.skins[0]))
        s.msg(ACTIVATE, SCREEN_1P, 0)
        s.tick(50)
        s.msg(UP)
        s.tick(2)
        s.msg(UP)
        s.tick(2)
        s.msg(UNACTIVATE, SCREEN_1P, 0)
    # Two locked cars, one of them an easter egg's and so lit.
    locked = s.of(0, 2)
    s.add("egg|%d|1" % locked[0].type)
    for c in locked[:2]:
        s.add("ride|0|3|%d|%d" % (c.type, c.skins[0]))
        s.msg(ACTIVATE, SCREEN_1P, 0)
        s.tick(3)
        s.msg(UNACTIVATE, SCREEN_1P, 0)
    s.add("egg|%d|0" % locked[0].type)
    # Out while the car still loads, its models with no solid.
    allisl(0)
    s.add("solid|0")
    s.msg(ACTIVATE, SCREEN_1P, 0)
    s.tick(2)
    s.msg(UNACTIVATE, SCREEN_1P, 0)
    s.add("solid|1")
    allisl(1)
    # Two players as cops: only the first's set is the cops'.
    s.g("gametype", 7)
    s.g("players", 2)
    s.statuses(1, kind_b)
    s.msg(ACTIVATE, SCREEN_2P, 0)
    s.msg(ACTIVATE, SCREEN_2P_LO, 1)
    s.tick(3, ports=(0, 1))
    s.msg(UNACTIVATE, SCREEN_2P_LO, 1)
    s.msg(UNACTIVATE, SCREEN_2P, 0)
    s.add("close")
    s.g("players", 1)


def script():
    s = Script()
    common(s)
    s_cop(s)
    s_single(s, 8, 1, 1)
    s_single(s, 9, 2, 0)
    s_two(s)
    s_extra(s)
    return s.ops


# =================================================================== model

class Model(fc.Model):
    def __init__(self):
        fc.Model.__init__(self)
        e = self.e
        self.lines = {}
        e.write(FRED, bytes(FRED_SIZE))
        for g in (G_RTIMER, G_RTIME, G_RFRAMES, G_RELAPSED, G_SOUND,
                  G_ALLCARS, G_SCREEN, LANGUAGE, G_FPOS, G_FEND, G_FFAIL,
                  G_FAMOUNT):
            e.put32(g, 0)
        self.frame = 0
        self.solid = 1
        self.texmode = 1
        self.tex = e.alloc(256, align=16)
        e.put32(G_PRE, M32)
        e.put32(G_PRE + 4, M32)
        e.write(LOADER, bytes(16))
        self.menu = e.alloc(1024, align=16)
        e.write(self.menu, bytes(1024))
        e.put32(G_MENU, self.menu)
        self.speech = e.alloc(64, align=16)
        self.data = e.alloc(16, align=16)
        self.xlbuf = {}
        self.xl = {}
        self.help = 0
        self.pi = 0
        self.eggs = {}
        self.ev = {}
        self.isl = {}
        self.joys = {}
        stubs = {
            S_XL: self.s_xl, S_XS: self.s_xs, S_SOUND: self.s_sound,
            S_STOPSOUND: self.s_stopsound, S_HELP: self.s_help,
            S_HELPACTIVE: self.s_helpactive, S_SUMMON: self.s_summon,
            S_DISMISS: self.s_dismiss, S_CHANGE: self.s_change,
            S_STARTRACE: self.s_startrace, S_LOAD: self.s_load,
            S_ISLOADED: self.s_isloaded, S_UNLOAD: self.s_unload,
            S_BEGIN: self.s_begin, S_EGG: self.s_egg,
            S_ISEVENT: self.s_isevent, S_FINDEVENT: self.s_findevent,
            S_RTEXT: self.s_rtext, S_REINIT: self.s_reinit, S_SPEECH: lambda em: self.speech,
            S_FADE: self.s_fade, S_SPEAK: self.s_speak,
            S_CONVERT: lambda em: em.reg[4] & M32,
            S_STOPMOVIE: self.s_stopmovie, S_PERPORT: self.s_perport,
            S_ASSIGN: self.s_assign, S_ADDJOY: self.s_addjoy,
            S_REMOVEJOY: self.s_removejoy, S_OMALLOC: self.s_omalloc,
            S_MOVER: self.s_mover, S_FERC_DTOR: self.s_ferc_dtor,
            S_MODEL_INIT: self.s_model_init,
            S_MODEL_UNINIT: self.s_model_uninit,
            S_MODEL_DTOR: self.s_model_dtor,
            S_MODEL_RENDER: self.s_model_render,
            S_CAM_MODE: self.s_cam_mode, S_CAM_DTOR: self.s_cam_dtor,
            S_CAM_RADIUS: lambda em: self.e.put32(
                (em.reg[4] & M32) + 64, em.fpr[12] & M32),
            S_CAM_OFFSET: lambda em: self.copy12(em, 80),
            S_CAM_ORBIT: lambda em: self.copy12(em, 96),
            S_CAM_FOV: lambda em: self.put16((em.reg[4] & M32) + 144,
                                             em.reg[5]),
            S_CAM_ORIENT: self.s_cam_orient, S_LIGHTING: self.s_lighting,
            S_TEXINFO: self.s_texinfo, S_FERC: self.s_ferc,
        }
        for a, fn in stubs.items():
            e.stub(a, fn)
        for a in SILENT:
            e.stub(a, lambda em: 0)
        e.call(F_SINIT)
        self.building = 0
        e.hook(F_SELECTOR, self.h_selector)

    # ---- stubs

    def string(self, a):
        mem = self.e.mem
        n = 0
        while mem[a + n]:
            n += 1
        return bytes(mem[a:a + n]).decode("latin-1")

    def ride(self, a):
        e = self.e
        b = bytes(e.mem[a + 4:a + 8])
        return "%d %d %d %d %d" % ((s32(e.u32(a)),)
                                   + struct.unpack("<4b", b))

    def s_xl(self, em):
        i = s32(em.reg[4] & M32)
        t = self.xl.get(i, "M%x" % (i & M32))
        self.emit("  xl %s -> %s" % (cx(i & M32), t))
        if i not in self.xlbuf:
            self.xlbuf[i] = self.e.alloc(128, align=16)
        self.e.write(self.xlbuf[i], t.encode("latin-1") + b"\0")
        return self.xlbuf[i]

    def s_xs(self, em):
        a = em.reg[4] & M32
        self.emit("  xs %s" % self.string(a))
        return a

    def s_sound(self, em):
        self.emit("  sound %d" % s32(em.reg[4] & M32))

    def s_stopsound(self, em):
        self.emit("  stopsound %d" % s32(em.reg[4] & M32))

    def s_help(self, em):
        a = em.reg[4] & M32
        if a == 0:
            self.emit("  help -")
            return
        v = []
        while self.e.u32(a):
            v.append(str(s32(self.e.u32(a))))
            a += 4
        self.emit("  help %s" % ",".join(v))

    def s_helpactive(self, em):
        self.emit("  helpmenu? -> %d" % self.help)
        return self.help & M32

    def s_summon(self, em):
        c = em.reg[5] & M32
        g = lambda o: s32(self.e.u32(c + o))      # noqa: E731
        msg = self.e.u32(c + 16)
        self.emit("  popup n %d flags %d screen %08x msg %s b %s %s %s "
                  "p %d %d %d cancel %d dismiss %d start %d port %d "
                  "timeout %d title %d -> %d" % (
                      g(0), g(4), g(12) & M32,
                      self.string(msg) if msg else "(null)",
                      cx(g(20) & M32), cx(g(24) & M32), cx(g(28) & M32),
                      g(32), g(36), g(40), g(44), g(48), g(52), g(56),
                      g(60), g(68), self.pi))
        self.pi += 1
        return (self.pi - 1) & M32

    def s_dismiss(self, em):
        self.emit("  dismiss %d" % s32(em.reg[5] & M32))

    def s_change(self, em):
        self.emit("  change %s %d" % (self.string(em.reg[4] & M32),
                                      s32(em.reg[5] & M32)))

    def s_startrace(self, em):
        self.emit("  startrace")

    def s_load(self, em):
        self.emit("  load %s" % self.ride(em.reg[5] & M32))

    def s_isloaded(self, em):
        a = em.reg[5] & M32
        v = self.isl.get(s32(self.e.u32(a)), 1)
        self.emit("  isloaded %s %d -> %d" % (self.ride(a),
                                              s32(em.reg[6] & M32), v))
        return v & M32

    def s_unload(self, em):
        self.emit("  unload %s" % self.ride(em.reg[5] & M32))

    def s_begin(self, em):
        self.emit("  begin %d" % s32(em.reg[5] & M32))

    def s_egg(self, em):
        t = s32(em.reg[5] & M32)
        v = self.eggs.get(t, 0)
        self.emit("  egg? %d %d -> %d" % (t, s32(em.reg[6] & M32), v))
        return v & M32

    def s_isevent(self, em):
        t = s32(em.reg[4] & M32)
        v = 1 if self.ev.get(t, (-1, 0))[0] != -1 else 0
        self.emit("  event? %d -> %d" % (t, v))
        return v

    def s_findevent(self, em):
        e = self.e
        tree, num = self.ev[s32(em.reg[4] & M32)]
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

    def h_selector(self, em):
        self.building = em.reg[4] & M32

    def selectors(self):
        p = self.e.u32(G_SCREEN)
        if not p:
            return []
        return [(i, self.e.u32(p + 4 + 4 * i)) for i in range(2)
                if self.e.u32(p + 4 + 4 * i)]

    # ---- the 3D seams

    def put16(self, a, v):
        self.e.write(a, struct.pack("<H", v & 0xffff))

    def copy12(self, em, off):
        e = self.e
        a, v = em.reg[4] & M32, em.reg[5] & M32
        e.write(a + off, bytes(e.mem[v:v + 12]))

    @staticmethod
    def fe_name(f, e):
        return "refl" if e.u32(f + 636) else "car"

    def s_ferc(self, em):
        a = em.reg[4] & M32
        self.e.write(a, bytes(FERC_SIZE))
        self.e.put32(a + 20, em.reg[6])
        self.emit("  fecar init view %d ride %d" % (
            s32(em.reg[6] & M32), 1 if em.reg[5] & M32 else 0))
        return a

    def s_reinit(self, em):
        f = em.reg[4] & M32
        self.emit("  reinit %s view %d ride %s" % (
            self.fe_name(f, self.e), s32(self.e.u32(f + 20)),
            self.ride(em.reg[5] & M32)))

    def s_ferc_dtor(self, em):
        f = em.reg[4] & M32
        self.emit("  fecar delete %s view %d model %d" % (
            self.fe_name(f, self.e), s32(self.e.u32(f + 20)),
            1 if self.e.u32(f + 624) else 0))

    def s_model_init(self, em):
        a = em.reg[4] & M32
        self.e.put32(a + 8, em.reg[5])
        self.e.put32(a + 12, self.solid)
        self.emit("  model init %08x" % (em.reg[5] & M32))

    def s_model_uninit(self, em):
        a = em.reg[4] & M32
        self.emit("  model uninit %08x" % self.e.u32(a + 8))
        self.e.put32(a + 12, 0)

    def s_model_dtor(self, em):
        self.emit("  model delete %08x" % self.e.u32((em.reg[4] & M32) + 8))

    def s_model_render(self, em):
        e = self.e
        m = em.reg[5] & M32
        self.emit("  model render %08x at %d light %d flags %d matrix %s" % (
            e.u32((em.reg[4] & M32) + 8), s32((m - self.frame) & M32),
            1 if em.reg[6] & M32 else 0, em.reg[7] & M32,
            bytes(e.mem[m:m + 64]).hex()))

    def s_cam_mode(self, em):
        self.emit("  cam mode %d" % s32(em.reg[5] & M32))

    def s_cam_dtor(self, em):
        self.emit("  cam delete")

    def s_cam_orient(self, em):
        a = em.reg[4] & M32
        self.put16(a + 56, em.reg[5])
        self.put16(a + 60, em.reg[6])

    def s_lighting(self, em):
        self.emit("  light %d %d %08x" % (
            s32(em.reg[4] & M32), s32(em.reg[5] & M32), em.fpr[12] & M32))

    def s_texinfo(self, em):
        """GetTextureInfo, as the harness's: a swatch whose fourth texel is
        the hash's bits 4..6, over eight colours from its high bytes."""
        e = self.e
        h = em.reg[4] & M32
        self.emit("  tex %08x %d" % (h, s32(em.reg[5] & M32)))
        if self.texmode == 0:
            return 0
        ti, image, pal = self.tex, self.tex + 160, self.tex + 176
        e.write(ti, bytes(160))
        e.write(image, bytes([0, 0, 0, (h >> 4) & 7]))
        e.write(pal, b"".join(bytes([((h >> 8) + 37 * k) & 255,
                                     ((h >> 16) + 59 * k) & 255,
                                     ((h >> 24) + 83 * k) & 255, 0x80])
                              for k in range(8)))
        e.put32(ti + 144, 0 if self.texmode == 2 else image)
        e.put32(ti + 60, 0 if self.texmode == 3 else 32)
        e.put32(ti + 148, 0 if self.texmode == 4 else pal)
        return ti

    def s_fade(self, em):
        self.emit("  fade %08x" % (em.fpr[12] & M32))

    def s_speak(self, em):
        r = [s32(em.reg[i] & M32) for i in range(4, 8)]
        if r[0] == 211:
            self.emit("  speak 211 %d %d" % (r[1], r[2]))
        else:
            self.emit("  speak %d %d %d %d" % tuple(r))

    def s_stopmovie(self, em):
        self.emit("  stopmovie")

    def s_perport(self, em):
        self.emit("  perport %d" % s32(em.reg[4] & M32))

    def s_assign(self, em):
        p = ((em.reg[4] & M32) - F_FPI) // FPI_SIZE
        self.emit("  assign %d %d %d %d %d" % (
            p, s32(em.reg[5] & M32), s32(em.reg[6] & M32),
            s32(em.reg[7] & M32), s32(em.reg[8] & M32)))

    def s_addjoy(self, em):
        key = (s32(em.reg[4] & M32), s32(em.reg[5] & M32))
        self.joys[key] = (em.reg[6] & M32, em.reg[7] & M32)

    def s_removejoy(self, em):
        self.joys.pop((s32(em.reg[4] & M32), s32(em.reg[5] & M32)), None)

    def s_omalloc(self, em):
        a = self.e.alloc(256, align=16)
        self.e.write(a, bytes(256))
        return a

    def s_mover(self, em):
        a = em.reg[4] & M32
        self.e.write(a, bytes(MOVER_SIZE))
        self.e.put32(a + 40, MOVER_VT)
        self.emit("  cam init view %d" % s32(em.reg[5] & M32))
        return a

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

    def car_type(self, a):
        return -1 if a == 0 else s32(self.e.u32(a + 12))

    def status_name(self, a):
        rel = a - F_FPI
        p, off = divmod(rel, FPI_SIZE)
        if 0 <= p < 2 and off % 24 == 0 and off // 24 < 64:
            return "%d.%d" % (p, off // 24)
        return "stray"

    def dump_selector(self, i, c):
        e = self.e
        g = e.u32
        si = lambda o: s32(g(c + o))      # noqa: E731
        self.note("sel%d" % i, (
            "port %d 2p %d player %d screen %08x fade %d/%d all %d "
            "loaded %d pending %d modes %08x %08x %08x %08x orbit %d %d "
            "state %d popup %d trans %d hand %d turn %d %d %d sw %d") % (
            si(20), si(24), si(28), g(c + 32), si(72), si(68), si(76),
            self.car_type(g(c + 80)), self.car_type(g(c + 84)),
            g(c + 88), g(c + 92), g(c + 96), g(c + 100), si(104), si(108),
            si(112), si(116), si(120), si(124), e.u16(c + 224),
            e.u16(c + 226), e.u16(c + 228), si(232)))
        items = []
        n = g(c + 12)
        while n != c + 12 and n:
            items.append(" %d:%d:%d:%d:%08x:%s" % (
                s32(g(n + 12)), s32(g(n + 16)), s32(g(n + 20)),
                s32(g(n + 28)), g(n + 24), self.status_name(g(n + 8))))
            n = g(n)
        self.note("set%d" % i, "cur %d total %d unl %d list%s" % (
            self.car_type(g(c)), si(4), si(8), "".join(items)))
        u = c + 652
        sl = u + 16
        self.note("unl%d" % i, (
            "car %d screen %08x x %08x alpha %d start %d state %d hide %d "
            "slide %08x %08x %08x %d %d %s \"%s\"") % (
            self.car_type(g(u)), g(u + 4), g(u + 8), s32(g(u + 12)),
            s32(g(u + 348)), s32(g(u + 352)), s32(g(u + 356)), g(sl + 8),
            g(sl + 12), g(sl + 16), s32(g(sl + 20)), s32(g(sl + 24)),
            bytes(e.mem[sl + 28:sl + 76]).hex(), self.string(u + 92)))
        self.note("thumbs%d" % i, bytes(e.mem[c + 332:c + 380]).hex())
        self.note("swatch%d" % i, " ".join(
            "%08x:%08x" % (g(c + 236 + 4 * k), g(c + 276 + 4 * k))
            for k in range(10)))
        self.dump_fecar("fe%d" % i, c, g(c + 36))
        self.dump_fecar("fr%d" % i, c, g(c + 40))
        m = g(c + 188)
        self.note("cam%d" % i, (
            "blend %08x angle %d tilt %d radius %08x off %08x %08x %08x "
            "orbit %08x %08x %08x fov %d desired %08x %08x") % (
            g(m + 48), e.u16(m + 56), e.u16(m + 60), g(m + 64), g(m + 80),
            g(m + 84), g(m + 88), g(m + 96), g(m + 100), g(m + 104),
            e.u16(m + 144), g(m + 152), g(m + 160)))

    def dump_fecar(self, key, c, f):
        e = self.e
        g = e.u32
        pm = g(f + 624)
        self.note(key, (
            "en %d refl %d model %s lights %d %d pos %08x %08x %08x %s") % (
            s32(g(f + 628)), s32(g(f + 636)),
            "0" if not pm else "cover" if pm == c + 44 else "stray",
            s32(g(f + 640)), s32(g(f + 644)), g(f + 32), g(f + 36),
            g(f + 40), bytes(e.mem[f + 48:f + 112]).hex()))
        self.note(key + "w", bytes(e.mem[f + 112:f + 624]).hex())

    def dump(self):
        e = self.e
        g = e.u32
        p = g(G_SCREEN)
        if p:
            self.note("scr", "present 1 count %d sel %d %d" % (
                s32(g(p)), 1 if g(p + 4) else 0, 1 if g(p + 8) else 0))
            for i, c in self.selectors():
                self.dump_selector(i, c)
        else:
            self.note("scr", "present 0")
        self.note("pre", "%d %d" % (s32(g(G_PRE)), s32(g(G_PRE + 4))))
        self.note("carloader", "%d %d" % (s32(g(LOADER + 4)),
                                          s32(g(LOADER + 8))))
        self.note("frame", "used %d failed %d amount %d" % (
            s32((g(G_FPOS) - self.frame) & M32), s32(g(G_FFAIL)),
            g(G_FAMOUNT)))
        for i in range(2):
            st = F_FPI + FPI_SIZE * i + FPI_SETTINGS
            self.note("pl%d" % i, "trans %d style %d" % (
                struct.unpack("<b", bytes(e.mem[st + 3:st + 4]))[0],
                struct.unpack("<b", bytes(e.mem[st + 2:st + 3]))[0]))
        self.dump_objects()

    # ---- ops

    def load_cars(self, path):
        e = self.e
        d = Path(path).read_bytes()
        out, off = {}, 0
        while off + 8 <= len(d):
            cid, size = struct.unpack_from("<II", d, off)
            if cid in (CAR_CHUNK, SKIN_CHUNK) and cid not in out:
                out[cid] = d[off:off + 8 + size]
            off += 8 + size
        self.carmem = e.alloc(64 * CAR_REC, align=16)
        e.write(self.carmem, out[CAR_CHUNK][16:16 + 64 * CAR_REC])
        e.put32(G_CARS, self.carmem)
        sk = out[SKIN_CHUNK]
        self.skinmem = e.alloc(len(sk), align=16)
        e.write(self.skinmem, sk)
        e.put32(G_SKINS, self.skinmem + 8)
        e.put32(G_NSKINS, (len(sk) - 8) >> 6)
        self.emit("  cars 1 skins %d" % ((len(sk) - 8) >> 6))

    def put(self, a, n, v):
        self.e.write(a, (v & ((1 << (8 * n)) - 1)).to_bytes(n, "little"))

    def op(self, a):
        e = self.e
        o = a[0]
        v = lambda i: int(a[i], 0)      # noqa: E731
        if o == "load":
            self.load(a[1])
            return
        if o == "cars":
            self.load_cars(a[1])
            return
        if o == "spec":
            t = v(1)
            blk = e.alloc(28, align=16)
            e.write(blk, struct.pack("<7i", t, *[v(i) for i in range(2, 8)]))
            e.put32(self.carmem + CAR_REC * t + 1368, blk)
            return
        if o == "cr":
            self.put(self.carmem + CAR_REC * v(1) + v(2), v(3), v(4))
            return
        if o == "sk":
            self.put(self.skinmem + 8 + 64 * v(1) + v(2), v(3), v(4))
            return
        if o == "g":
            k = a[1]
            if k == "help":
                self.help = v(2)
            elif k == "pi":
                self.pi = v(2)
            elif k == "units":
                e.mem[F_UNITS] = v(2) & 0xff
            else:
                e.put32({"gametype": F_GT, "players": F_NP,
                         "lang": LANGUAGE, "sound": G_SOUND,
                         "allcars": G_ALLCARS, "rtimer": G_RTIMER,
                         "rframes": G_RFRAMES,
                         "relapsed": G_RELAPSED}[k], v(2) & M32)
        elif o == "fs":
            st = F_FPI + FPI_SIZE * v(1) + 24 * v(2)
            skins = [int(x, 0) & 0xff for x in a[5].split(",") if x][:10]
            e.write(st, struct.pack("<i", v(3)))
            e.write(st + 4, bytes(skins) + bytes(10 - len(skins)))
            e.write(st + 16, struct.pack("<ii", v(4), v(6)))
        elif o == "ride":
            r = F_FPI + FPI_SIZE * v(1) + FPI_RIDES + 8 * v(2)
            e.put32(r, v(3) & M32)
            e.mem[r + 5] = v(4) & 0xff
        elif o == "pts":
            e.put32(F_FPI + FPI_SIZE * v(1) + FPI_POINTS, v(2) & M32)
        elif o == "xl":
            self.xl[s32(v(1) & M32)] = a[2]
        elif o == "egg":
            self.eggs[v(1)] = v(2)
        elif o == "ev":
            self.ev[v(1)] = (v(2), v(3))
        elif o == "isl":
            self.isl[v(1)] = v(2)
        elif o == "tex":
            self.texmode = v(1)
        elif o == "solid":
            self.solid = v(1)
        elif o == "blend":
            c = e.u32(e.u32(G_SCREEN) + 4 + 4 * v(1))
            e.put32(e.u32(c + 188) + 48, v(2) & M32)
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
        elif o == "joy":
            h = self.joys.get((v(1), v(2)))
            if h:
                e.call(h[0], v(1), v(2), v(3), h[1], limit=10000000)
        elif o == "preload":
            e.call(F_PRELOAD, limit=200000000)
        elif o == "close":
            e.call(F_CLOSE, limit=10000000)
        else:
            raise ValueError(o)
        # The set-up ops change nothing until the next action shows it.
        if o in ("msg", "joy", "preload", "close"):
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

def build_harness(tmp, name="carsel_test"):
    return hostbuild.build(tmp, SOURCES, name=name)


run_harness = fc.run_harness
diff = pcc.diff
write_script = fc.write_script


# ============================================================= mutations

H = BCARSEL


def M(name, before, after, rel=H):
    return (name, rel, before, after)


MUTATIONS = [
    # CarListSort's keys and its tie.
    M("sort-available", "uint32_t ka = a->available ? 0 : 0x40000000u;",
      "uint32_t ka = a->available ? 0x40000000u : 0;"),
    M("sort-cop", "if (ca->UsageType == CAR_USAGE_TYPE_COP) ka += 0x01000000u;",
      "if (ca->UsageType == CAR_USAGE_TYPE_COP) ka += 0x00000100u;"),
    M("sort-hp", "ka += (uint32_t)((int32_t)ca->HighPerformance << 16);",
      "ka += (uint32_t)((int32_t)ca->HighPerformance << 4);"),
    M("sort-class", "ka += (uint32_t)((5 - (int32_t)ca->CarClass) << 8);",
      "ka += (uint32_t)((int32_t)ca->CarClass << 8);"),
    M("sort-name-tie",
      "ka += bStrCmp(nameA, trId(s_sortHooks, specFullName(cb))) > 0;",
      "ka += bStrCmp(nameA, trId(s_sortHooks, specFullName(cb))) >= 0;"),
    M("sort-name-way",
      "ka += bStrCmp(nameA, trId(s_sortHooks, specFullName(cb))) > 0;",
      "ka += bStrCmp(nameA, trId(s_sortHooks, specFullName(cb))) < 0;"),
    M("sort-strict", "return !(kb < ka);", "return ka < kb;"),

    # The set: its init and its copy.
    M("set-hidden-shown",
      "if (st->nStatus == CAR_STATUS_HIDDEN" + NL
      + "            && !AllCarsAvailableInCarSelectScreen)",
      "if (st->nStatus == CAR_STATUS_HIDDEN)"),
    M("set-egg-cops", "h->eggActive(h->user, i, copsOnly))) {",
      "h->eggActive(h->user, i, 0))) {"),
    M("set-no-egg",
      "|| (h->eggActive && h->eggActive(h->user, i, copsOnly))) {",
      "|| (h->eggActive && h->eggActive(h->user, i, copsOnly) && 0)) {"),
    M("set-unlocked", "            unlocked++;" + NL, ""),
    M("set-ride-skin", "carSetSkin(c, (int8_t)ride->SkinNumber);",
      "carSetSkin(c, cti(i)->DefaultSkinNumber);"),
    M("set-ride-game", "ride = fpi_get_selected_ride_info(player, Fred.GameType);",
      "ride = fpi_get_selected_ride_info(player, 3);"),
    M("set-current-last",
      "    if (!s->current && s->list.next != &s->list)" + NL
      + "        s->current = (VisibleCar*)s->list.next;",
      "    if (!s->current && s->list.next != &s->list)" + NL
      + "        s->current = (VisibleCar*)s->list.prev;"),
    M("set-renumber", "((VisibleCar*)node)->carIndex = i++;",
      "((VisibleCar*)node)->carIndex = ++i;"),
    M("set-no-sort", "    blist_sort(&s->list, carListSort);" + NL, ""),
    M("copy-skin", "to->skinIndex = from->skinIndex;", "to->skinIndex = 0;"),
    M("copy-available", "to->available = from->available;",
      "to->available = 1;"),
    M("copy-current", "if (from == s->current) d->current = to;",
      "if (0) d->current = to;"),
    M("copy-index", "to->carIndex  = from->carIndex;", "to->carIndex  = 0;"),
    M("skin-next-wrap", "if (++c->skinIndex >= c->status->nSkins)",
      "if (++c->skinIndex > c->status->nSkins)"),
    M("skin-prev-wrap", "if (--c->skinIndex < 0) c->skinIndex = c->status->nSkins - 1;",
      "if (--c->skinIndex < 0) c->skinIndex = 0;"),
    M("car-thumb-name", "c->thumbHash = hashf(\"THUMBNAIL_%s\", cti(type)->CarTypeName);",
      "c->thumbHash = hashf(\"THUMBNAIL%s\", cti(type)->CarTypeName);"),

    # The preload and the close.
    M("preload-same", "if (g_m->preloaded[i] == type) continue;",
      "if (0) continue;"),
    M("preload-unload", "if (g_m->preloaded[i] != -1) loaderUnload(h, g_m->preloaded[i]);",
      "(void)0;"),
    M("preload-cops", "i == 0 && Fred.GameType == GAME_TYPE_BE_A_COP);",
      "i == 1 && Fred.GameType == GAME_TYPE_BE_A_COP);"),
    M("preload-one", "for (i = 0; i < Fred.NumPlayerCars && i < 2; i++) {",
      "for (i = 0; i < Fred.NumPlayerCars && i < 1; i++) {"),
    M("preload-no-begin", "        loaderLoad(h, type);" + NL
      + "        loaderBeginLoading(h);",
      "        loaderLoad(h, type);"),
    M("close-no-unload", "if (g_m) preloadUnload();", "(void)0;"),
    M("close-keep", "        g_m->preloaded[i] = -1;" + NL + "    }",
      "    }"),

    # feAlphaAnimation.
    M("fade-bound", "&& f->count < BCARSEL_MAX_FADE) {", "&& f->count < 48) {"),
    M("fade-bitmap-corner", "ee_trunc_w(f->el[n].alpha[i] * s), i);",
      "ee_trunc_w(f->el[n].alpha[0] * s), i);"),
    M("fade-object-scale",
      "flailerobject_set_alpha(o, ee_trunc_w(f->el[n].alpha[0] * s));",
      "flailerobject_set_alpha(o, ee_trunc_w(f->el[n].alpha[0]));"),
    M("fade-restore", "ee_trunc_w(f->el[n].alpha[i]), i);",
      "ee_trunc_w(f->el[n].alpha[i] * 0.5f), i);"),
    M("fade-restore-object",
      "flailerobject_set_alpha(o, ee_trunc_w(f->el[n].alpha[0]));" + NL
      + "        }" + NL + "    }" + NL + "    f->count = 0;",
      "flailerobject_set_alpha(o, 0);" + NL
      + "        }" + NL + "    }" + NL + "    f->count = 0;"),

    # AnimationGroup.
    M("slide-init-start", "OBJ_UNLOCK_BOX, 640.0f,", "OBJ_UNLOCK_BOX, 650.0f,"),
    M("slide-duration", "              u->x, 0.5f);", "              u->x, 1.0f);"),
    M("slide-show-start",
      "slideSetup(&u->slide, 650.0f, u->x);" + NL + "    u->state = 2;",
      "slideSetup(&u->slide, 640.0f, u->x);" + NL + "    u->state = 2;"),
    M("slide-threshold", "a->spline.arrivalThreshold = 1.0f;",
      "a->spline.arrivalThreshold = 2.0f;"),
    M("slide-restore", "slidePlace(a, a->savedX, a->savedY);",
      "slidePlace(a, a->savedX + 1, a->savedY);"),
    M("slide-jump", "    s->val   = s->valDesired;" + NL
      + "    s->dval  = s->dvalDesired;" + NL + "    splineAim(s, end);",
      "    s->dval  = s->dvalDesired;" + NL + "    splineAim(s, end);"),

    # The unlock box.
    M("unlock-delay", "if (0.4f < t) {", "if (0.3f < t) {"),
    M("unlock-frac", "frac = (t - 0.4f) / 0.5f;", "frac = (t - 0.4f) / 0.25f;"),
    M("unlock-alpha-full", "frac < 1.0f ? ee_trunc_w((float)u->alpha * frac)",
      "frac < 0.5f ? ee_trunc_w((float)u->alpha * frac)"),
    M("unlock-clock", "float t    = (float)(RealTimer - u->start) * 0.00025f;",
      "float t    = (float)(RealTimer - u->start) * 0.0005f;"),
    M("unlock-same-car", "    if (car == u->car) return;" + NL, ""),
    M("unlock-state-free", "        u->state = 0;" + NL + "    } else {",
      "        u->state = 1;" + NL + "    } else {"),
    M("unlock-group-shown",
      "flailer_set_group_visibility(u->screen, OBJ_UNLOCK_GROUP, 0);" + NL
      + "        flailer_set_visibility(u->screen, OBJ_UNLOCK_FADE, 0);" + NL
      + "        u->state = 0;",
      "flailer_set_group_visibility(u->screen, OBJ_UNLOCK_GROUP, 1);" + NL
      + "        flailer_set_visibility(u->screen, OBJ_UNLOCK_FADE, 0);" + NL
      + "        u->state = 0;"),
    M("unlock-text-shown",
      "flailer_set_visibility(u->screen, OBJ_UNLOCK_TEXT, 0);" + NL
      + "    snprintf",
      "flailer_set_visibility(u->screen, OBJ_UNLOCK_TEXT, 1);" + NL
      + "    snprintf"),
    M("unlock-flag-init", "unlockSetCar(c, cur(c), c->port == 1);",
      "unlockSetCar(c, cur(c), c->port != 1);"),
    M("unlock-flag-move", "unlockSetCar(c, car, c->port == 1);",
      "unlockSetCar(c, car, c->port ^ 1);"),
    M("unlock-render-state", "|| c->allUnlocked || u->state != 2)" + NL
      + "        return;",
      "|| c->allUnlocked)" + NL + "        return;"),
    M("unlock-render-avail", "if (!u->car || u->car->available ||",
      "if (!u->car ||"),
    M("unlock-joy-pressed", "if (ev == BCARSEL_JOY_CHANGE_MODE && pressed && u->car",
      "if (ev == BCARSEL_JOY_CHANGE_MODE && u->car"),
    M("unlock-joy-avail", "&& !u->car->available && !c->allUnlocked) {",
      "&& !c->allUnlocked) {"),
    M("unlock-hide-sound", "unlockHide(u);" + NL + "            sound(c->hooks, 5);",
      "unlockHide(u);" + NL + "            sound(c->hooks, 6);"),
    M("unlock-show-pressed", "if (pressed) {" + NL + "            unlockShow(u);",
      "if (1) {" + NL + "            unlockShow(u);"),
    M("unlock-cb-noise", "data->noise = 5;", "data->noise = 6;"),
    M("unlock-cb-back",
      "        case BMSG_MENUITEM_PAD_DOWN:" + NL
      + "        case BMSG_SCREEN_BACK_BUTTON:" + NL
      + "            unlockShow(u);",
      "        case BMSG_MENUITEM_PAD_DOWN:" + NL
      + "            unlockShow(u);"),
    M("unlock-cb-state", "    if (u->state != 1) return 0;", "    if (u->state == 2) return 0;"),
    M("covered-status", "&& car->status->nStatus == 4;",
      "&& car->status->nStatus == 1;"),

    # The make's logo and the badge.
    M("logo-hp-cut", "buf[n >= 2 ? n - 2 : 0] = 0;", "buf[n >= 2 ? n - 1 : 0] = 0;"),
    M("logo-1p-names", "    if (c->twoPlayer) {" + NL + "        if (ct->HighPerformance) {",
      "    if (1) {" + NL + "        if (ct->HighPerformance) {"),
    M("logo-cop-names", "{ \"CROWNVIC\",    \"CROWNVICNOCOP\" },",
      "{ \"CROWNVIC\",    \"CROWNVIC\" },"),
    M("logo-prefix", "return hashf(\"CARLOGO_%s\", buf);",
      "return hashf(\"CARLOGO%s\", buf);"),
    M("badge-1p", "    if (!c->twoPlayer) return 0;" + NL, ""),
    M("badge-cop", "return bchunk_hash(\"LOGO_SHERIFF\");",
      "return bchunk_hash(\"LOGO_NFS\");"),
    M("badge-hp", "if (isHP(type)) return bchunk_hash(\"LOGO_NFS\");",
      "if (0) return bchunk_hash(\"LOGO_NFS\");"),
    M("logo-covered", "    if (covered(c, car)) {" + NL
      + "        flailer_set_visibility(c->screen, OBJ_CAR_NAME, 0);",
      "    if (0) {" + NL
      + "        flailer_set_visibility(c->screen, OBJ_CAR_NAME, 0);"),

    # The info bar.
    M("info-kph", "if (units == 1) speed = ct->pCarSpecs->TopSpeedKph;",
      "if (units == 1) speed = ct->pCarSpecs->TopSpeedMph;"),
    M("info-units-label", "trId(h, units != 0 ? LANG_KPH : LANG_MPH));",
      "trId(h, units == 1 ? LANG_KPH : LANG_MPH));"),
    M("info-plus-hp", "int         plus  = ct->HighPerformance || cop;",
      "int         plus  = cop;"),
    M("info-minus", "plus ? \"-\" : \"\", trId(h, LANG_SECONDS));",
      "plus ? \"+\" : \"\", trId(h, LANG_SECONDS));"),
    M("info-class", "\"%d\", ct->CarClass + 1);", "\"%d\", ct->CarClass);"),
    M("info-cop-shown", "if (covered(c, car) || cop) {", "if (covered(c, car)) {"),
    M("info-unlocked-shown", "useTreeEvent() ? 0 : 1);", "1);"),
    M("info-unlocked-count", "(int)c->set.unlocked," + NL, "(int)c->set.used," + NL),
    M("tree-event-range", "return Fred.GameType >= 8 && Fred.GameType < 10;",
      "return Fred.GameType >= 8 && Fred.GameType < 9;"),

    # The help bar.
    M("help-single", "if (gt == 8) {" + NL + "            setHelp(h, kHelpChooseSingle);",
      "if (gt == 8) {" + NL + "            setHelp(h, kHelpChooseChamp);"),
    M("help-champ-line", "800053, 800054, 800400,", "800053, 800054, 800401,"),
    M("help-cop1", "if (npc == 1) setHelp(h, kHelpChooseCop1);",
      "if (npc == 1) setHelp(h, kHelpChooseCop2);"),
    M("help-1p-none", "if (npc == 1) setHelp(h, NULL);",
      "if (npc == 1) setHelp(h, kHelpChoose2P);"),
    M("help-2p", "else if (npc == 2) setHelp(h, kHelpChoose2P);",
      "else if (npc == 2) setHelp(h, NULL);"),
    M("help-orbit-single", "if (gt == 8) setHelp(h, kHelpOrbitSingle);",
      "if (gt == 8) setHelp(h, kHelpOrbit);"),
    M("help-orbit-champ", "else if (gt == 9) setHelp(h, kHelpOrbitChamp);",
      "else if (gt == 9) setHelp(h, kHelpOrbit);"),
    M("help-orbit-line", "{800023, 800024, 800027, 0}", "{800023, 800024, 800025, 0}"),

    # The swatches.
    M("swatch-1p-x", "        x = 587;", "        x = 588;"),
    M("swatch-2p-y", "        y = 77;", "        y = 78;"),
    M("swatch-2plo-y", "        y = 321;", "        y = 320;"),
    M("swatch-step", "y + 18 * i);", "y + 17 * i);"),
    M("swatch-ring", "y + 18 * i - 4);", "y + 18 * i - 5);"),
    M("swatch-ring-x", "OBJ_SWATCH_RING, x - 4,", "OBJ_SWATCH_RING, x - 5,"),
    M("swatch-bottom", "18 * c->nSwatches + y + 2);", "18 * c->nSwatches + y + 3);"),
    M("swatch-top", "OBJ_SWATCH_TOP, x, y - 22);", "OBJ_SWATCH_TOP, x, y - 21);"),
    M("swatch-one", "if (c->nSwatches < 2 || covered(c, cur(c))) {",
      "if (c->nSwatches < 1 || covered(c, cur(c))) {"),
    M("swatch-covered", "if (c->nSwatches < 2 || covered(c, cur(c))) {",
      "if (c->nSwatches < 2) {"),
    M("swatch-colour", "c->swatchColour[i] = si ? si->ColourSwatchHash : 0;",
      "c->swatchColour[i] = si ? si->ColourSwatchHash ^ 1 : 0;"),
    M("swatch-name", "c->swatchHash[i]   = hashf(\"SWATCH_%d\", (int)i);",
      "c->swatchHash[i]   = hashf(\"SWATCH_%d\", (int)i + 1);"),
    M("swatch-close", "    closeSwatches(c);" + NL + "    c->nSwatches = car->status->nSkins;",
      "    c->nSwatches = car->status->nSkins;"),

    # The thumbnail row.
    M("thumbs-base-1p", "#define THUMB_BASE_1P   377.0f", "#define THUMB_BASE_1P   378.0f"),
    M("thumbs-base-2p", "#define THUMB_BASE_2P   395.0f", "#define THUMB_BASE_2P   394.0f"),
    M("thumbs-step", "#define THUMB_STEP      39.0f", "#define THUMB_STEP      40.0f"),
    M("thumbs-lock-target", "    if (!car->available) t -= (float)lockW;" + NL, ""),
    M("thumbs-1p-y", "    else y = 402;", "    else y = 401;"),
    M("thumbs-2p-y", "BCARSEL_SCREEN_2P) y = 25;", "BCARSEL_SCREEN_2P) y = 26;"),
    M("thumbs-2plo-y", "y = 265;", "y = 264;"),
    M("thumbs-pitch", "        off += 39;", "        off += 38;"),
    M("thumbs-lock-first", "if (!car->available && car->node.prev != &c->set.list" + NL
      + "            && ((VisibleCar*)car->node.prev)->available) {",
      "if (!car->available && car->node.prev != &c->set.list) {"),
    M("thumbs-lock-shift", "        if (lockShown) x += lockW;" + NL, ""),
    M("thumbs-cloaks", "if (covered(c, car) && q < MAX_CLOAKS) {",
      "if (covered(c, car) && q < 3) {"),
    M("thumbs-duration", "    s->duration = 0.5f;", "    s->duration = 1.0f;"),
    M("thumbs-hide-all", "    for (i = 0; i < BCARSEL_MAX_CARS; i++)" + NL
      + "        flailer_set_visibility(c->screen," + NL,
      "    for (i = 0; i < BCARSEL_MAX_CARS - 1; i++)" + NL
      + "        flailer_set_visibility(c->screen," + NL),

    # The fade groups.
    M("fadegroups-a", "float s = c->shownMode * 3.0f;", "float s = c->shownMode * 2.0f;"),
    M("fadegroups-cop", "    if (isCop(cur(c)->type)) fadeScale(&c->fadeB, 0.0f);" + NL, ""),
    M("fadegroups-c-third", "c->shownMode < 1.0f / 3.0f)", "c->shownMode < 0.5f)"),
    M("fadegroups-c-orbit", "    if (c->shownMode == c->orbitMode)" + NL
      + "        fadeScale(&c->fadeC, 0.0f);",
      "    if (c->shownMode == c->orbitMode)" + NL
      + "        fadeScale(&c->fadeC, 0.5f);"),

    # The orbit view and the JoyHandler.
    M("orbit-left", "? -9000.0f", "? -8000.0f"),
    M("orbit-up", "? 10000.0f", "? 11000.0f"),
    M("orbit-lr-scale", "* 70.3125f;", "* 70.0f;"),
    M("orbit-ud-scale", "* -78.125f;", "* 78.125f;"),
    M("orbit-lr-centre", "((float)pressed - 128.0f) * 70.3125f;",
      "((float)pressed - 127.0f) * 70.3125f;"),
    M("joy-fade", "if (!pressed || c->twoPlayer || c->fade != 0) return;",
      "if (!pressed || c->twoPlayer) return;"),
    M("joy-2p", "if (!pressed || c->twoPlayer || c->fade != 0) return;",
      "if (!pressed || c->fade != 0) return;"),
    M("joy-state", "    unlockJoy(c, ev, pressed);" + NL + "    if (c->state != 0) return;",
      "    unlockJoy(c, ev, pressed);"),
    M("joy-touch", "            c->orbitTouched = 1;" + NL
      + "            c->orbitFrame   = RealTimeFrames;" + NL
      + "            c->mover.DesiredHorizSpeed =" + NL,
      "            c->orbitFrame   = RealTimeFrames;" + NL
      + "            c->mover.DesiredHorizSpeed =" + NL),
    M("joy-lr-vert", "c->mover.DesiredHorizSpeed = ((float)pressed",
      "c->mover.DesiredVertSpeed = ((float)pressed"),
    M("can-orbit-help", "if (h->helpMenuActive && h->helpMenuActive(h->user)) return 0;",
      "if (h->helpMenuActive && !h->helpMenuActive(h->user)) return 0;"),
    M("can-orbit-mode", "    if (c->mode != c->chooseMode) return 0;" + NL, ""),
    M("can-orbit-locked", "    return car->available || c->allUnlocked;",
      "    return 1;"),
    M("orbit-speak-lang", "(h->language ? h->language(h->user) : 0) == 0",
      "(h->language ? h->language(h->user) : 0) <= 1"),
    M("orbit-speak-args", "h->speakCar(h->user, car->type, isCop(car->type), isHP(car->type));",
      "h->speakCar(h->user, car->type, isHP(car->type), isCop(car->type));"),
    M("orbit-untouched", "    c->orbitTouched = 0;" + NL + "    if (soundEnabled(h)",
      "    if (soundEnabled(h)"),
    M("choose-fade-level", "if (soundEnabled(c->hooks)) speechFade(c->hooks, 1.0f);",
      "if (soundEnabled(c->hooks)) speechFade(c->hooks, 0.5f);"),

    # The popups.
    M("popup-flags", "cfg.flags        = BPOPUP_HORIZONTAL | BPOPUP_CANCELABLE;",
      "cfg.flags        = BPOPUP_HORIZONTAL;"),
    M("popup-dismiss-param", "cfg.dismissParam = 6;", "cfg.dismissParam = 5;"),
    M("popup-2p-screen", "BCARSEL_SCREEN_2P) cfg.screen = POPUP_SCREEN_2P;",
      "BCARSEL_SCREEN_2P) cfg.screen = POPUP_SCREEN_2P_LO;"),
    M("popup-1p-screen", "BCARSEL_SCREEN_1P) cfg.screen = POPUP_SCREEN_1P;",
      "BCARSEL_SCREEN_1P) cfg.screen = POPUP_SCREEN_2P;"),
    M("popup-trans-start", "cfg.startButton    = c->transmission;",
      "cfg.startButton    = 0;"),
    M("popup-handling-start", "cfg.startButton    = c->handling;",
      "cfg.startButton    = c->transmission;"),
    M("popup-trans-third", "cfg.buttonParam[2] = 3;", "cfg.buttonParam[2] = 2;"),
    M("popup-handling-param", "cfg.buttonParam[1] = 5;", "cfg.buttonParam[1] = 4;"),
    M("popup-wait-param", "cfg.buttonParam[0] = 7;", "cfg.buttonParam[0] = 6;"),
    M("popup-port", "cfg.joyPort      = c->port;", "cfg.joyPort      = 0;"),
    M("advance-top", "if (c->state != 3) c->state++;", "if (c->state != 2) c->state++;"),
    M("devance-floor", "if (c->state != 0) c->state--;", "c->state--;"),

    # The tick.
    M("tick-fade-in", "        c->fade -= 3;", "        c->fade -= 4;"),
    M("tick-fade-out", "        c->fade += 7;", "        c->fade += 6;"),
    M("tick-fade-floor", "        if (c->fade < 0) c->fade = 0;" + NL, ""),
    M("tick-timeout", "&& RealTimeFrames - c->orbitFrame > ORBIT_TIMEOUT) {",
      "&& RealTimeFrames - c->orbitFrame >= ORBIT_TIMEOUT) {"),
    M("tick-timeout-fade", "        if (soundEnabled(h)) speechFade(h, 1.0f);" + NL
      + "    }" + NL + "    if (c->shownMode",
      "    }" + NL + "    if (c->shownMode"),
    M("tick-turn", "#define TURN_STEP       46", "#define TURN_STEP       45"),
    M("tick-turn-touched", "if (c->shownMode == c->chooseMode || !c->orbitTouched)",
      "if (c->shownMode == c->chooseMode)"),
    M("tick-mode-step", "#define MODE_STEP       0.03f", "#define MODE_STEP       0.04f"),
    M("tick-next-rest", "!(bcarsel_next_car(&c->set, cur(c)) == cur(c)" + NL
      + "                             && c->thumbs.state == 0));",
      "!(bcarsel_next_car(&c->set, cur(c)) == cur(c)));"),
    M("tick-swap-rest", "        && c->thumbs.state == 0) {" + NL + "        c->pending = cur(c);",
      "        ) {" + NL + "        c->pending = cur(c);"),
    M("tick-swap-faded", "c->loaded != cur(c) && c->fade == c->fadeMax",
      "c->loaded != cur(c)"),
    M("tick-show-faded", "        if (c->fade == c->fadeMax) showLoadedCar(c);" + NL, ""),
    M("tick-pending-current", "        if (c->loaded == cur(c)) {" + NL
      + "            updateCarCover(c);" + NL + "            showLoadedCar(c);",
      "        if (1) {" + NL
      + "            updateCarCover(c);" + NL + "            showLoadedCar(c);"),

    # The constructor and destructor.
    M("init-fade-max", "c->fadeMax      = 130;", "c->fadeMax      = 128;"),
    M("init-turn", "c->turnAngle = 16123;", "c->turnAngle = 16124;"),
    M("init-tilt", "c->turnTilt  = 15712;", "c->turnTilt  = 15713;"),
    M("init-points", "flailer_printf(screen, OBJ_POINTS, \"%s %d\",",
      "flailer_printf(screen, OBJ_POINTS, \"%s %d \","),
    M("init-no-tick", "    selTick(c);" + NL + "    trace(h, \"carsel player",
      "    trace(h, \"carsel player"),
    M("destroy-sound", "h->stopSound(h->user, 12);", "h->stopSound(h->user, 13);"),
    M("destroy-pending", "    if (c->pending) loaderUnload(h, c->pending->type);" + NL, ""),
    M("destroy-slide", "    slideRestore(&c->unlock.slide);" + NL, ""),

    # The callback.
    M("cb-select-orbit-noise", "            if (c->mode == c->orbitMode) {" + NL
      + "                data->noise = 0;",
      "            if (c->mode == c->orbitMode) {" + NL
      + "                data->noise = 1;"),
    M("cb-select-item", "            if (data->itemHash != BCARSEL_ITEM_CHOOSE) return;" + NL, ""),
    M("cb-select-state", "            if (c->state != 0) return;" + NL
      + "            if (cur(c)->available",
      "            if (cur(c)->available"),
    M("cb-select-locked", "if (cur(c)->available || c->allUnlocked) advanceState(c);",
      "advanceState(c);"),
    M("cb-move-shown", "            if (c->shownMode != c->chooseMode) return;" + NL, ""),
    M("cb-move-sound", "sound(h, msg == BMSG_MENUITEM_PAD_LEFT ? 13 : 12);",
      "sound(h, msg == BMSG_MENUITEM_PAD_LEFT ? 12 : 13);"),
    M("cb-move-sound-fade", "            if (c->fade != c->fadeMax)" + NL
      + "                sound(", "            if (1)" + NL + "                sound("),
    M("cb-move-end", "            if (car == cur(c)) return;" + NL, ""),
    M("cb-skin-param", "            data->param = 1;", "            data->param = 0;"),
    M("cb-skin-one", "&& c->nSwatches >= 2", "&& c->nSwatches >= 1"),
    M("cb-skin-sound", "                sound(h, 14);", "                sound(h, 15);"),
    M("cb-skin-way", "if (msg == BMSG_MENUITEM_PAD_UP) carPrevSkin(cur(c));",
      "if (msg == BMSG_MENUITEM_PAD_UP) carNextSkin(cur(c));"),
    M("cb-skin-show", "                if (c->loaded == cur(c)) showLoadedCar(c);" + NL, ""),
    M("cb-back-param", "                data->param = 0;" + NL
      + "                enterChooseMode(c);",
      "                data->param = 1;" + NL + "                enterChooseMode(c);"),
    M("cb-dismiss-popup", "            c->popup = -1;" + NL
      + "            switch (data->param) {",
      "            switch (data->param) {"),
    M("cb-dismiss-manual", "case 2: c->transmission = 1;", "case 2: c->transmission = 2;"),
    M("cb-dismiss-wait", "                case 7: ok = 1; break;" + NL, ""),
    M("cb-dismiss-noise", "if (maybeContinue()) data->noise = 18;",
      "if (maybeContinue()) data->noise = 17;"),
    M("cb-render", "            unlockRender(c);" + NL, ""),

    # SC-2c: the cover and the shown car.
    M("cover-covered", "eModel* m = covered(c, cur(c)) ? &c->cover : NULL;",
      "eModel* m = covered(c, cur(c)) ? NULL : &c->cover;"),
    M("cover-refl", "c->reflection.pModel = m;", "c->reflection.pModel = NULL;"),
    M("show-skin", "skinAt(c->loaded->status, c->loaded->skinIndex), 0, 0);",
      "skinAt(c->loaded->status, 0), 0, 0);"),
    M("show-dash", "c->loaded->skinIndex), 0, 0);", "c->loaded->skinIndex), 1, 0);"),
    M("show-refl", "    fecar_reinit(&c->reflection, &ri);" + NL, ""),

    # The cars on the turntable.
    M("urcp-loaded", "ct = cti(c->loaded->type);", "ct = cti(cur(c)->type);"),
    M("urcp-lift", "#define CAR_LIFT        0.01f", "#define CAR_LIFT        0.02f"),
    M("urcp-radius", "ct->Wheels[0].Radius - ct->Wheels[0].PositionZ",
      "ct->Wheels[0].Radius + ct->Wheels[0].PositionZ"),
    M("urcp-refl-z", "    if (reflection) z = -z;" + NL, ""),
    M("urcp-pos-x", "f->Position.x = 0.0f;", "f->Position.x = z;"),
    M("urcp-flip-y", "        f->BodyMatrix.v0.y = -f->BodyMatrix.v0.y;" + NL, ""),
    M("urcp-flip-z", "        f->BodyMatrix.v2.z = -f->BodyMatrix.v2.z;" + NL, ""),
    M("urcp-turn", "eRotateZ(&f->BodyMatrix, &f->BodyMatrix, c->turnAngle);",
      "eRotateZ(&f->BodyMatrix, &f->BodyMatrix, c->turnAngle + 1);"),
    M("urcp-steer", "#define WHEEL_STEER     4240", "#define WHEEL_STEER     4241"),
    M("urcp-blend", "(1.0f - c->mover.Blend)", "(1.0f + c->mover.Blend)"),
    M("urcp-steer-round", "* (float)WHEEL_STEER);", "* (float)WHEEL_STEER + 0.5f);"),
    M("urcp-front", "        if (i < 2) {", "        if (i < 1) {"),
    M("urcp-brake-steer", "            eRotateZ(b, b, steer);" + NL, ""),
    M("urcp-tire-roll", "        eRotateY(t, t, 0);" + NL, ""),
    M("urcp-wheel-y", "t->v3.y = b->v3.y = ct->Wheels[i].PositionY;",
      "t->v3.y = b->v3.y = ct->Wheels[i].PositionX;"),
    M("urcp-wheel-w", "        t->v3.w = b->v3.w = 1.0f;", "        t->v3.w = 1.0f;"),

    # The light.
    M("light-one-skin", "car->status->nSkins == 1 ? 0 : car->skinIndex;",
      "car->skinIndex;"),
    M("light-default", "GetTextureInfo(c->swatchColour[i], 1, 0);",
      "GetTextureInfo(c->swatchColour[i], 0, 0);"),
    M("light-covered", "if (!covered(c, car) && ti && ti->ImageData",
      "if (ti && ti->ImageData"),
    M("light-image", "&& ti->ImageData && ti->PaletteData)", "&& ti->PaletteData)"),
    M("light-palsize", "&& ti->ImageData && ti->PaletteData)",
      "&& ti->ImageData && ti->PaletteSize && ti->PaletteData)"),
    M("light-paldata", "&& ti->ImageData && ti->PaletteData)", "&& ti->ImageData)"),
    M("light-texel", "4 * ti->ImageData[3];", "4 * ti->ImageData[2];"),
    M("light-r", "#define LUM_R           0.299f", "#define LUM_R           0.3f"),
    M("light-g", "#define LUM_G           0.587f", "#define LUM_G           0.586f"),
    M("light-b", "#define LUM_B           0.114f", "#define LUM_B           0.115f"),
    M("light-scale", "#define LUM_SCALE       (1.0f / 255.0f)",
      "#define LUM_SCALE       (1.0f / 256.0f)"),
    M("light-square", "        bright *= bright;" + NL + "        bright *= bright;",
      "        bright *= bright;"),
    M("light-one-minus", "bright = 1.0f - ((float)col[0]",
      "bright = 0.5f - ((float)col[0]"),
    M("light-locked-status", "#define CAR_STATUS_LOCKED 2", "#define CAR_STATUS_LOCKED 1"),
    M("light-locked-all", "if (!AllCarsAvailableInCarSelectScreen && !c->allUnlocked && c->loaded",
      "if (!c->allUnlocked && c->loaded"),
    M("light-locked-avail", "        && !c->loaded->available)" + NL
      + "        locked =", "        )" + NL + "        locked ="),

    # The camera.
    M("cam-radius-1p", "#define CAM_RADIUS_1P   12.93f", "#define CAM_RADIUS_1P   12.94f"),
    M("cam-radius-2p", "#define CAM_RADIUS_2P   16.5f", "#define CAM_RADIUS_2P   16.6f"),
    M("cam-heading", "#define CAM_HEADING     0", "#define CAM_HEADING     1"),
    M("cam-tilt-1p", "#define CAM_TILT_1P     15262", "#define CAM_TILT_1P     15263"),
    M("cam-tilt-2p", "#define CAM_TILT_2P     15654", "#define CAM_TILT_2P     15655"),
    M("cam-off-1p", "kOffsetStats1P = {0.27398f", "kOffsetStats1P = {0.27399f"),
    M("cam-off-2p", "{-0.62f, 0.0f, -1.05f", "{-0.62f, 0.0f, -1.06f"),
    M("cam-orbit", "{0.0f, 0.0f, -0.6384f", "{0.0f, 0.0f, -0.6385f"),
    M("cam-fov", "selcam_set_fov_stats(&c->mover, c->turnFOV);",
      "selcam_set_fov_stats(&c->mover, c->turnTilt);"),
    M("cam-2p-radius", "selcam_set_radius_stats(&c->mover, CAM_RADIUS_2P);",
      "selcam_set_radius_stats(&c->mover, CAM_RADIUS_1P);"),
    M("cam-mode-orbit", "selcam_set_mode(&c->mover, SELCAM_MODE_ORBIT);",
      "selcam_set_mode(&c->mover, SELCAM_MODE_STATS);"),
    M("cam-mode-choose", "    adjustHelp(c);" + NL
      + "    selcam_set_mode(&c->mover, SELCAM_MODE_STATS);" + NL, "    adjustHelp(c);" + NL),
    M("cam-mode-timeout", "        adjustHelp(c);" + NL
      + "        selcam_set_mode(&c->mover, SELCAM_MODE_STATS);" + NL,
      "        adjustHelp(c);" + NL),

    # The platform.
    M("render-identity", "                eIdentity(m);" + NL, ""),
    M("render-size", "eframe_malloc(sizeof(bMatrix4))", "eframe_malloc(sizeof(bMatrix4) + 16)"),
    M("render-model", "gEModelRenderFn(&c->platform, m, NULL, 0);",
      "gEModelRenderFn(&c->cover, m, NULL, 0);"),
    M("render-flags", "gEModelRenderFn(&c->platform, m, NULL, 0);",
      "gEModelRenderFn(&c->platform, m, NULL, 4);"),

    # The 3D's constructor and destructor.
    M("init-refl", "    c->reflection.Reflection = 1;" + NL, ""),
    M("init-refl-enabled", "    c->reflection.Enabled    = 1;" + NL, ""),
    M("init-cover-name", "bchunk_hash(\"CARCOVER\")", "bchunk_hash(\"CARCOVR\")"),
    M("init-platform-name", "bchunk_hash(\"PLATFORM\")", "bchunk_hash(\"PLATFORMS\")"),
    M("init-refl-view", "fecar_init(&c->reflection, NULL, playerNum);",
      "fecar_init(&c->reflection, NULL, 0);"),
    M("init-cam-view", "selcam_init(&c->mover, playerNum);", "selcam_init(&c->mover, 0);"),
    M("init-light", "el_set_select_car_lighting(playerNum, 0, 0.0f);",
      "el_set_select_car_lighting(playerNum, 1, 0.0f);"),
    M("destroy-platform-uninit", "    if (c->platform.Solid) emodel_uninit(&c->platform);" + NL, ""),
    M("destroy-platform-solid", "if (c->platform.Solid) emodel_uninit",
      "if (1) emodel_uninit"),
    M("destroy-cover-uninit", "    if (c->cover.Solid) emodel_uninit(&c->cover);" + NL, ""),
    M("destroy-unhook", "    c->car.pModel        = NULL;" + NL, ""),
    M("destroy-cam", "    selcam_destroy(&c->mover);" + NL, ""),
    M("destroy-refl", "    fecar_delete(&c->reflection, 2);" + NL, ""),
    M("destroy-platform-delete", "    emodel_delete(&c->platform, 2);" + NL, ""),
    M("destroy-cover-delete", "    emodel_delete(&c->cover, 2);" + NL, ""),
    M("tick-urcp-refl", "updateRenderingCarParameters(c, &c->reflection, 1);",
      "updateRenderingCarParameters(c, &c->reflection, 0);"),
    M("tick-light", "    updateLighting(c);" + NL, ""),

    # SelectCarScreen.
    M("selector-index", "return Fred.NumPlayerCars == 2 ? data->port != 0 : 0;",
      "return data->port != 0;"),
    M("activate-port-none", "        if (data->port == -1) return;" + NL
      + "        idx = data->port != 0;" + NL + "    }" + NL
      + "    player = &Fred.FrontendPlayers[idx];",
      "        idx = data->port != 0;" + NL + "    }" + NL
      + "    player = &Fred.FrontendPlayers[idx];"),
    M("activate-player-num", "idx ? 2 : 1, data->itemHash", "idx ? 1 : 2, data->itemHash"),
    M("activate-cops", "idx == 0 && Fred.GameType == GAME_TYPE_BE_A_COP);",
      "Fred.GameType == GAME_TYPE_BE_A_COP);"),
    M("activate-count", "    p->count++;" + NL, ""),
    M("deactivate-count", "    p->count--;" + NL, ""),
    M("setsel-manual", "player->mPlayerSettings.TransmissionType = 2;",
      "player->mPlayerSettings.TransmissionType = 1;"),
    M("setsel-style", "else if (c->handling == 1) player->mPlayerSettings.DrivingStyle = 1;",
      "else if (c->handling == 1) player->mPlayerSettings.DrivingStyle = 0;"),
    M("setsel-dash", "(uint32_t)skinAt(car->status, car->skinIndex)," + NL
      + "                               1);",
      "(uint32_t)skinAt(car->status, car->skinIndex)," + NL
      + "                               0);"),
    M("all-ready", "c->state != (c->twoPlayer ? 3 : 2)", "c->state != (c->twoPlayer ? 2 : 2)"),
    M("continue-champ", "if (Fred.GameType == 8 || Fred.GameType == 9) {",
      "if (Fred.GameType == 8) {"),
    M("continue-screen", "\"Select Track\", 1);", "\"Select Track\", 0);"),
    M("unactivate-help", "            setHelp(h, NULL);" + NL
      + "            screenDeactivate(p, data);",
      "            screenDeactivate(p, data);"),
    M("unactivate-fade", "speechFade(h, 0.2f);", "speechFade(h, 0.25f);"),
    M("unactivate-perport", "                h->setPerPortJoy(h->user, 0);",
      "                h->setPerPortJoy(h->user, 1);"),
    M("back-selected", "            if (p) screenSetSelectedCars(p);" + NL, ""),
    M("joy-port-filter", "if (c->twoPlayer && c->port != port) continue;",
      "if (c->port != port) continue;"),
]

EQUIVALENT = {
    "slide-init-start": "the constructor's unlockSetCar sets the slide up "
                        "again from 650 before anything reads it: u->car "
                        "starts NULL and the current car never is",
    "unlock-render-avail": "the box is at state 2 only with no car or a "
                           "locked one: SetCar puts an available car's at 0, "
                           "and only a locked car's hides to 1 and back",
    "unlock-joy-avail": "the same: at state 2 the car is a locked one",
    "badge-1p": "\"Select Car\" has no BADGE object, so the one-player "
                "badge's texture and visibility go nowhere",
    "thumbs-hide-all": "car 63, the FIRETRUCK, has no THUMBNAIL_ object on "
                       "any of the three screens",
    # SC-2c's.
    "urcp-flip-y": "the identity's v0.y is 0, and eRotateZ's sums lose the "
                   "sign of the -0 the flip makes",
    "urcp-tire-roll": "eRotateY by 0 multiplies by an exact identity: the "
                      "table's sine of 0 is 0 and its cosine 1",
    "urcp-wheel-w": "eIdentity has already put 1 in the brake's v3.w, and "
                    "eRotateZ leaves row 3 alone",
    "light-one-skin": "SetSkin, NextSkin and PrevSkin can only leave a "
                      "one-skin car's index at 0",
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
        todo, SOURCES, "carsel_test",
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
