#!/usr/bin/env python3
"""Cross-check 3DS Files/source/playerzone.c's camera zones and the jump
cam's two movers against the retail image itself, run in mipsemu.

The model is the image. Player::RequestZone (0x00177c88), ClearZone
(0x00178358), ClearZoneSound (0x00178470) and PlayerClearZone (0x00177c80)
run as shipped, and so do ChangeCameraMover's types 15 and 16 (0x00176ddc
and 0x00177200, from ChangeCameraMover itself, 0x00176ae8, on a player with
no mover), over retail's PreviewRoutePoint and TrackRoutePoint
GetPositions. The harness (tools/src/playerzone_test.c) runs the port over
the same script, and the two transcripts are diffed.

Stubs, each printing its call as the harness prints the port's:
IsNisPlaying and IsReplayDemoMode answer the script; ChangeCameraMover
(outside "J") gives a fake mover, M0, M1, ...; RestoreCameraMover,
CleanUpJumpCam, ClearHudAnimations and DetermineInputMode print; World's
SetWorldPaused and SetTimeScale print and keep the callback for "X" to
fire, ResetTimeScale prints; RadialBlurOn and Off print the view;
ZoneFreezeCameraMover::Duration, ZonePreviewCameraMover::FindRoute,
ViolatesTopology and the preview's duration answer the script. The sound:
GetCategoryVolume answers the script; bOMalloc on the sample pool gives a
sample, S0, S1, ..., whose vtable's destructor prints it; the bSample
constructor, Initialize, SetCategory and Play print; CommonRegion's Sample
gives RS and GetInGameSample I0 to I3 by name. For the movers: bMalloc
hands out 0xa5-filled blocks and prints its name, line and size; the
TrackCarCameraMover constructor prints its arguments and the shake's
nonzero words; the TrackPathCoordinate constructor writes the script's
ratio; the TopologyCoordinate's constructor and destructor print, and
GetElevation prints its point and answers the script.

The pad lanes of the eye points, the bank points and the field-of-view
table are the stack's in retail and are not compared.

    python tools/playerzone_check.py
    python tools/playerzone_check.py --mutate [--only a,b]
    python tools/playerzone_check.py --dump out/playerzone
"""
import argparse
import math
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
from mipsemu import M32, f_to_bits, s32

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

HARNESS = "tools/src/playerzone_test.c"
PZC = "3DS Files/source/playerzone.c"
SOURCES = [HARNESS, PZC] + ["3DS Files/source/" + f for f in (
    "previewroute.c", "trackroute.c", "trackpath.c", "quickspline.c",
    "replay.c", "p32.c",
    "bvector.c", "bmath.c", "bmathtab.c", "bmatrix.c")]

HARNESS_TIMEOUT = 120

# ================================================================ the image

GP = 0x003358f0
REQUEST_ZONE = 0x00177c88
CLEAR_ZONE = 0x00178358
CLEAR_ZONE_SOUND = 0x00178470
PLAYER_CLEAR_ZONE = 0x00177c80
CHANGE_MOVER = 0x00176ae8
IS_NIS = 0x00176520
IS_REPLAY_DEMO = 0x001369a8
RESTORE_MOVER = 0x00176948
CLEAN_UP_JUMP_CAM = 0x00176ab0
INPUT_MODE = 0x00177608
CLEAR_HUD = 0x0017c7c8
FREEZE_DURATION = 0x00161098
FIND_ROUTE = 0x00163708
VIOLATES = 0x00164180
PREVIEW_DURATION = 0x001637c8
SET_TIME_SCALE = 0x0014d620
RESET_TIME_SCALE = 0x0014d638
SET_WORLD_PAUSED = 0x0014d658
BLUR_ON = 0x0010f178
BLUR_OFF = 0x0010f1b0
COMMON_REGION = 0x002779e0
REGION_SAMPLE = 0x002719b8
SAMPLE_PLAY = 0x00274080
CATEGORY_VOLUME = 0x00277dc0
B_OMALLOC = 0x00257c80
SAMPLE_CTOR = 0x00272ff0
GET_IN_GAME = 0x001ae280
SAMPLE_INIT = 0x00273210
SAMPLE_SET_CATEGORY = 0x00273618
B_MALLOC = 0x002577c0
TCC_CTOR = 0x00159130
TPC_CTOR = 0x002086f0
TPC_DTOR = 0x00208748
TOPO_CTOR = 0x00151c28
TOPO_DTOR = 0x00151c70
GET_ELEVATION = 0x00152070

G_RC = GP - 22216                 # pRaceCoordinator
G_RACE = GP - 22272               # pCurrentRace
G_WORLD = GP - 22120              # pCurrentWorld
G_TWEAKER = GP - 22116            # TweakerPauseWorld
G_WORLD_TIMER = GP - 19576
G_REAL_TIMER = GP - 19608
G_ELAPSED = GP - 19560            # WorldTimeElapsed
G_SOUND_ENABLED = GP - 23056
G_THE_SOUND = GP - 13696
G_SAMPLE_POOL = GP - 13816
G_NUM_PLAYERS = GP - 20920
G_PLAYERS = GP - 20928            # PlayerPlayersByIndex
TRACK_DIRECTION = 0x0031a8a4      # TheRaceParameters.TrackDirection
JUMP_CAMS = 0x0031ab8a            # .GlobalDisplaySettings.JumpCams
ZONE_CAMS = 0x0031ab8b

POOL = 0x01200000
POOL_END = 0x01300000
PLAYER0 = 0x01300000
PLAYER1 = 0x01301000
CAR = 0x01302000
CD = 0x01303000
FOV = 0x01303200
PR = 0x01304000
PTS = 0x01304100
RPTS = 0x01305000
RC = 0x01307000
RACE = 0x01307100
WORLD = 0x01307200
SOUND = 0x01307300
SAMPLE_POOL = 0x01307400
REGION = 0x01307500
RS = 0x01307600
INGAME = 0x01307700
FAKE_ROUTE = 0x01307800
VTABLE = 0x01307900
DELETE_FN = 0x01307a00
MOVERS = 0x01310000
SAMPLES = 0x01320000

NPOINTS = 40
PLAYER_SIZE = 2752

P_CAR = 4
P_NUMBER = 16
P_VIEW = 24
P_ZONE = 88
P_ZONE_PREV = 92
P_TIMERS = 104
P_ROUTE = 136
P_SAMPLE = 140
P_MUFFLE = 144
P_MUFFLE_VOLUME = 148
P_IGNORE_POV = 152
P_MOVER = 200
P_WRONG_WAY = 760
P_CD = 1652
P_EYE = 1664
P_BANK = 1712
P_FOV = 1760
P_JUMP_ROUTE = 1764

C_POS = 96
C_VEL = 112
C_RATIO = 2032

S_VTABLE = 184

INGAME_NAMES = ("Wind", "PreviewZone", "SlomoZone")

PATTERN = 0xa5
PAT32 = 0xa5a5a5a5


def fb(v):
    if isinstance(v, int):
        return v & M32
    return f_to_bits(v)


def h(v):
    return "%08x" % fb(v)


def f32(v):
    return struct.unpack("<f", struct.pack("<f", v))[0]


def fx(w):
    """A float's bits, with every NaN the one "nan"."""
    w &= M32
    if (w & 0x7f800000) == 0x7f800000 and (w & 0x7fffff):
        return "nan"
    return "%08x" % w


def bits_f(w):
    return struct.unpack("<f", struct.pack("<I", w & M32))[0]


# ============================================================ the scenarios


def route_points(rnd, n, flat=False):
    """`pp` and `rp` lines for n route points along a rough line."""
    out = ["pp %d" % n]
    x, y = rnd.uniform(-800, 800), rnd.uniform(-800, 800)
    a = rnd.uniform(0, 2 * math.pi)
    elev = rnd.uniform(-5, 5)
    for i in range(n):
        a += rnd.uniform(-0.3, 0.3)
        dx, dy = math.cos(a), math.sin(a)
        x += dx * rnd.uniform(3, 6)
        y += dy * rnd.uniform(3, 6)
        elev += rnd.uniform(-1, 1)
        bank = 0.0 if flat or rnd.random() < 0.3 else rnd.uniform(-0.2, 0.2)
        fwd = 0.0 if flat or rnd.random() < 0.3 else rnd.uniform(-0.2, 0.2)
        out.append("rp %d %s %s %s %s %s %s %s %s %s" % (
            i, h(x), h(y), h(elev), h(dx), h(dy), h(rnd.uniform(1, 12)),
            h(rnd.uniform(1, 12)), h(bank), h(fwd)))
    return out


def car_line(rnd, z=None, still=False):
    if still:
        v = (0.0, 0.0, 0.0)
    else:
        v = (rnd.uniform(-60, 60), rnd.uniform(-60, 60), rnd.uniform(-5, 5))
    if z is None:
        z = rnd.uniform(-6, 10)
    return "car %s %s %s %s %s %s %s" % (
        h(rnd.uniform(-800, 800)), h(rnd.uniform(-800, 800)), h(z),
        h(v[0]), h(v[1]), h(v[2]), h(rnd.uniform(0, 1)))


def s_jumpers(rnd):
    out = []
    for _ in range(10):
        out.append("dir %d" % rnd.choice((0, 0, 1)))
        n = rnd.choice((3, 4, 5, 6, 6, 7, 9, 12, 20))
        out += route_points(rnd, n)
        out.append(car_line(rnd, still=rnd.random() < 0.15))
        out.append("tr %s" % h(rnd.uniform(0, 1)))
        out.append("el %s" % h(rnd.uniform(-8, 10)))
        out.append("J 0")
        for _ in range(rnd.choice((0, 1, 1, 2))):
            out.append(car_line(rnd))
            out.append("el %s" % h(rnd.uniform(-8, 12)))
            if rnd.random() < 0.3:
                out.append("dir %d" % rnd.choice((0, 1)))
            out.append("J 1")
    return out


def s_jump_edges(rnd):
    """Ties: the ground at the eye's height, the car at the top point's, a
    still car (both edges the same along its velocity), and the ratios at
    0 and 1."""
    out = []
    for _ in range(8):
        e = rnd.uniform(-4, 4)
        out += [ln if not ln.startswith("rp ") else
                " ".join(ln.split()[:4] + [h(e)] + ln.split()[5:])
                for ln in route_points(rnd, rnd.choice((5, 6, 7)),
                                       flat=True)]
        out.append(car_line(rnd, still=rnd.random() < 0.5))
        out.append("tr %s" % h(rnd.choice((0.0, 1.0, 0.25))))
        eye = f32(f32(e) + 1.0)
        out.append("el %s" % h(rnd.choice((eye, eye, f32(eye + 1e-5),
                                           f32(eye - 1e-5)))))
        out.append("J 0")
        z = f32(rnd.uniform(-4, 4))
        out.append("ey 2 %s %s %s" % (h(1.0), h(2.0), h(z)))
        out.append(car_line(rnd, z=rnd.choice((z, z, f32(z + 1e-5)))))
        top = rnd.choice((z, f32(z + 1e-5)))
        out.append("el %s" % h(rnd.choice((top, f32(top - 1e-5),
                                           f32(top + 0.5)))))
        out.append("J 1")
    # Type 16 alone, on the fill.
    out.append("eh %s" % h(0.4))
    out.append(car_line(rnd))
    out.append("J 1")
    return out


class Zones(object):
    """Random request, clear and fire ops over a changing world."""

    def __init__(self, rnd):
        self.rnd = rnd
        self.wt = 100000
        self.out = []

    def tick(self):
        rnd = self.rnd
        d = rnd.choice((rnd.randint(0, 600), rnd.randint(19000, 21000),
                        rnd.randint(0, 40000), rnd.randint(0, 40000),
                        rnd.choice((0, 399, 400, 401, 19999, 20000, 20001)),
                        -rnd.randint(1, 500)))
        self.wt = (self.wt + d) & M32
        self.out.append("wt %08x" % self.wt)

    def toggle(self):
        rnd = self.rnd
        k = rnd.choice(("rc", "rc", "rd", "st", "nis", "tw", "se", "cv",
                        "jc", "zc", "np", "ww", "fr", "vt", "fd", "pd", "we",
                        "rt", "zn", "sm", "tm"))
        good = rnd.random() < 0.6
        if k == "rc":
            v = 3 if good else rnd.choice((0, 1, 2, 4, 5, 6, 7, 8, 9))
        elif k == "st":
            v = 4 if good else rnd.choice((0, 1, 2, 3, 5))
        elif k in ("rd", "nis", "tw", "ww", "vt"):
            v = 0 if good else 1
        elif k in ("se", "jc", "zc", "fr"):
            v = 1 if good else 0
        elif k == "np":
            v = 1 if good else rnd.choice((0, 2))
        elif k == "cv":
            v = h(rnd.choice((1.0, 0.5, 0.0, -0.0, -0.25, 1e-30)))
        elif k in ("fd", "pd", "we"):
            v = h(rnd.uniform(-1, 6))
        elif k == "rt":
            v = "%08x" % rnd.getrandbits(32)
        elif k == "zn":
            v = rnd.choice((0, 0, 1, 2, 3, 4, 5, 6, 7))
        elif k == "sm":
            v = rnd.choice((0, 1))
        else:
            i = rnd.randint(0, 7)
            v = "%d %08x" % (i, rnd.choice((
                0, 0x7fffffff, self.wt, (self.wt - 20000) & M32,
                (self.wt - 400) & M32, (self.wt + 100) & M32,
                (self.wt ^ 0x80000000) & M32, rnd.getrandbits(32))))
        self.out.append("%s %s" % (k, v))

    def action(self):
        rnd = self.rnd
        r = rnd.random()
        if r < 0.55:
            force = int(rnd.random() < 0.3)
            if force:
                zone = rnd.choice(list(range(-1, 10)))
            else:
                zone = rnd.randint(0, 7)
            self.out.append("Z %d %d %d %d" % (
                zone, force, int(rnd.random() < 0.7),
                int(rnd.random() < 0.5)))
        elif r < 0.75:
            self.out.append("C %d" % rnd.choice((0, 1)))
        elif r < 0.85:
            self.out.append("S")
        else:
            self.out.append("X")

    def run(self, steps):
        rnd = self.rnd
        for _ in range(steps):
            r = rnd.random()
            if r < 0.2:
                self.tick()
            elif r < 0.45:
                self.toggle()
            else:
                self.action()
        return self.out


def s_zones(rnd, steps=80):
    return Zones(rnd).run(steps)


def s_each_zone(rnd):
    """Every zone from a clean start, with the sound on and off, then
    cleared by its callback and by hand."""
    out = []
    wt = 100000
    for zone in range(8):
        for sound, muffle in ((1, 0), (1, 1), (0, 1)):
            wt += 30000
            out.append("wt %08x" % wt)
            out.append("Z %d 0 %d %d" % (zone, sound, muffle))
            out.append("X" if sound else "C 1")
            out.append("C 0")
    return out


def s_refusals(rnd):
    """Each of RequestZone's noes, one at a time, with a good request
    after each to show the world was left as it was."""
    out = []
    wt = [100000]

    def later():
        wt[0] += 30000
        out.append("wt %08x" % wt[0])

    def ask(zone, force=0):
        later()
        out.append("Z %d %d 1 0" % (zone, force))

    for zone in range(1, 8):
        for bad, fix in (("nis 1", "nis 0"), ("rc 8", "rc 3"),
                         ("st 3", "st 4"), ("np 2", "np 1"),
                         ("jc 0", "jc 1"), ("zc 0", "zc 1"),
                         ("rc 4", "rc 3"), ("rc 5", "rc 3"),
                         ("rc 7", "rc 3"), ("rd 1", "rd 0"),
                         ("ww 1", "ww 0"), ("fr 0", "fr 1"),
                         ("vt 1", "vt 0"), ("se 0", "se 1"),
                         ("cv 00000000", "cv 3f800000")):
            out.append(bad)
            ask(zone)
            out.append(fix)
            out.append("C 1")
            ask(zone)
            out.append("C 1")
    # The zone a player is in: the freeze and the preview are cleared
    # first, 3 to 7 refuse. (Past 7 both index past the tables, as
    # nothing in the game can.)
    for cur in range(8):
        for zone in (1, 3, 6):
            out.append("zn %d" % cur)
            ask(zone)
            out.append("zn 0")
    # Zones out of range, with force.
    for zone in (-1, 8, 9, 0):
        ask(zone, 1)
    out.append("np 0")
    ask(3)
    out.append("C 1")
    out.append("np 1")
    return out


def s_timers(rnd):
    """The 5 s between a zone's starts, the 0.1 s after a freeze or a
    preview ends, at their edges, and the timer's unset values."""
    out = []
    base = 0x00100000
    for zone in (1, 3, 6, 2):
        for d in (19998, 19999, 20000, 20001, 20002, 0, -1, -20000,
                  0x7fffffff, -0x80000000):
            for t in (0, 0x7fffffff, base):
                out.append("tm %d %08x" % (zone, t))
                out.append("wt %08x" % ((base + d) & M32))
                out.append("Z %d 0 0 0" % zone)
                out.append("C 0")
    for d in (398, 399, 400, 401, 402, 0, -1, 0x7fffffff, -0x80000000):
        for t in (0, 0x7fffffff, base):
            out.append("tm 0 %08x" % t)
            out.append("wt %08x" % ((base + d) & M32))
            out.append("Z 3 1 0 0")
            out.append("C 0")
    # ClearZone's stamp, with the tweaker's pause and without.
    for tw in (0, 1):
        out.append("tw %d" % tw)
        for zone in (1, 2, 3, 6):
            out.append("wt %08x" % (base + 0x10000 * zone))
            out.append("zn %d" % zone)
            out.append("C 0")
    return out


def s_clears(rnd):
    """ClearZone from each zone, in a replay and out, with and without a
    sample, and ClearZoneSound."""
    out = []
    for rc, rd in ((3, 0), (4, 0), (5, 0), (7, 0), (9, 1), (6, 0)):
        out += ["rc %d" % rc, "rd %d" % rd]
        for zone in (-1, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9):
            for sm, se, sound in ((1, 1, 1), (1, 0, 1), (1, 1, 0), (0, 1, 1)):
                out += ["zn %d" % zone, "sm %d" % sm, "se %d" % se,
                        "C %d" % sound]
        out += ["se 1", "rc 3", "rd 0"]
    for sm, se in ((1, 1), (0, 1), (1, 0)):
        out += ["sm %d" % sm, "se %d" % se, "S", "S"]
    return out


def s_jump_ties(rnd):
    """A straight road, banked, and velocities at right angles to the line
    between its edges, so that the two dot products differ by their
    roundings and the order of the sums picks the edge; or straight up,
    where only z picks it."""
    out = []
    for _ in range(80):
        a = rnd.uniform(0, 2 * math.pi)
        dx, dy = f32(math.cos(a)), f32(math.sin(a))
        bank = f32(rnd.choice((-1, 1)) * rnd.uniform(0.02, 0.3))
        x, y, e = (rnd.uniform(-800, 800), rnd.uniform(-800, 800),
                   rnd.uniform(-5, 5))
        n = rnd.choice((5, 6, 7))
        out.append("pp %d" % n)
        for i in range(n):
            out.append("rp %d %s %s %s %s %s %s %s %s %s" % (
                i, h(x + dx * 5 * i), h(y + dy * 5 * i), h(e), h(dx), h(dy),
                h(rnd.uniform(1, 12)), h(rnd.uniform(1, 12)), h(bank),
                h(0.0)))
        if rnd.random() < 0.25:
            v = (0.0, 0.0, rnd.choice((-1, 1)) * rnd.uniform(1, 20))
        else:
            s, t = rnd.uniform(-60, 60), rnd.uniform(-20, 20)
            v = (s * dx + t * bank * dy, s * dy - t * bank * dx, -t)
        out.append("car %s %s %s %s %s %s %s" % (
            h(x + rnd.uniform(-30, 30)), h(y + rnd.uniform(-30, 30)),
            h(e + rnd.uniform(-2, 2)), h(v[0]), h(v[1]), h(v[2]),
            h(rnd.uniform(0, 1))))
        out.append("J 0")
    return out


def s_quiet_wrong(rnd):
    """The preview's "MenuWrong" with the sound off."""
    out = ["se 0"]
    wt = 100000
    for bad, fix in (("ww 1", "ww 0"), ("fr 0", "fr 1"), ("vt 1", "vt 0")):
        wt += 30000
        out += [bad, "wt %08x" % wt, "Z 2 0 1 0", fix]
    return out


def script():
    rnd = random.Random(0x20e5a3)
    sc = [s_jumpers(rnd), s_jump_edges(rnd), s_each_zone(rnd),
          s_refusals(rnd), s_timers(rnd), s_clears(rnd)]
    for _ in range(12):
        sc.append(s_zones(rnd))
    for _ in range(3):
        sc.append(s_jumpers(rnd))
    sc.append(s_jump_ties(random.Random(0x71e5)))
    sc.append(s_quiet_wrong(None))
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
        self.w = e.u32
        for addr, fn in (
                (IS_NIS, self.s_nis), (IS_REPLAY_DEMO, self.s_replay_demo),
                (CHANGE_MOVER, self.s_change_mover),
                (RESTORE_MOVER, self.s_print("restore")),
                (CLEAN_UP_JUMP_CAM, self.s_print("cleanup")),
                (INPUT_MODE, self.s_print("inputmode")),
                (CLEAR_HUD, self.s_print("clearhud")),
                (FREEZE_DURATION, self.s_freeze_duration),
                (FIND_ROUTE, self.s_find_route), (VIOLATES, self.s_violates),
                (PREVIEW_DURATION, self.s_preview_duration),
                (SET_TIME_SCALE, self.s_time_scale),
                (RESET_TIME_SCALE, self.s_reset_time_scale),
                (SET_WORLD_PAUSED, self.s_paused),
                (BLUR_ON, self.s_blur("bluron")),
                (BLUR_OFF, self.s_blur("bluroff")),
                (COMMON_REGION, self.s_common_region),
                (REGION_SAMPLE, self.s_region_sample),
                (SAMPLE_PLAY, self.s_play),
                (CATEGORY_VOLUME, self.s_category_volume),
                (B_OMALLOC, self.s_omalloc), (SAMPLE_CTOR, self.s_sample_ctor),
                (GET_IN_GAME, self.s_in_game), (SAMPLE_INIT, self.s_init),
                (SAMPLE_SET_CATEGORY, self.s_set_category),
                (DELETE_FN, self.s_delete),
                (B_MALLOC, self.s_malloc), (TCC_CTOR, self.s_tcc),
                (TPC_CTOR, self.s_tpc), (TPC_DTOR, lambda em: None),
                (TOPO_CTOR, self.s_topo), (TOPO_DTOR, self.s_topodel),
                (GET_ELEVATION, self.s_elevation)):
            e.stub(addr, fn)

    def emit(self, s):
        self.out.append(s)

    def arg(self, i):
        return self.e.reg[(4, 5, 6, 7, 8, 9)[i]] & M32

    def cstr(self, a):
        mem = self.e.mem
        end = mem.index(0, a)
        return bytes(mem[a:end]).decode("latin-1")

    def fill(self, a, n):
        self.e.mem[a:a + n] = bytes([PATTERN]) * n

    def put_f(self, a, s):
        self.e.put32(a, int(s, 16))

    # ---- names -----------------------------------------------------------

    def name(self, a):
        a &= M32
        fixed = {0: "null", PAT32: "pat", PLAYER0: "p0", PLAYER1: "p1",
                 CAR: "car", CD: "cd", FOV: "fov", PLAYER0 + P_EYE: "eye",
                 PLAYER0 + P_BANK: "bank", PR: "pr", FAKE_ROUTE: "route",
                 WORLD: "world", RS: "RS", RC: "rc"}
        if a in fixed:
            return fixed[a]
        if INGAME <= a < INGAME + 64 and (a - INGAME) % 16 == 0:
            return "I%d" % ((a - INGAME) // 16)
        if MOVERS <= a < MOVERS + 0x40 * self.nmovers \
                and (a - MOVERS) % 0x40 == 0:
            return "M%d" % ((a - MOVERS) // 0x40)
        if SAMPLES <= a < SAMPLES + 0x100 * self.nsamples \
                and (a - SAMPLES) % 0x100 == 0:
            return "S%d" % ((a - SAMPLES) // 0x100)
        for i, b in enumerate(self.allocs):
            if a == b:
                return "A%d" % i
        return "?%08x" % a

    def cb_name(self, a):
        return "clearzone" if a == PLAYER_CLEAR_ZONE else "?"

    # ---- the stubs -------------------------------------------------------

    def s_print(self, what):
        def fn(em):
            self.emit("  %s %s" % (what, self.name(self.arg(0))))
        return fn

    def s_blur(self, what):
        def fn(em):
            self.emit("  %s %d" % (what, s32(self.arg(0))))
        return fn

    def s_nis(self, em):
        self.emit("  nis %s -> %d" % (self.name(self.arg(0)), self.nis))
        return self.nis

    def s_replay_demo(self, em):
        self.emit("  replaydemo %s -> %d" % (self.name(self.arg(0)),
                                             self.replay_demo))
        return self.replay_demo

    def s_change_mover(self, em):
        p, typ, keep = self.arg(0), s32(self.arg(1)), s32(self.arg(2))
        m = MOVERS + 0x40 * self.nmovers
        self.nmovers += 1
        self.fill(m, 0x40)
        self.emit("  ccm %s %d %d -> %s" % (self.name(p), typ, keep,
                                            self.name(m)))
        self.e.put32(p + P_MOVER, m)

    def s_freeze_duration(self, em):
        self.emit("  freezedur -> %s" % fx(self.freeze_dur))
        em.fpr[0] = self.freeze_dur

    def s_find_route(self, em):
        r = FAKE_ROUTE if self.find_route else 0
        self.emit("  findroute %s -> %s" % (self.name(self.arg(0)),
                                            self.name(r)))
        return r

    def s_violates(self, em):
        self.emit("  violates %s -> %d" % (self.name(self.arg(0)),
                                           self.violates))
        return self.violates

    def s_preview_duration(self, em):
        self.emit("  previewdur %s -> %s" % (self.name(self.arg(0)),
                                             fx(self.preview_dur)))
        em.fpr[0] = self.preview_dur

    def s_time_scale(self, em):
        w, cb, param = self.arg(0), self.arg(1), self.arg(2)
        self.emit("  scale %s %s %s %s %s" % (
            self.name(w), fx(em.fpr[12]), fx(em.fpr[13]), self.cb_name(cb),
            self.name(param)))
        self.cb = (cb, param)

    def s_paused(self, em):
        w, cb, param = self.arg(0), self.arg(1), self.arg(2)
        self.emit("  paused %s %s %s %s" % (
            self.name(w), fx(em.fpr[12]), self.cb_name(cb), self.name(param)))
        self.cb = (cb, param)

    def s_reset_time_scale(self, em):
        self.emit("  resetscale %s" % self.name(self.arg(0)))

    def s_common_region(self, em):
        assert self.arg(0) == SOUND
        return REGION

    def s_region_sample(self, em):
        assert self.arg(0) == REGION
        self.emit("  region %s -> RS" % self.cstr(self.arg(1)))
        return RS

    def s_play(self, em):
        self.emit("  play %s %s %s %s" % (
            self.name(self.arg(0)), fx(em.fpr[12]), fx(em.fpr[13]),
            fx(em.fpr[14])))

    def s_category_volume(self, em):
        assert self.arg(0) == SOUND
        self.emit("  catvol %d -> %s" % (self.arg(1), fx(self.cat_volume)))
        em.fpr[0] = self.cat_volume

    def new_sample(self):
        s = SAMPLES + 0x100 * self.nsamples
        self.nsamples += 1
        self.fill(s, 0x100)
        self.e.put32(s + S_VTABLE, VTABLE)
        self.emit("  newsample %s" % self.name(s))
        return s

    def s_omalloc(self, em):
        assert self.arg(0) == SAMPLE_POOL
        return self.new_sample()

    def s_sample_ctor(self, em):
        return self.arg(0)

    def s_in_game(self, em):
        n = self.cstr(self.arg(0))
        k = INGAME_NAMES.index(n) if n in INGAME_NAMES else 3
        r = INGAME + 16 * k
        self.emit("  ingame %s -> %s" % (n, self.name(r)))
        return r

    def s_init(self, em):
        self.emit("  init %s %s" % (self.name(self.arg(0)),
                                    self.name(self.arg(1))))

    def s_set_category(self, em):
        self.emit("  setcat %s %08x" % (self.name(self.arg(0)), self.arg(1)))

    def s_delete(self, em):
        assert s32(self.arg(1)) == 3
        self.emit("  deletesample %s" % self.name(self.arg(0)))

    def s_malloc(self, em):
        size, name, line = s32(self.arg(0)), self.arg(1), s32(self.arg(2))
        a = (self.pool + 15) & ~15
        self.pool = a + max(size, 0)
        assert self.pool < POOL_END
        self.fill(a, max(size, 0))
        self.allocs.append(a)
        self.emit("  malloc A%d %s %d size %d" % (
            len(self.allocs) - 1, self.cstr(name), line, size))
        return a

    def s_tcc(self, em):
        m, view, car, cd, shake, fe = (self.arg(i) for i in range(6))
        words = []
        for i in range(0, 560, 4):
            v = self.w(shake + i)
            if v:
                words.append(" %d:%08x" % (i, v))
        self.emit("  tcc %s view %d car %s cd %s fe %d shake%s" % (
            self.name(m), s32(view), self.name(car), self.name(cd), s32(fe),
            "".join(words)))
        return m

    def s_tpc(self, em):
        c, pos = self.arg(0), self.arg(1)
        self.emit("  tpc %s %s -> %s" % (fx(self.w(pos)), fx(self.w(pos + 4)),
                                         fx(self.tpc_ratio)))
        self.e.put32(c + 16, self.tpc_ratio)
        return c

    def s_topo(self, em):
        self.emit("  topo")
        self.topo_at = self.arg(0)
        return self.arg(0)

    def s_topodel(self, em):
        self.emit("  topodel %s"
                  % ("same" if self.arg(0) == self.topo_at else "other"))

    def s_elevation(self, em):
        tc, pt = self.arg(0), self.arg(1)
        self.emit("  elev %s %s %s %s %d%d%d -> %s" % (
            "same" if tc == self.topo_at else "other", fx(self.w(pt)),
            fx(self.w(pt + 4)), fx(self.w(pt + 8)), self.arg(2) != 0,
            self.arg(3) != 0, self.arg(4) != 0, fx(self.elevation)))
        em.fpr[0] = self.elevation

    # ---- the dumps -------------------------------------------------------

    def dump_player(self):
        w, p = self.w, PLAYER0
        self.emit("  pz zone %d prev %d t %s pov %08x" % (
            s32(w(p + P_ZONE)), s32(w(p + P_ZONE_PREV)),
            " ".join("%08x" % w(p + P_TIMERS + 4 * i) for i in range(8)),
            w(p + P_IGNORE_POV)))
        self.emit("  pz route %s sample %s muffle %d %s mover %s" % (
            self.name(w(p + P_ROUTE)), self.name(w(p + P_SAMPLE)),
            s32(w(p + P_MUFFLE)), fx(w(p + P_MUFFLE_VOLUME)),
            self.name(w(p + P_MOVER))))

    def dump_v(self, tag, i, a):
        self.emit("  %s %d %s %s %s" % (tag, i, fx(self.w(a)),
                                        fx(self.w(a + 4)), fx(self.w(a + 8))))

    def dump_jumper(self):
        w, d, n = self.w, CD, self.name

        def i(off):
            return s32(w(d + off))

        def f(off):
            return fx(w(d + off))

        self.emit("  cd type %d name %s iso %d min %s max %s es %s ls %s"
                  " fs %s le %d ll %d" % (
                      i(0), n(w(d + 4)), i(8), f(12), f(16), f(20), f(24),
                      f(28), i(32), i(36)))
        self.emit("  cd mina %s maxa %s near %s far %s back %d fov %s nav %d"
                  " av %s naf %d af %s" % (
                      f(40), f(44), f(48), f(52), i(56), n(w(d + 60)), i(64),
                      n(w(d + 68)), i(72), n(w(d + 76))))
        self.emit("  cd nev %d ev %s bv %s nlv %d lv %s" % (
            i(80), n(w(d + 84)), n(w(d + 88)), i(92), n(w(d + 96))))
        self.emit("  cd spring %s %s %s %s %s look %s %s %s" % (
            f(100), f(104), f(108), f(112), f(116), f(120), f(124), f(128)))
        self.emit("  cd enter %s %s leave %s %s set %d wipe %s %d shake %d"
                  % (f(132), f(136), f(140), f(144), i(148), f(152), i(156),
                     i(160)))
        for k in range(3):
            self.dump_v("eyev", k, PLAYER0 + P_EYE + 16 * k)
        for k in range(3):
            self.dump_v("bankv", k, PLAYER0 + P_BANK + 16 * k)
        for k in range(32):
            self.dump_v("fovt", k, FOV + 16 * k)

    # ---- the world -------------------------------------------------------

    def reset(self):
        e = self.e
        self.pool = POOL
        self.allocs = []
        self.nmovers = 0
        self.nsamples = 0
        self.cb = None
        self.topo_at = None
        self.nis = 0
        self.replay_demo = 0
        self.find_route = 1
        self.violates = 0
        self.freeze_dur = fb(2.0)
        self.preview_dur = fb(3.0)
        self.cat_volume = fb(1.0)
        self.tpc_ratio = fb(0.5)
        self.elevation = fb(0.0)

        e.put32(G_RC, RC)
        e.put32(RC, 3)
        e.put32(G_RACE, RACE)
        e.put32(RACE, 4)
        e.put32(TRACK_DIRECTION, 0)
        e.mem[JUMP_CAMS] = 1
        e.mem[ZONE_CAMS] = 1
        e.put32(G_NUM_PLAYERS, 1)
        e.put32(G_PLAYERS, PLAYER0)
        e.put32(G_PLAYERS + 4, PLAYER1)
        e.put32(G_SOUND_ENABLED, 1)
        e.put32(G_WORLD_TIMER, 100000)
        e.put32(G_REAL_TIMER, 200000)
        e.put32(G_ELAPSED, fb(f32(0.0333)))
        e.put32(G_TWEAKER, 0)
        e.put32(G_WORLD, WORLD)
        e.put32(G_THE_SOUND, SOUND)
        e.put32(G_SAMPLE_POOL, SAMPLE_POOL)
        e.put32(VTABLE + 8, 0)
        e.put32(VTABLE + 12, DELETE_FN)

        p = PLAYER0
        self.fill(p, PLAYER_SIZE)
        self.fill(PLAYER1, PLAYER_SIZE)
        e.put32(p + P_CAR, CAR)
        e.put32(p + P_NUMBER, 1)
        e.put32(p + P_VIEW, 3)
        e.put32(p + P_ZONE, 0)
        e.put32(p + P_ZONE_PREV, 0)
        for i in range(8):
            e.put32(p + P_TIMERS + 4 * i, 0)
        e.put32(p + P_IGNORE_POV, 0)
        e.put32(p + P_SAMPLE, 0)
        e.put32(p + P_MUFFLE, 0)
        e.put32(p + P_MUFFLE_VOLUME, 0)
        e.put32(p + P_MOVER, 0)
        for off in (216, 220, 224):
            e.put32(p + off, 0)
        e.put32(p + P_WRONG_WAY, 0)
        e.put32(p + P_CD, CD)
        e.put32(p + P_FOV, FOV)
        e.put32(p + P_JUMP_ROUTE, PR)
        e.put32(PLAYER1 + P_ZONE, 0)

        self.fill(CAR, 2200)
        self.fill(CD, 168)
        self.fill(FOV, 512)
        self.fill(PR, 24)
        self.fill(PTS, 24 * NPOINTS)
        self.fill(RPTS, 112 * NPOINTS)
        e.put32(PR, PTS)
        e.put32(PR + 4, 0)

    # ---- the ops ---------------------------------------------------------

    def call(self, fn, *args):
        return self.e.call(fn, *args, limit=2000000)

    def op(self, t):
        e = self.e
        c = t[0]
        p = PLAYER0
        if c == "rc":
            e.put32(RC, int(t[1]))
        elif c == "rd":
            self.replay_demo = int(t[1])
        elif c == "st":
            e.put32(RACE, int(t[1]))
        elif c == "nis":
            self.nis = int(t[1])
        elif c == "tw":
            e.put32(G_TWEAKER, int(t[1]))
        elif c == "wt":
            e.put32(G_WORLD_TIMER, int(t[1], 16))
        elif c == "rt":
            e.put32(G_REAL_TIMER, int(t[1], 16))
        elif c == "we":
            self.put_f(G_ELAPSED, t[1])
        elif c == "se":
            e.put32(G_SOUND_ENABLED, int(t[1]))
        elif c == "cv":
            self.cat_volume = int(t[1], 16)
        elif c == "jc":
            e.mem[JUMP_CAMS] = int(t[1]) & 0xff
        elif c == "zc":
            e.mem[ZONE_CAMS] = int(t[1]) & 0xff
        elif c == "np":
            e.put32(G_NUM_PLAYERS, int(t[1]))
        elif c == "ww":
            e.put32(p + P_WRONG_WAY, int(t[1]))
        elif c == "fr":
            self.find_route = int(t[1])
        elif c == "vt":
            self.violates = int(t[1])
        elif c == "fd":
            self.freeze_dur = int(t[1], 16)
        elif c == "pd":
            self.preview_dur = int(t[1], 16)
        elif c == "tm":
            e.put32(p + P_TIMERS + 4 * int(t[1]), int(t[2], 16))
        elif c == "zn":
            e.put32(p + P_ZONE, int(t[1]))
        elif c == "sm":
            e.put32(p + P_SAMPLE, self.new_sample() if int(t[1]) else 0)
        elif c == "dir":
            e.put32(TRACK_DIRECTION, int(t[1]))
        elif c == "car":
            for i, off in enumerate((C_POS, C_POS + 4, C_POS + 8, C_VEL,
                                     C_VEL + 4, C_VEL + 8, C_RATIO)):
                self.put_f(CAR + off, t[1 + i])
        elif c == "rp":
            q = RPTS + 112 * int(t[1])
            for i, off in enumerate((0, 4, 8, 12, 16, 24, 28, 32, 36)):
                self.put_f(q + off, t[2 + i])
        elif c == "pp":
            e.put32(PR + 4, int(t[1]))
            for i in range(NPOINTS):
                e.put32(PTS + 24 * i + 4, RPTS + 112 * i)
        elif c == "tr":
            self.tpc_ratio = int(t[1], 16)
        elif c == "el":
            self.elevation = int(t[1], 16)
        elif c == "ey":
            a = p + P_EYE + 16 * int(t[1])
            for i in range(3):
                self.put_f(a + 4 * i, t[2 + i])
        elif c == "eh":
            self.put_f(CD + 136, t[1])
        elif c == "Z":
            got = self.call(REQUEST_ZONE, p, *(int(x) for x in t[1:5]))
            self.emit("  -> %d" % got)
            self.dump_player()
        elif c == "C":
            self.call(CLEAR_ZONE, p, int(t[1]))
            self.dump_player()
        elif c == "S":
            self.call(CLEAR_ZONE_SOUND, p)
            self.dump_player()
        elif c == "X":
            if self.cb is None:
                self.emit("  nofire")
                return
            cb, param = self.cb
            self.emit("  fire %s %s" % (self.cb_name(cb), self.name(param)))
            self.call(cb, param)
            self.dump_player()
        elif c == "J":
            second = int(t[1])
            for off in (P_MOVER, 216, 220, 224):
                e.put32(p + off, 0)
            stub = e.stubs.pop(CHANGE_MOVER)
            try:
                self.call(CHANGE_MOVER, p, 16 if second else 15, 0)
            finally:
                e.stubs[CHANGE_MOVER] = stub
            self.emit("  jumper -> %s" % self.name(self.w(p + P_MOVER)))
            self.dump_jumper()
        else:
            raise SystemExit("bad op %r" % (t,))

    def run(self, scenarios):
        for i, sc in enumerate(scenarios):
            self.emit("B %d" % i)
            self.reset()
            for ln in sc:
                self.emit("> " + ln[:60])
                self.op(ln.split())
        return self.out


# ================================================================ the build


# The line the mutations start at, spelt so that this one does not match.
MUTATIONS_HEADER = "# " + "=" * 60 + " the mutations" + NL


def model_cached(sc):
    """Model().run(sc), or its last transcript when nothing it reads has
    changed (tools/mutpar.py)."""
    return mutpar.model_cached(sc, lambda s: Model().run(s),
                               cut=MUTATIONS_HEADER)


def build_harness(tmp, name="playerzone_test"):
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


def M(name, before, after, rel=PZC):
    return (name, rel, before, after)


MUTATIONS = [
    # Type 15.
    M("j-n-last", "n = r->nPoints - 1;", "n = r->nPoints - 2;"),
    M("j-n-five", "if (5 <= n)", "if (6 <= n)"),
    M("j-n-three", "n = r->nPoints - 3;", "n = r->nPoints - 2;"),
    M("j-iso", "cd->IsFOVIso = 0;", "cd->IsFOVIso = 1;"),
    M("j-type", "cd->Type = 0;", "cd->Type = 1;"),
    M("j-name", "cd->Name = NULL;", "cd->Name = (char *)cd;"),
    M("j-target-across", "&target, 0.0f," + NL
      + "                                        0.0f);",
      "&target, 0.0f," + NL
      + "                                        1.0f);"),
    M("j-progress", "return ratio * 100.0f * 0.01f;", "return ratio;"),
    M("j-progress-rev", "return (100.0f - ratio * 100.0f) * 0.01f;",
      "return 1.0f - ratio;"),
    M("j-min-area", "cd->MinAreaPercent = pct;" + NL
      + "    cd->MinPercent = pct;" + NL + "    if",
      "cd->MinPercent = pct;" + NL + "    if"),
    M("j-min", "cd->MinAreaPercent = pct;" + NL
      + "    cd->MinPercent = pct;" + NL + "    if",
      "cd->MinAreaPercent = pct;" + NL + "    if"),
    M("j-max-dir", "pct = 1.0f - tpc.RatioAroundTrack;",
      "pct = tpc.RatioAroundTrack;"),
    M("j-max-fwd", "pct = tpc.RatioAroundTrack;" + NL + "    else",
      "pct = 1.0f - tpc.RatioAroundTrack;" + NL + "    else"),
    M("j-max-area", "cd->MaxAreaPercent = pct;", "cd->MaxAreaPercent = 0.0f;"),
    M("j-max", "cd->MaxPercent = pct;", "cd->MaxPercent = 0.0f;"),
    M("j-lock", "cd->LockEyeSpeedToCar = 1;", "cd->LockEyeSpeedToCar = 0;"),
    M("j-fovtable", "cd->FOVTable = p->FOVtable;", "cd->FOVTable = NULL;"),
    M("j-near", "cd->NearClip = 0.5f;", "cd->NearClip = 0.25f;"),
    M("j-far", "cd->FarClip = 10000.0f;", "cd->FarClip = 1000.0f;"),
    M("j-eye-speed", "cd->EyeSplineSpeed = 0.0f;",
      "cd->EyeSplineSpeed = 1.0f;"),
    M("j-look-speed", "cd->LookSplineSpeed = 0.0f;",
      "cd->LookSplineSpeed = 1.0f;"),
    M("j-fov-speed", "cd->FOVSplineSpeed = 0.0f;",
      "cd->FOVSplineSpeed = 1.0f;"),
    M("j-lock-look", "cd->LockLookSpeedToCar = 0;",
      "cd->LockLookSpeedToCar = 1;"),
    M("j-backwards", "cd->Backwards = 0;", "cd->Backwards = 1;"),
    M("j-fov-20", "p->FOVtable[i].x = 20.0f;", "p->FOVtable[i].x = 21.0f;"),
    M("j-fov-count", "for (i = 0; i < 32; i++) {" + NL
      + "        p->FOVtable[i].x = 20.0f;",
      "for (i = 0; i < 31; i++) {" + NL
      + "        p->FOVtable[i].x = 20.0f;"),
    M("j-fov-y", "p->FOVtable[i].x = 20.0f;" + NL
      + "        p->FOVtable[i].y = 0.0f;",
      "p->FOVtable[i].x = 20.0f;" + NL
      + "        p->FOVtable[i].y = 1.0f;"),
    M("j-fov-z", "p->FOVtable[i].y = 0.0f;" + NL
      + "        p->FOVtable[i].z = 0.0f;" + NL
      + "        p->FOVtable[i].pad = 0.0f;" + NL
      + "    }" + NL + "    cd->BankVerts",
      "p->FOVtable[i].y = 0.0f;" + NL
      + "        p->FOVtable[i].z = 1.0f;" + NL
      + "        p->FOVtable[i].pad = 0.0f;" + NL
      + "    }" + NL + "    cd->BankVerts"),
    M("j-bankverts", "cd->BankVerts = p->BankVerts;",
      "cd->BankVerts = NULL;"),
    M("j-num-eye", "cd->NumEyeVerts = 2;", "cd->NumEyeVerts = 3;"),
    M("j-eyeverts", "cd->EyeVerts = p->EyeVerts;", "cd->EyeVerts = NULL;"),
    M("j-bank-count", "for (i = 0; i < 3; i++) {" + NL
      + "        p->BankVerts[i].x = 0.0f;",
      "for (i = 0; i < 2; i++) {" + NL
      + "        p->BankVerts[i].x = 0.0f;"),
    M("j-bank-x", "p->BankVerts[i].x = 0.0f;", "p->BankVerts[i].x = 1.0f;"),
    M("j-bank-y", "p->BankVerts[i].y = 0.0f;", "p->BankVerts[i].y = 1.0f;"),
    M("j-bank-z", "p->BankVerts[i].z = 0.0f;", "p->BankVerts[i].z = 1.0f;"),
    M("j-spring-x", "cd->SpringXVel = 0.0f;", "cd->SpringXVel = 1.0f;"),
    M("j-enter-vert", "cd->EnterVertComp = 0.2f;",
      "cd->EnterVertComp = 0.3f;"),
    M("j-spring-y", "cd->SpringYVel = 0.0f;", "cd->SpringYVel = 1.0f;"),
    M("j-spring-z", "cd->SpringZVel = 0.0f;", "cd->SpringZVel = 1.0f;"),
    M("j-damp", "cd->SpringDamp = 0.0f;", "cd->SpringDamp = 1.0f;"),
    M("j-const", "cd->SpringConst = 0.0f;", "cd->SpringConst = 1.0f;"),
    M("j-look-x", "cd->LookOffsetX = 0.0f;", "cd->LookOffsetX = 1.0f;"),
    M("j-look-y", "cd->LookOffsetY = 0.0f;", "cd->LookOffsetY = 1.0f;"),
    M("j-look-z", "cd->LookOffsetZ = 0.0f;", "cd->LookOffsetZ = 1.0f;"),
    M("j-leave-vert", "cd->LeaveVertComp = 0.0f;",
      "cd->LeaveVertComp = 1.0f;"),
    M("j-leave-horiz", "cd->LeaveHorizComp = 0.0f;",
      "cd->LeaveHorizComp = 1.0f;"),
    M("j-wipe", "cd->WipeDistance = 0.0f;", "cd->WipeDistance = 1.0f;"),
    M("j-wipe-auto", "cd->WipeAutoDisable = 0;", "cd->WipeAutoDisable = 1;"),
    M("j-num-look", "cd->NumLookVerts = 0;", "cd->NumLookVerts = 1;"),
    M("j-look-verts", "cd->LookVerts = NULL;",
      "cd->LookVerts = p->EyeVerts;"),
    M("j-leave-set", "cd->IsLeaveSet = 0;", "cd->IsLeaveSet = 1;"),
    M("j-right-width", "pt->pPoint->RightWidth);" + NL
      + "    preview_route_point_get_position_at(pt, &left",
      "pt->pPoint->LeftWidth);" + NL
      + "    preview_route_point_get_position_at(pt, &left"),
    M("j-left-sign", "-pt->pPoint->LeftWidth);" + NL
      + "    pt = &r->pPoints[2];",
      "pt->pPoint->LeftWidth);" + NL + "    pt = &r->pPoints[2];"),
    M("j-other-point", "pt = &r->pPoints[2];", "pt = &r->pPoints[1];"),
    M("j-dot-lt", "< dot_velocity(&right, &eye, &car->State.Velocity)) {",
      "<= dot_velocity(&right, &eye, &car->State.Velocity)) {"),
    M("j-dot-order", "return (x * v->x + y * v->y) + z * v->z;",
      "return x * v->x + (y * v->y + z * v->z);"),
    M("j-dot-z", "return (x * v->x + y * v->y) + z * v->z;",
      "return x * v->x + y * v->y;"),
    M("j-dot-sub", "float x = a->x - b->x,", "float x = b->x - a->x,"),
    M("j-eye-left", "eye = left;", "eye = right;"),
    M("j-other-left", "&other, 0.0f," + NL
      + "                                            pt->pPoint->RightWidth);",
      "&other, 0.0f," + NL
      + "                                            pt->pPoint->LeftWidth);"),
    M("j-horiz-left", "cd->EnterHorizComp = 0.4f;",
      "cd->EnterHorizComp = 0.3f;"),
    M("j-eye-right", "eye = right;", "eye = left;"),
    M("j-other-right", "-pt->pPoint->LeftWidth);" + NL
      + "        cd->EnterHorizComp = -0.4f;",
      "pt->pPoint->LeftWidth);" + NL
      + "        cd->EnterHorizComp = -0.4f;"),
    M("j-horiz-right", "cd->EnterHorizComp = -0.4f;",
      "cd->EnterHorizComp = 0.4f;"),
    M("j-eye-up", "eye.z = eye.z + 1.0f;", "eye.z = eye.z + 2.0f;"),
    M("j-other-up", "other.z = other.z + 1.0f;", "other.z = other.z + 0.5f;"),
    M("j-ground-lt", "if (eye.z < elev)", "if (eye.z <= elev)"),
    M("j-ground-up", "eye.z = elev + 1.0f;", "eye.z = elev + 0.5f;"),
    M("j-eye-0", "p->EyeVerts[0] = eye;", "p->EyeVerts[0] = other;"),
    M("j-eye-1", "p->EyeVerts[1] = eye;", "p->EyeVerts[1] = other;"),
    M("j-eye-2", "p->EyeVerts[2] = other;", "p->EyeVerts[2] = eye;"),
    M("j-focus", "m = jump_cam_mover(p, car, 0);", "m = jump_cam_mover(p, car, 1);"),
    M("j-topo-order", "m = jump_cam_mover(p, car, 0);" + NL
      + "    topology_destroy(&tc);",
      "topology_destroy(&tc);" + NL + "    m = jump_cam_mover(p, car, 0);"),
    M("j-cvs", "shake.NumCVs = 2;", "shake.NumCVs = 3;"),
    M("j-alloc-line", "\"TrackCarCameraMover\"," + NL + "                  0, 16);",
      "\"TrackCarCameraMover\"," + NL + "                  1, 16);"),
    M("j-view", "p->ViewID, car, p->myCD", "p->PlayerNumber, car, p->myCD"),

    # Type 16.
    M("k-min-area", "cd->MinAreaPercent = pct;" + NL
      + "    cd->MinPercent = pct;" + NL + "    z =",
      "cd->MinPercent = pct;" + NL + "    z ="),
    M("k-min", "cd->MinAreaPercent = pct;" + NL
      + "    cd->MinPercent = pct;" + NL + "    z =",
      "cd->MinAreaPercent = pct;" + NL + "    z ="),
    M("k-car-z", "if (top->z < z)", "if (z < top->z)"),
    M("k-ground-lt", "if (top->z < elev)", "if (top->z <= elev)"),
    M("k-ground-up", "top->z = elev + 1.0f;", "top->z = elev + 2.0f;"),
    M("k-eye-0", "p->EyeVerts[0] = *top;", ""),
    M("k-eye-1", "p->EyeVerts[1] = *top;", ""),
    M("k-horiz", "cd->EnterHorizComp = -cd->EnterHorizComp;",
      "cd->EnterHorizComp = cd->EnterHorizComp;"),
    M("k-fov-step", "20.0f - (float)i * 0.25f;", "20.0f - (float)i * 0.5f;"),
    M("k-fov-count", "for (i = 0; i < 32; i++) {" + NL
      + "        p->FOVtable[i].x = 20.0f -",
      "for (i = 0; i < 31; i++) {" + NL
      + "        p->FOVtable[i].x = 20.0f -"),
    M("k-fov-y", "* 0.25f;" + NL + "        p->FOVtable[i].y = 0.0f;",
      "* 0.25f;" + NL + "        p->FOVtable[i].y = 1.0f;"),
    M("k-focus", "m = jump_cam_mover(p, car, 1);", "m = jump_cam_mover(p, car, 0);"),
    M("k-second", "if (second)", "if (!second)"),

    # RequestZone's noes.
    M("z-nis", "if (player_is_nis_playing(p))", "if (player_is_nis_playing(p) && 0)"),
    M("z-ai-demo", "== RCSTATE_AI_DEMO_MODE)", "== RCSTATE_PAUSE)"),
    M("z-timer-slot", "t = &p->tAutoZoneTimers[force ? 0 : zone];",
      "t = &p->tAutoZoneTimers[zone];"),
    M("z-timer-valid", "if (timer_is_valid(t)) {", "if (1) {"),
    M("z-repeat-lt", "since(t) < ZONE_REPEAT)", "since(t) <= ZONE_REPEAT)"),
    M("z-repeat", "#define ZONE_REPEAT      5.0f", "#define ZONE_REPEAT      4.0f"),
    M("z-repeat-force", "if (!force && since(t) < ZONE_REPEAT)",
      "if (since(t) < ZONE_REPEAT)"),
    M("z-gap-lt", "since(t) < ZONE_FORCE_GAP)", "since(t) <= ZONE_FORCE_GAP)"),
    M("z-gap", "#define ZONE_FORCE_GAP   0.1f", "#define ZONE_FORCE_GAP   0.2f"),
    M("z-gap-force", "if (force && since(t) < ZONE_FORCE_GAP)",
      "if (since(t) < ZONE_FORCE_GAP)"),
    M("z-tick", "#define ZONE_TICK        0.00025f",
      "#define ZONE_TICK        0.0002f"),
    M("z-since-signed", "(float)(int32_t)((uint32_t)WorldTimer - t->PackedTime)",
      "(float)((uint32_t)WorldTimer - t->PackedTime)"),
    M("z-stage", "!= RACE_STAGE_RACING)", "!= RACE_STAGE_COUNTDOWN)"),
    M("z-count", "(uint32_t)zone >= PLAYER_ZONE_COUNT",
      "(uint32_t)zone > PLAYER_ZONE_COUNT"),
    M("z-count-signed", "(uint32_t)zone >= PLAYER_ZONE_COUNT",
      "zone >= PLAYER_ZONE_COUNT"),
    M("z-two", "PlayerNumPlayers == 2)", "PlayerNumPlayers == 3)"),
    M("z-jump-cams", "(uint32_t)(zone - PLAYER_ZONE_JUMP_CAM) < 2",
      "(uint32_t)(zone - PLAYER_ZONE_JUMP_CAM) < 1"),
    M("z-zone-cams", "(uint32_t)(zone - PLAYER_ZONE_FREEZE) < 5",
      "(uint32_t)(zone - PLAYER_ZONE_FREEZE) < 4"),
    M("z-zone-cams-0", "(uint32_t)(zone - PLAYER_ZONE_FREEZE) < 5",
      "(uint32_t)zone < 6"),
    M("z-cleared", "if (PlayerZoneClearedByRequest[p->nZoneCurrent])",
      "if (0)"),
    M("z-cleared-sound", "player_clear_zone(p, 0);", "player_clear_zone(p, 1);"),
    M("z-cleared-table", "0, 1, 1, 0, 0, 0, 0, 0,", "0, 1, 0, 0, 0, 0, 0, 0,"),
    M("z-blocks-table", "0, 0, 0, 1, 1, 1, 1, 1,", "0, 0, 0, 1, 1, 1, 1, 0,"),
    M("z-blocks-loop", "for (i = 0; i < PlayerNumPlayers; i++)",
      "for (i = 0; i < 1; i++)"),
    M("z-pov", "p->tIgnoreNextPovChange.PackedTime = (uint32_t)RealTimer;",
      "p->tIgnoreNextPovChange.PackedTime = (uint32_t)WorldTimer;"),
    M("z-stamp-force", "if (!force)" + NL
      + "        p->tAutoZoneTimers[zone].PackedTime",
      "if (1)" + NL + "        p->tAutoZoneTimers[zone].PackedTime"),
    M("z-stamp", "p->tAutoZoneTimers[zone].PackedTime = (uint32_t)WorldTimer;",
      "p->tAutoZoneTimers[zone].PackedTime = (uint32_t)RealTimer;"),
    M("z-hud", "    player_clear_hud_animations(p);" + NL, ""),

    # The freeze.
    M("z1-replay", "if (in_replay())" + NL + "            return 0;" + NL
      + "        player_change_camera_mover(p, CM_ZONE_FREEZE, 1);",
      "player_change_camera_mover(p, CM_ZONE_FREEZE, 1);"),
    M("z1-keep", "CM_ZONE_FREEZE, 1);", "CM_ZONE_FREEZE, 0);"),
    M("z1-elapsed", "gZoneFreezeDurationFn() - WorldTimeElapsed",
      "gZoneFreezeDurationFn()"),
    M("z1-break", "player_clear_zone_callback, param);" + NL
      + "        break;" + NL + NL + "    case PLAYER_ZONE_PREVIEW:",
      "player_clear_zone_callback, param);" + NL + NL
      + "    case PLAYER_ZONE_PREVIEW:"),

    # The preview.
    M("z2-replay", "if (in_replay())" + NL + "            return 0;" + NL
      + "        if (p->bWrongWay)", "if (p->bWrongWay)"),
    M("z2-wrong-way", "if (p->bWrongWay) {", "if (0) {"),
    M("z2-wrong-sound", "if (p->bWrongWay) {" + NL
      + "            play_menu_wrong();", "if (p->bWrongWay) {"),
    M("z2-route-car", "p->pRoute = gZonePreviewFindRouteFn(p->MyCar);",
      "p->pRoute = gZonePreviewFindRouteFn(NULL);"),
    M("z2-route-store", "p->pRoute = gZonePreviewFindRouteFn(p->MyCar);" + NL
      + "        if (p->pRoute == NULL) {",
      "if (gZonePreviewFindRouteFn(p->MyCar) == NULL) {"),
    M("z2-no-route", "if (p->pRoute == NULL) {", "if (0) {"),
    M("z2-no-route-sound", "if (p->pRoute == NULL) {" + NL
      + "            play_menu_wrong();", "if (p->pRoute == NULL) {"),
    M("z2-keep", "CM_ZONE_PREVIEW, 1);", "CM_ZONE_PREVIEW, 0);"),
    M("z2-mover", "m = p->pCameraMover;", "m = NULL;"),
    M("z2-violates-sound", "if (gZonePreviewViolatesTopologyFn(m)) {" + NL
      + "            play_menu_wrong();",
      "if (gZonePreviewViolatesTopologyFn(m)) {"),
    M("z2-violates-restore", "            player_restore_camera_mover(p);" + NL
      + "            return 0;", "            return 0;"),
    M("z2-volume", "volume = 0.0f;", "volume = 0.5f;"),
    M("z2-elapsed", "gZonePreviewDurationFn(m) - WorldTimeElapsed",
      "gZonePreviewDurationFn(m)"),
    M("z2-name", "name = \"PreviewZone\";", "name = \"Wind\";"),
    M("w-sound-enabled", "if (!SoundEnabled || gCommonRegionSampleFn == NULL)",
      "if (gCommonRegionSampleFn == NULL)"),
    M("w-name", "gCommonRegionSampleFn(\"MenuWrong\");",
      "gCommonRegionSampleFn(\"MenuRight\");"),
    M("w-volume", "gSamplePlayFn(s, 1.0f, 0.0f, 0.0f);",
      "gSamplePlayFn(s, 0.5f, 0.0f, 0.0f);"),

    # The time scales.
    M("z3-scale", "#define ZONE_SLOMO_SCALE 0.333f",
      "#define ZONE_SLOMO_SCALE 0.33f"),
    M("z3-time", "ZONE_SLOMO_SCALE, 8.0f,", "ZONE_SLOMO_SCALE, 7.0f,"),
    M("z3-name", "name = \"SlomoZone\";" + NL + "        break;" + NL + NL
      + "    case PLAYER_ZONE_SLOMO_SHORT:",
      "break;" + NL + NL + "    case PLAYER_ZONE_SLOMO_SHORT:"),
    M("z4-time", "ZONE_SLOMO_SCALE, 2.0f,", "ZONE_SLOMO_SCALE, 3.0f,"),
    M("z4-name", "name = \"SlomoZone\";" + NL + "        break;" + NL + NL
      + "    case PLAYER_ZONE_FAST:",
      "break;" + NL + NL + "    case PLAYER_ZONE_FAST:"),
    M("z5-scale", "world_set_time_scale(pCurrentWorld, 2.0f, 4.0f,",
      "world_set_time_scale(pCurrentWorld, 1.5f, 4.0f,"),
    M("z5-time", "world_set_time_scale(pCurrentWorld, 2.0f, 4.0f,",
      "world_set_time_scale(pCurrentWorld, 2.0f, 5.0f,"),
    M("z-name-default", "const char *name = \"Wind\";",
      "const char *name = \"SlomoZone\";"),
    M("z6-scale", "#define ZONE_JUMP_SCALE  0.4f", "#define ZONE_JUMP_SCALE  0.5f"),
    M("z6-pitch", "#define ZONE_JUMP_PITCH  0.9f", "#define ZONE_JUMP_PITCH  0.8f"),
    M("z6-time", "case PLAYER_ZONE_JUMP_CAM:" + NL
      + "        world_set_time_scale(pCurrentWorld, ZONE_JUMP_SCALE, 8.0f,",
      "case PLAYER_ZONE_JUMP_CAM:" + NL
      + "        world_set_time_scale(pCurrentWorld, ZONE_JUMP_SCALE, 7.0f,"),
    M("z6-replay", "if (!in_replay())" + NL
      + "            player_change_camera_mover(p, CM_ZONE_JUMPER, 1);",
      "if (1)" + NL
      + "            player_change_camera_mover(p, CM_ZONE_JUMPER, 1);"),
    M("z6-keep", "CM_ZONE_JUMPER, 1);", "CM_ZONE_JUMPER, 0);"),
    M("z6-cleanup", "        player_clean_up_jump_cam(p);" + NL
      + "        break;", "        break;"),
    M("z6-pitch-set", "pitch = ZONE_JUMP_PITCH;" + NL
      + "        name = \"SlomoZone\";" + NL + "        if (!in_replay())" + NL
      + "            player_change_camera_mover(p, CM_ZONE_JUMPER, 1);",
      "name = \"SlomoZone\";" + NL + "        if (!in_replay())" + NL
      + "            player_change_camera_mover(p, CM_ZONE_JUMPER, 1);"),
    M("z7-time", "case PLAYER_ZONE_AFTER_JUMP:" + NL
      + "        world_set_time_scale(pCurrentWorld, ZONE_JUMP_SCALE, 8.0f,",
      "case PLAYER_ZONE_AFTER_JUMP:" + NL
      + "        world_set_time_scale(pCurrentWorld, ZONE_JUMP_SCALE, 7.0f,"),
    M("z7-replay", "if (!in_replay())" + NL
      + "            player_change_camera_mover(p, CM_ZONE_JUMPER2, 1);",
      "if (1)" + NL
      + "            player_change_camera_mover(p, CM_ZONE_JUMPER2, 1);"),
    M("z7-keep", "CM_ZONE_JUMPER2, 1);", "CM_ZONE_JUMPER2, 0);"),
    M("z7-pitch-set", "pitch = ZONE_JUMP_PITCH;" + NL
      + "        name = \"SlomoZone\";" + NL + "        if (!in_replay())" + NL
      + "            player_change_camera_mover(p, CM_ZONE_JUMPER2, 1);",
      "name = \"SlomoZone\";" + NL + "        if (!in_replay())" + NL
      + "            player_change_camera_mover(p, CM_ZONE_JUMPER2, 1);"),
    M("z7-name", "pitch = ZONE_JUMP_PITCH;" + NL
      + "        name = \"SlomoZone\";" + NL + "        if (!in_replay())" + NL
      + "            player_change_camera_mover(p, CM_ZONE_JUMPER2, 1);",
      "pitch = ZONE_JUMP_PITCH;" + NL + "        if (!in_replay())" + NL
      + "            player_change_camera_mover(p, CM_ZONE_JUMPER2, 1);"),

    # In a replay.
    M("r-instant", "return s == RCSTATE_INSTANT_REPLAY || s == RCSTATE_POSTRACE",
      "return s == RCSTATE_POSTRACE"),
    M("r-postrace", "s == RCSTATE_INSTANT_REPLAY || s == RCSTATE_POSTRACE",
      "s == RCSTATE_INSTANT_REPLAY"),
    M("r-auto", "|| s == RCSTATE_AUTO_REPLAY" + NL, NL),
    M("r-demo", "|| racecoordinator_is_replay_demo_mode(pRaceCoordinator);",
      ";"),

    # The tail.
    M("t-blur-view", "gRadialBlurOnFn(p->PlayerNumber);",
      "gRadialBlurOnFn(p->ViewID);"),
    M("t-zone", "p->nZoneCurrent = zone;", "p->nZoneCurrent = zone & 3;"),
    M("t-muffle", "p->bZoneMuffleSound = muffle;", "p->bZoneMuffleSound = 1;"),
    M("t-muffle-volume", "p->fZoneMuffleVolume = muffle ? 0.0f : 1.0f;",
      "p->fZoneMuffleVolume = muffle ? 1.0f : 0.0f;"),
    M("t-sound-enabled", "if (SoundEnabled && sound && gSoundGetCategoryVolumeFn",
      "if (sound && gSoundGetCategoryVolumeFn"),
    M("t-sound", "if (SoundEnabled && sound && gSoundGetCategoryVolumeFn",
      "if (SoundEnabled && gSoundGetCategoryVolumeFn"),
    M("t-volume-lt", "&& 0.0f < gSoundGetCategoryVolumeFn(0)) {",
      "&& 0.0f <= gSoundGetCategoryVolumeFn(0)) {"),
    M("t-category", "&& 0.0f < gSoundGetCategoryVolumeFn(0)) {",
      "&& 0.0f < gSoundGetCategoryVolumeFn(1)) {"),
    M("t-delete", "if (p->pZoneSample != NULL)" + NL
      + "            delete_zone_sample(p);" + NL, ""),
    M("t-from", "gSampleInitializeFn(p->pZoneSample, from);",
      "gSampleInitializeFn(p->pZoneSample, NULL);"),
    M("t-set-category", "gSampleSetCategoryFn(p->pZoneSample, 0xffffffffu);",
      "gSampleSetCategoryFn(p->pZoneSample, 0u);"),
    M("t-play-volume", "gSamplePlayFn(p->pZoneSample, volume, 0.0f, pitch - 1.0f);",
      "gSamplePlayFn(p->pZoneSample, 1.0f, 0.0f, pitch - 1.0f);"),
    M("t-play-pan", "gSamplePlayFn(p->pZoneSample, volume, 0.0f, pitch - 1.0f);",
      "gSamplePlayFn(p->pZoneSample, volume, 1.0f, pitch - 1.0f);"),
    M("t-play-pitch", "gSamplePlayFn(p->pZoneSample, volume, 0.0f, pitch - 1.0f);",
      "gSamplePlayFn(p->pZoneSample, volume, 0.0f, pitch);"),
    M("t-return", "            gSamplePlayFn(p->pZoneSample, volume, 0.0f, pitch - 1.0f);"
      + NL + "    }" + NL + "    return 1;",
      "            gSamplePlayFn(p->pZoneSample, volume, 0.0f, pitch - 1.0f);"
      + NL + "    }" + NL + "    return 2;"),
    M("t-param", "int32_t param = (int32_t)(intptr_t)p;",
      "int32_t param = (int32_t)(intptr_t)p->MyCar;"),

    # ClearZone.
    M("c-none", "if (p->nZoneCurrent == 0)" + NL + "        return;", ""),
    M("c-blur-view", "gRadialBlurOffFn(p->PlayerNumber);",
      "gRadialBlurOffFn(p->ViewID);"),
    M("c-low", "if (0 < zone && zone < 3) {", "if (zone < 3) {"),
    M("c-low-3", "if (0 < zone && zone < 3) {", "if (0 < zone && zone < 2) {"),
    M("c-tweaker", "if (TweakerPauseWorld == 0)", "if (1)"),
    M("c-stamp", "p->tAutoZoneTimers[0].PackedTime = (uint32_t)WorldTimer;",
      "p->tAutoZoneTimers[0].PackedTime = (uint32_t)RealTimer;"),
    M("c-low-replay", "if (!in_replay())" + NL
      + "            player_restore_camera_mover(p);" + NL
      + "    } else if",
      "player_restore_camera_mover(p);" + NL + "    } else if"),
    M("c-jump-low", "} else if (PLAYER_ZONE_JUMP_CAM <= zone && zone < PLAYER_ZONE_COUNT)",
      "} else if (PLAYER_ZONE_JUMP_CAM < zone && zone < PLAYER_ZONE_COUNT)"),
    M("c-jump-high", "} else if (PLAYER_ZONE_JUMP_CAM <= zone && zone < PLAYER_ZONE_COUNT)",
      "} else if (PLAYER_ZONE_JUMP_CAM <= zone)"),
    M("c-jump-replay", "if (!in_replay())" + NL
      + "            player_restore_camera_mover(p);" + NL + "    }" + NL
      + "    world_reset_time_scale",
      "player_restore_camera_mover(p);" + NL + "    }" + NL
      + "    world_reset_time_scale"),
    M("c-reset", "    world_reset_time_scale(pCurrentWorld);" + NL, ""),
    M("c-previous", "p->nZonePrevious = p->nZoneCurrent;",
      "p->nZonePrevious = 0;"),
    M("c-current", "p->nZonePrevious = p->nZoneCurrent;" + NL
      + "    p->nZoneCurrent = 0;", "p->nZonePrevious = p->nZoneCurrent;"),
    M("c-muffle", "p->bZoneMuffleSound = 0;", "p->bZoneMuffleSound = 1;"),
    M("c-muffle-volume", "p->fZoneMuffleVolume = 0.0f;",
      "p->fZoneMuffleVolume = 1.0f;"),
    M("c-sound", "if (sound)" + NL + "        player_clear_zone_sound(p);",
      "player_clear_zone_sound(p);"),
    M("c-input", "    player_determine_input_mode(p);" + NL, ""),

    # ClearZoneSound and PlayerClearZone.
    M("s-enabled", "if (SoundEnabled && p->pZoneSample != NULL) {",
      "if (p->pZoneSample != NULL) {"),
    M("s-null", "delete_zone_sample(p);" + NL + "        p->pZoneSample = NULL;",
      "delete_zone_sample(p);"),
    M("cb-sound", "player_clear_zone((struct Player *)(intptr_t)param, 1);",
      "player_clear_zone((struct Player *)(intptr_t)param, 0);"),
]

EQUIVALENT = {
    "z-gap-force": "without force, any time under the 0.1 s gap is under "
                   "the 5 s one too, which has already said no",
}


def mutate_pass(only=None, jobs=None):
    todo = [m for m in MUTATIONS if only is None or m[0] in only]
    if only:
        unknown = set(only) - {m[0] for m in MUTATIONS}
        if unknown:
            print("no such mutation: %s" % ", ".join(sorted(unknown)))
            return 1
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
        todo, SOURCES, "playerzone_test",
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
