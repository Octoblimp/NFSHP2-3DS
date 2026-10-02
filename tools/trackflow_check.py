#!/usr/bin/env python3
"""Cross-check 3DS Files/source/trackflow.c -- the game flow's four track
states and their load callbacks -- and hudtex.c's ChooseLoadableTextures
against the retail image itself, run in mipsemu.

The model is the image. These run as shipped:

    BeginGameFlowLoadingTrackCommon      0x00168db8
    GameFlowLoadingTrackCommonPart1      0x00168ac0
    GameFlowLoadingTrackCommonPart2      0x00168928
    LoadHudTextures                      0x00168c30
    ChooseLoadableTextures               0x001ee3c0
    BeginGameFlowLoadingTrackSpecific    0x001690a0
    GameFlowLoadingTrackSpecificPart1-6  0x00169058 0x00169048 0x00169018
                                         0x00168f98 0x00168f78 0x00168f28
    EndGameFlowLoadingTrackSpecific      0x00169168
    BeginGameFlowUnloadingTrackSpecific  0x00169288
    BeginGameFlowUnloadingTrackCommon    0x00168ea0

and so do RaceParameters::GetDriverInfo, bSPrintf, bStringHash, bStrCmp,
bStrLen, bMemSet and bMemCpy under them. Every other callee is stubbed.
Each stub prints its name, its arguments, and the globals the steps write,
read at the moment of the call:

    ig   InGameFlag                          gp-21424
    dft  eDisableFixUpTables                 gp-24944
    rev  TheTrackPathManager.ReverseTrackDirection   0x0031bc3c
    jr2  WeHaveCheckedIfJR2ServerExists      gp-21764
    rc   pRaceCoordinator                    gp-22216
    sfe  SkipFE                              gp-23220
    fc   FreeMemoryBeforeLoadingTrackCommon  gp-21444
    fs   FreeMemoryBeforeLoadingTrackSpecific  gp-21440
    adf  AnimatedDriverNeedsFixup            gp-21376
    fe   TheCarLoader.InFrontEndFlag         0x00313a40
    rr   TheCarLoader.RoundRobinFlag         0x00313a3c
    want, pend  Desired- and PendingGameFlowState  gp-21416, gp-21412

so a store that moves across a call shows. The harness
(tools/src/trackflow_test.c) links trackflow.c, hudtex.c and
cartypeinfo.c with the same stubs, by name for the callees the port has
and through the seams for the rest, and prints the same lines.

**The loads.** LoadResourceFile, the car loader's BeginLoading,
LoadSoundRegionsInGame and LoadTexturesFromFile queue their callbacks with
their parameters, and the script's D runs the oldest, so a scenario walks
a whole load chain one step at a time. CarLoader::Load answers each car
type's count so far, from a base the script sets, as a signed byte. The
drivers are the script's, in retail's 24-byte DriverInfo; after every step
the transcript holds each one's InstanceIndex and SkinNumber. The cars are
GLOBALB.BUN's own 64 records, and some scenarios change them.

**The seams.** A scenario with null=1 clears every seam on the port's
side, and the model's stubs for those callees go silent: FindResourceFile
finds nothing, bIsAsyncDone is done, bCountFreeMemory counts 0, the
RaceCoordinator is NULL, and LoadSoundRegionsInGame and
LoadTexturesFromFile run their callbacks at once. The callees the port
calls directly still print.

    python tools/trackflow_check.py
    python tools/trackflow_check.py --mutate [--only a,b]
    python tools/trackflow_check.py --dump out/trackflow
"""
import argparse
import os
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import carinfo_check as cic
import hostbuild
import physicscar_check as pcc
import retail_model
from mipsemu import M32, s32

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

HARNESS = "tools/src/trackflow_test.c"
TFC = "3DS Files/source/trackflow.c"
HTC = "3DS Files/source/hudtex.c"
SOURCES = [HARNESS, TFC, HTC] + ["3DS Files/source/" + f for f in (
    "cartypeinfo.c", "langtab.c", "bmath.c", "bmathtab.c")]

HARNESS_TIMEOUT = 60
LIMIT = 20000000

# ================================================================ the image

GP = 0x003358f0
IN_GAME = GP - 21424
HUD_PACK = GP - 21428
JR2 = GP - 21764
FREE_COMMON = GP - 21444
FREE_SPECIFIC = GP - 21440
ANIM_FIXUP = GP - 21376
SKIP_FE = GP - 23220
DISABLE_FIXUP = GP - 24944
RACE_COORD = GP - 22216
DESIRED = GP - 21416
PENDING = GP - 21412
CAR_ARRAY = GP - 20616

RP = 0x0031a898                      # TheRaceParameters
TRACK = RP + 0
TRACK_DIR = RP + 12
AI_DEMO = RP + 24
REPLAY_DEMO = RP + 28
NUM_PLAYERS = RP + 48
UNITS = RP + 749
DRIVERS = RP + 772
NUM_DRIVERS = RP + 776

REVERSE = 0x0031bc3c                 # TheTrackPathManager + 4
# TheDemoDiscManager.bActive, held at 0: the image puts the demo disc's own
# screen up when it is set, and the port has no demo disc.
DEMO_DISC = 0x002effe0
TOPO_TREE = 0x002f9498
DEMO_REPLAY = 0x002f0960             # +0 is ActiveFlag
LANGUAGES = 0x0031c1c8
SLOT_POOLS = 0x0031fd88
EASTER_EGGS = 0x0031d7e8
CAR_LOADER = 0x00313a38

BEGIN_LTC = 0x00168db8
PART1C = 0x00168ac0
PART2C = 0x00168928
LOAD_HUD = 0x00168c30
CHOOSE = 0x001ee3c0
BEGIN_LTS = 0x001690a0
PARTS = (0x00169058, 0x00169048, 0x00169018, 0x00168f98, 0x00168f78,
         0x00168f28)
END = 0x00169168
BEGIN_UTS = 0x00169288
BEGIN_UTC = 0x00168ea0

# Where the model puts the objects a scenario names.
REC_BASE = 0x01000000
REC = 1376
NUM_TYPES = 64
DI_BASE = 0x01100000
DI = 24
MAXDRV = 16
RC0, RC_NEW, HUD = 0x01200000, 0x01200100, 0x01200200
RF_BASE = 0x01210000
MAXRF = 64
FILES = {2: 0x01220000, 3: 0x01221000}
TESTCB = 0x01230000
TEX_BUF = 0x01240000

CB_NAMES = {PART1C: "P1C", PARTS[0]: "P1", PARTS[1]: "P2", PARTS[2]: "P3",
            PARTS[3]: "P4", PARTS[4]: "P5", PARTS[5]: "P6",
            TESTCB: "testcb"}
VCB_NAMES = {PART2C: "P2C"}

STEPS = {"C": BEGIN_LTC, "S": BEGIN_LTS, "E": END, "U": BEGIN_UTS,
         "V": BEGIN_UTC, "p": PART1C, "q": PART2C, "1": PARTS[0],
         "2": PARTS[1], "3": PARTS[2], "4": PARTS[3], "5": PARTS[4],
         "6": PARTS[5]}

# (address, name, kind, is_seam). The kinds say how the arguments print;
# the ones with stubs of their own are below.
CALLEES = [
    # The End of loading.
    (0x00103e68, "eFixUpTables", "", False),
    (0x0021e5c8, "InitCollision", "", False),
    (0x001d5d00, "InitCollisionBody", "", False),
    (0x001d4520, "InitContact", "", False),
    (0x00152b48, "InitTree", "ptr", False),
    (0x0021f270, "InitSmokeables", "", True),
    (0x00136f28, "InitPhysics", "drivers", False),
    (0x0011c5f8, "SkyLoader", "", False),
    (0x0012a148, "rain_Load", "", False),
    (0x001251c0, "SunTrackLoader", "", False),
    (0x00203ce0, "InitDebugTopology", "", True),
    (0x001be310, "InitTrackMarkers", "", True),
    (0x0014f848, "InitVisibleZones", "", False),
    (0x002089d8, "InitTrackPaths", "", False),
    (0x001c3250, "InitTrackRoutes", "int", False),
    (0x001c5da0, "InitTrackRouteEditor", "", True),
    (0x001cd918, "InitWorldObjects", "", True),
    (0x001a9238, "InitAnimatedDriver", "", True),
    (0x001c6028, "InitAIPlans", "", True),
    (0x0024bf18, "SetRenderEggFromEasterEggs", "", True),
    (0x002577c0, "bMalloc", "malloc", True),
    (0x00149738, "RaceCoordinator", "ctor", True),
    # The Begins of unloading.
    (0x0014cbf8, "SetFlailerScreenVisibility", "flailer", True),
    (0x00111dd8, "eWaitUntilRenderingDone", "", True),
    (0x00149858, "~RaceCoordinator", "ptr_int", True),
    (0x001acf98, "UnloadAllTexturesFromFile", "ptr", True),
    (0x001c6058, "CloseAIPlans", "", True),
    (0x001a9458, "CloseAnimatedDriver", "", True),
    (0x001cd948, "CloseWorldObjects", "", True),
    (0x001c5dd8, "CloseTrackRouteEditor", "", True),
    (0x001c3558, "CloseTrackRoutes", "", False),
    (0x0014f898, "CloseVisibleZones", "", False),
    (0x001be378, "CloseTrackMarkers", "", True),
    (0x00203ce8, "CloseDebugTopology", "", True),
    (0x00125290, "SunTrackUnloader", "", False),
    (0x0011c6b8, "SkyUnloader", "", False),
    (0x0012a150, "rain_Unload", "", False),
    (0x00137070, "ClosePhysics", "", False),
    (0x0021f500, "CloseSmokeables", "", True),
    (0x00152b98, "CloseTree", "ptr", False),
    (0x002089e8, "CloseTrackPaths", "", False),
    (0x001d4550, "CloseContact", "", False),
    (0x001d5e20, "CloseCollisionBody", "", False),
    (0x0021e5f8, "CloseCollision", "", False),
    (0x00199728, "UnloadResourceFile", "ptr", True),
    (0x00199890, "FindResourceFile", "find", True),
    (0x001af420, "UnLoadSoundRegions", "", True),
    (0x0013f0c0, "DemoModeReplayUnload", DEMO_REPLAY, True),
    (0x0021e280, "UnloadSpeech", LANGUAGES, False),
    (0x00258730, "CleanupExpandedSlotPools", SLOT_POOLS, False),
    (0x002548a8, "bIsAsyncDone", "async", True),
    (0x00257988, "bCountFreeMemory", "count", True),
    (0x001083f0, "eFlashScreen", "flash", True),
    (0x001680d8, "ChangeGameFlow", "flow", False),
    (0x0024bdc0, "ResetRenderEggs", "", True),
    (0x0024f700, "ClearTemporaryEasterEggs", EASTER_EGGS, True),
    # The loading states'.
    (0x00199640, "LoadResourceFile", "loadres", False),
    (0x00199788, "ServiceResourceLoading", "", False),
    (0x00199818, "IsResourceLoadingComplete", "complete", False),
    (0x00199720, "ChangeFilenameForHotChunking", "rename", False),
    (0x001b0560, "Load", "load", False),
    (0x001b0b00, "BeginLoading", "begin", False),
    (0x001b08c0, "UnloadEverything", "ptr", False),
    (0x001acc98, "LoadTexturesFromFile", "loadtex", True),
    (0x00103bf0, "eDuplicateSolid", "dup", True),
    (0x00103d58, "eDeleteAllDuplicatedSolids", "", True),
    (0x0021e250, "LoadSpeech", LANGUAGES, False),
    (0x0013f070, "DemoModeReplayLoad", DEMO_REPLAY, True),
    (0x001ae798, "LoadSoundRegionsInGame", "sound", True),
    (0x001edb40, "GetDriverInfoByDriverNumber", "bynum", False),
    (TESTCB, "testcb", "int", False),
]


# ============================================================ the scenarios

def G(name, v):
    return "G %s %d" % (name, v)


def d(num, rank, car, inst=0, skin=0, dash=0, vd=0):
    return "d %d %d %d %d %d %d %d" % (num, rank, car, inst, skin, dash, vd)


def X(steps):
    return ["X " + s for s in steps]


def T(car, units):
    return "T %d %d" % (car, units)


def A(car, off, data):
    return "A %d %d %s" % (car, off, bytes(data).hex())


def name(s):
    return s.encode() + b"\0"


def f32(v):
    return struct.pack("<f", v)


def i32(v):
    return struct.pack("<i", v)


# The whole chain, step by step: C and its two parts, S and its six, then
# the End and both Begins of unloading.
CHAIN = X("C") + ["D", "D"] + X("S") + ["D"] * 6 + X("EUV")

FIELD = [
    d(0, 0, 2, 0, 3, 1, 0),       # the player, a VIPERGTS
    d(1, 0, 7, 0, 1, 0, 0),       # an AI MCLAREN
    d(2, 0, 2, 0, 2, 0, 0),       # a second VIPERGTS
    d(3, 0, 31, 0, 0, 0, 0),      # a BMWM5COP
    d(4, 0, 49, 0, 5, 0, 0),      # traffic: a PARCELVAN, skin 5
    d(5, 0, 49, 0, 2, 0, 0),      # and another
]


def s_race():
    # The plain race: one player, MPH, the HUD pack, no leak.
    return [G("track", 11), G("np", 1), G("units", 0), G("hud", 1),
            G("mem0", 5000), G("fe", 1), G("rr", 1), G("dft", 3)] \
        + FIELD + CHAIN


def s_damage():
    # Vertex damage, KPH, the frontend skipped, driver 0 knocked out, the
    # attract replay, an AI demo, the counts wrapping, a leak, a slow
    # INGAMEA, files to unload and a busy reader, something pending.
    return [G("track", 3), G("dir", 1), G("np", 1), G("units", 1),
            G("sfe", 1), G("rep", 1), G("aid", 1), G("lbase", 126),
            G("mem0", 9000), G("mstep", 7), G("nload", 3), G("nf2", 2),
            G("nf3", 3), G("nbusy", 2), G("pend", 5), G("rc", 1),
            G("hud", 1), G("ig", 4), G("jr2", 9), G("adf", 6)] + [
        d(0, 2, 5, 0, 1, 1, 1),       # knocked out, a CLK_GTR, damageable
        d(1, 0, 23, 0, 0, 1, 1),      # an F50, integrated gauges
        d(2, 0, 5, 0, 4, 0, 1),       # a second damageable CLK_GTR
        d(3, 0, 5, 0, 4, 0, 0),       # and one that is not
        d(4, 0, 50, 9, 1, 0, 1),      # damageable traffic
        d(5, 0, 50, 0, 3, 0, 0),
        d(6, 0, 33, 0, -1, 0, 0),     # a CORVETTECOP, skin -1
    ] + CHAIN


def s_null():
    # Every seam NULL, the same race.
    return [G("track", 11), G("np", 1), G("units", 0), G("hud", 1),
            G("rep", 1), G("mem0", 77), G("nf2", 1), G("nf3", 2),
            G("rc", 1), G("pend", 3), G("null", 1)] + FIELD + CHAIN


def s_null_skip():
    # And with SkipFE, two players, and LoadHudTextures on its own after.
    return [G("track", 7), G("np", 2), G("units", 1), G("sfe", 1),
            G("null", 1)] + FIELD[:3] + CHAIN + [G("np", 1)] + X("H")


def s_null_leak():
    # Both Begins of unloading with the counts NULL, after loads that were
    # not: free memory reads 0, and the leak checks see a leak.
    return [G("fc", 5), G("fs", 6), G("rc", 1), G("hud", 1),
            G("null", 1)] + X("UV")


def s_hud():
    # LoadHudTextures alone, over who drives and the units.
    sc = []
    for np_ in (2, 0, -1):
        sc += [G("np", np_)] + X("H") + ["D"]
    for units in (2, -1, 1, 0, 0x7f):
        sc += [G("np", 1), G("units", units)] + X("H") + ["D"]
    return [d(0, 0, 23), d(1, 0, 2)] + sc


def s_hud_drivers():
    sc = []
    # Driver 0 knocked out, driver 1 in: driver 1's gauges.
    sc += [[d(0, 1, 2), d(1, -1, 34)]]
    # Driver 1 listed first.
    sc += [[d(1, 0, 32), d(0, 0, 47)]]
    # Driver 0 missing.
    sc += [[d(5, 0, 2), d(1, 0, 17)]]
    # Both knocked out, and neither there.
    sc += [[d(0, 3, 2), d(1, 4, 17)]]
    sc += [[d(5, 0, 2), d(6, 0, 17)]]
    # No drivers at all, and NumDriverInfo short of driver 1.
    sc += [[]]
    sc += [[d(1, 0, 2), d(0, 0, 13), G("ndi", 1)]]
    out = []
    for i, drv in enumerate(sc):
        out.append([G("np", 1), G("units", i % 3), G("hud", i & 1)]
                   + drv + X("H") + ["D"])
    return out


def s_parts():
    # The parts alone, out of order, each way of SkipFE and the replay.
    return [G("track", -5), G("np", 1), G("hud", 1)] + FIELD[:2] + X("3") \
        + [G("sfe", 1)] + X("3") + X("6") + X("5") + [G("track", 123456)] \
        + X("4") + [G("rep", 1)] + X("1") + [G("rep", -1)] + X("1") \
        + X("2") + [G("track", 0)] + X("S") + ["D"] * 9


def s_instances():
    # Part2 over InstanceIndexes already set: none, the first, further
    # ones, and the byte's far ends; damageable and not.
    return [d(0, 0, 2, -1, 0, 0, 1), d(1, 0, 2, 0, 0, 0, 1),
            d(2, 0, 2, 1, 0, 0, 1), d(3, 0, 7, 5, 0, 0, 0),
            d(4, 0, 33, 127, 0, 0, 1), d(5, 0, 33, -128, 0, 0, 0),
            d(6, 0, 52, 2, 0, 0, 0), d(7, 0, 22, 3, 0, 0, 7)] \
        + X("q") + [G("ndi", 3)] + X("q") + [G("ndi", 0)] + X("q") \
        + [G("ndi", -2)] + X("q")


def s_part1():
    # Part1 over more drivers than NumDriverInfo says, then none; the
    # loader's two flags set to odd values first.
    return [G("fe", 7), G("rr", -1), G("lbase", -3)] + FIELD \
        + [d(6, 0, 51, 4, 9, 0, 3)] + [G("ndi", 4)] + X("p") \
        + [G("ndi", 0), G("fe", 2), G("rr", 2)] + X("p") \
        + [G("ndi", 7), G("lbase", 255)] + X("p") + ["D", "D"]


def s_unload():
    # The Begins of unloading alone: what is pending, the demo modes'
    # eggs, a leak or none on each side.
    sc = [G("mem0", 100), G("fc", 100), G("fs", 100), G("rc", 1)]
    for pend, aid, rpd in ((0, 0, 0), (-1, 0, 1), (8, 1, 0), (1, 1, 1),
                           (9, 0, 0)):
        sc += [G("pend", pend), G("aid", aid), G("rpd", rpd)] + X("UV")
    sc += [G("mstep", -1), G("fc", 99), G("fs", 97)] + X("VU")
    sc += [G("mstep", 0), G("mem0", -40), G("fc", -40), G("fs", 0),
           G("nf2", 3), G("nf3", 1), G("nbusy", 4)] + X("UV")
    return sc


def s_end():
    # The End: the track directions, the demo modes' eggs, twice.
    sc = []
    for dir_, aid, rpd in ((0, 0, 0), (1, 1, 0), (2, 0, 1), (-1, 3, 4),
                           (0x101, 0, 0)):
        sc += [G("dir", dir_), G("aid", aid), G("rpd", rpd),
               G("ig", 5), G("dft", 2), G("rev", 9), G("jr2", 4)] + X("E")
    return [d(0, 0, 2), d(1, 0, 3)] + sc + X("E")


def s_begins():
    # The Begins of loading alone, with SkipFE each way, a long wait for
    # INGAMEA, and run twice.
    return [G("mem0", 3), G("mstep", 2), G("nload", 5), G("track", 9),
            G("adf", 4), G("dft", 0)] + X("C") + [G("sfe", 1)] + X("CS") \
        + [G("sfe", -1), G("track", -1)] + X("S") + X("C") + X("3")


def s_choose():
    # ChooseLoadableTextures on every car, in each units setting.
    return [T(car, u) for car in range(NUM_TYPES) for u in (0, 1, 2, -1)]


def s_choose_patched():
    # The names and gauges the disc does not have: tails of COP and HP in
    # every order, the Lamborghini cop's name near misses, the longest
    # name, odd MaxRPMs and IsIntegrated words.
    sc = []
    names = ["BMWCOPHP", "HPCOP", "COP", "AHP", "XHP", "LAMBOCOPX",
             "LAMBOCO", "XCOPHP", "XHPCOP", "COPCOP", "HPHP",
             "ABCDEFGHIJKLMNOPQRSTUVWXYZ01234", "lambocop", "MCLARENHP",
             "SHOOP"]
    for i, n in enumerate(names):
        car = (5 * i) % 49
        sc += [A(car, 0, name(n))] + [T(car, u) for u in (0, 1, 2)]
    rpms = [7999.9, -1.5, 3e9, -3e9, 0.0, 0.99, -0.99, 2147483520.0,
            2147483648.0, 1e-30]
    for i, r in enumerate(rpms):
        car = 7 + i
        sc += [A(car, 1248, f32(r)), T(car, 0)]
    for bits in (0x7f800000, 0xff800000, 0x7fc00000, 0xffffffff,
                 0x00000001):
        sc += [A(20, 1248, struct.pack("<I", bits)), T(20, 1)]
    for i, w in enumerate((0x100, -0x80000000, -1, 0)):
        car = 23 + i
        sc += [A(car, 1232, i32(w))] + [T(car, u) for u in (0, 1)]
    # LAMBOCOP, integrated.
    sc += [A(32, 1232, i32(1))] + [T(32, u) for u in (0, 1, 3)]
    return sc


def s_records():
    # A load chain over changed cars: a cop that is traffic, traffic that
    # is a racer, a long base name.
    return [A(4, 1336, i32(2)), A(49, 1336, i32(0)),
            A(7, 32, name("ABCDEFGHIJKLMNOPQRSTU")),
            A(2, 1336, i32(-2)), G("np", 1), G("hud", 1), G("lbase", 3),
            d(0, 0, 4, 0, 2, 0, 0), d(1, 0, 49, 0, 3, 0, 0),
            d(2, 0, 49, 0, 1, 0, 1), d(3, 0, 7, 0, 0, 0, 1),
            d(4, 0, 7, 0, 0, 0, 1), d(5, 0, 2, 0, 6, 0, 0)] \
        + X("p") + ["D"] + X("q")


def script():
    scs = [s_race(), s_damage(), s_null(), s_null_skip(), s_null_leak(),
           s_hud()] \
        + s_hud_drivers() \
        + [s_parts(), s_instances(), s_part1(), s_unload(), s_end(),
           s_begins(), s_choose(), s_choose_patched(), s_records()]
    return scs


def records():
    return bytes(cic.car_records(cic.globalb_chunks()[cic.CAR_CHUNK]))


def encode(scenarios, recs):
    lines = ["R " + recs.hex()]
    for i, s in enumerate(scenarios):
        lines.append("B %d" % i)
        lines += s
    return NL.join(lines) + NL


# ================================================================ the model


class Model(object):
    def __init__(self, recs):
        self.out = []
        self.recs = recs
        self.e = retail_model.RetailEmu(ieee=True, eediv=True)
        for addr, nm, kind, seam in CALLEES:
            self.e.stub(addr, self.make_stub(nm, kind, seam))
        self.reset()

    def emit(self, s):
        self.out.append(s)

    # ---- the state ------------------------------------------------------

    def reset(self):
        e = self.e
        for a in (IN_GAME, HUD_PACK, JR2, FREE_COMMON, FREE_SPECIFIC,
                  ANIM_FIXUP, SKIP_FE, DISABLE_FIXUP, RACE_COORD, DESIRED,
                  PENDING, REVERSE, DEMO_DISC, DEMO_REPLAY, TRACK, TRACK_DIR,
                  AI_DEMO, REPLAY_DEMO, NUM_PLAYERS, NUM_DRIVERS):
            e.put32(a, 0)
        e.write(UNITS, b"\0")
        e.write(CAR_LOADER, bytes(32))
        e.write(DI_BASE, bytes(DI * MAXDRV))
        e.put32(DRIVERS, DI_BASE)
        e.write(REC_BASE, self.recs)
        e.put32(CAR_ARRAY, REC_BASE)
        self.ndrivers = 0
        self.lbase = self.mem0 = self.mstep = self.nload = self.nbusy = 0
        self.null = 0
        self.nfiles = {2: 0, 3: 0}
        self.nfound = {2: 0, 3: 0}
        self.counts = [0] * NUM_TYPES
        self.nmem = 0
        self.nrf = 0
        self.pend = []

    def set_global(self, nm, v):
        e = self.e
        words = {"track": TRACK, "dir": TRACK_DIR, "np": NUM_PLAYERS,
                 "aid": AI_DEMO, "rpd": REPLAY_DEMO, "ndi": NUM_DRIVERS,
                 "sfe": SKIP_FE, "pend": PENDING, "ig": IN_GAME,
                 "dft": DISABLE_FIXUP, "rev": REVERSE, "jr2": JR2,
                 "fc": FREE_COMMON, "fs": FREE_SPECIFIC, "adf": ANIM_FIXUP,
                 "fe": CAR_LOADER + 8, "rr": CAR_LOADER + 4,
                 "rep": DEMO_REPLAY}
        if nm in words:
            e.put32(words[nm], v)
        elif nm == "units":
            e.write(UNITS, bytes([v & 0xff]))
        elif nm == "rc":
            e.put32(RACE_COORD, RC0 if v else 0)
        elif nm == "hud":
            e.put32(HUD_PACK, HUD if v else 0)
        elif nm in ("lbase", "mem0", "mstep", "nload", "nbusy"):
            setattr(self, nm, v)
        elif nm == "nf2":
            self.nfiles[2] = v
        elif nm == "nf3":
            self.nfiles[3] = v
        elif nm == "null":
            self.null = v
        else:
            raise SystemExit("no global %s" % nm)

    def add_driver(self, num, rank, car, inst, skin, dash, vd):
        a = DI_BASE + DI * self.ndrivers
        rec = bytearray(DI)
        rec[0] = rank & 0xff
        rec[1] = num & 0xff
        struct.pack_into("<i", rec, 8, 2)            # an AI racer
        struct.pack_into("<i", rec, 12, car)
        rec[16] = inst & 0xff
        rec[17] = skin & 0xff
        rec[18] = dash & 0xff
        rec[19] = vd & 0xff
        self.e.write(a, bytes(rec))
        self.ndrivers += 1
        self.e.put32(NUM_DRIVERS, self.ndrivers)

    # ---- the labels -----------------------------------------------------

    def s8(self, a):
        v = self.e.u8(a)
        return v - 256 if v & 0x80 else v

    def label(self, a):
        a &= M32
        if a == 0:
            return "null"
        named = {RC0: "rc0", RC_NEW: "rc", HUD: "hud", TOPO_TREE: "TT",
                 CAR_LOADER: "L0"}
        if a in named:
            return named[a]
        if RF_BASE <= a < RF_BASE + 4 * MAXRF and (a - RF_BASE) % 4 == 0:
            return "rf%d" % ((a - RF_BASE) // 4)
        for t, base in FILES.items():
            if base <= a < base + 4 * 64 and (a - base) % 4 == 0:
                return "f%d.%d" % (t, (a - base) // 4)
        if DI_BASE <= a < DI_BASE + DI * MAXDRV:
            k, off = divmod(a - DI_BASE, DI)
            if off == 0:
                return "d%d" % k
            if off == 12:
                return "r%d" % k
        return "x%08x" % a

    def cblabel(self, a):
        a &= M32
        return "null" if a == 0 else CB_NAMES.get(a, "?")

    def vcblabel(self, a):
        a &= M32
        return "null" if a == 0 else VCB_NAMES.get(a, "?")

    def cstr(self, a, n=128):
        b = bytearray()
        while len(b) < n and self.e.mem[a]:
            b.append(self.e.mem[a])
            a += 1
        return b.decode("latin-1")

    def snap(self):
        e = self.e
        return (" | ig=%d dft=%d rev=%d jr2=%d rc=%s sfe=%d fc=%d fs=%d"
                " adf=%d fe=%d rr=%d want=%d pend=%d" % (
                    s32(e.u32(IN_GAME)), s32(e.u32(DISABLE_FIXUP)),
                    s32(e.u32(REVERSE)), s32(e.u32(JR2)),
                    self.label(e.u32(RACE_COORD)), s32(e.u32(SKIP_FE)),
                    s32(e.u32(FREE_COMMON)), s32(e.u32(FREE_SPECIFIC)),
                    s32(e.u32(ANIM_FIXUP)), s32(e.u32(CAR_LOADER + 8)),
                    s32(e.u32(CAR_LOADER + 4)), s32(e.u32(DESIRED)),
                    s32(e.u32(PENDING))))

    def say(self, s):
        self.emit("  " + s + self.snap())

    def print_state(self):
        self.emit("st" + self.snap())
        self.emit("drv" + "".join(
            " %d/%d" % (self.s8(DI_BASE + DI * k + 16),
                        self.s8(DI_BASE + DI * k + 17))
            for k in range(self.ndrivers)))

    # ---- nested calls ---------------------------------------------------

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

    # ---- the stubs ------------------------------------------------------

    def make_stub(self, nm, kind, seam):
        def stub(em):
            a = [em.reg[4 + i] & M32 for i in range(5)]
            quiet = seam and self.null
            ret = 0
            text = nm
            if kind == "ptr":
                text += " " + self.label(a[0])
            elif kind == "int":
                text += " %d" % s32(a[0])
            elif kind == "ptr_int":
                text += " %s %d" % (self.label(a[0]), s32(a[1]))
            elif kind == "drivers":
                text += " %d" % s32(em.u32(NUM_DRIVERS))
            elif kind == "flailer":
                text += " %08x %d" % (a[0], s32(a[1]))
            elif kind == "malloc":
                text += " %d %s %d %d" % (s32(a[0]), self.cstr(a[1]),
                                          s32(a[2]), s32(a[3]))
                ret = 0 if quiet else RC_NEW
            elif kind == "ctor":
                ret = 0 if quiet else a[0]
            elif kind == "find":
                t = s32(a[0])
                f = 0
                if not quiet and t in self.nfiles \
                        and self.nfound[t] < self.nfiles[t]:
                    self.nfound[t] += 1
                    f = FILES[t] + 4 * self.nfound[t]
                text += " %d -> %s" % (t, self.label(f))
                ret = f
            elif kind == "async":
                if quiet:
                    ret = 1
                else:
                    ret = 1 if self.nbusy <= 0 else 0
                    if self.nbusy > 0:
                        self.nbusy -= 1
                text += " %s -> %d" % (self.label(a[0]), ret)
            elif kind == "count":
                if not quiet:
                    ret = self.mem0 + self.mstep * self.nmem
                    self.nmem += 1
                text += " %d -> %d" % (s32(a[0]), ret)
            elif kind == "flash":
                text += " %d %d %d %s %g" % (s32(a[0]), s32(a[1]), s32(a[2]),
                                             self.cstr(a[3]), em.f(12))
            elif kind == "flow":
                em.put32(DESIRED, a[0])
                em.put32(PENDING, a[1])
                text += " %d %d" % (s32(a[0]), s32(a[1]))
            elif kind == "loadres":
                if self.nrf >= MAXRF:
                    raise SystemExit("too many files")
                rf = RF_BASE + 4 * self.nrf
                self.nrf += 1
                text += " %s %d %d %s %d -> %s" % (
                    self.cstr(a[0]), s32(a[1]), s32(a[2]),
                    self.cblabel(a[3]), s32(a[4]), self.label(rf))
                if a[3]:
                    self.pend.append((a[3], s32(a[4]), False))
                ret = rf
            elif kind == "complete":
                ret = 1 if self.nload <= 0 else 0
                if self.nload > 0:
                    self.nload -= 1
                text += " -> %d" % ret
            elif kind == "rename":
                text += " %s %s" % (self.label(a[0]), self.cstr(a[1]))
            elif kind == "load":
                r = a[1]
                t = s32(em.u32(r))
                n = self.lbase
                if 0 <= t < NUM_TYPES:
                    n += self.counts[t]
                    self.counts[t] += 1
                n &= 0xff
                n = n - 256 if n & 0x80 else n
                text += " %s %s type=%d inst=%d skin=%d dash=%d vd=%d -> %d" % (
                    self.label(a[0]), self.label(r), t, self.s8(r + 4),
                    self.s8(r + 5), self.s8(r + 6), self.s8(r + 7), n)
                ret = n
            elif kind == "begin":
                text += " %s %s" % (self.label(a[0]), self.vcblabel(a[1]))
                if a[1]:
                    self.pend.append((a[1], 0, True))
            elif kind == "loadtex":
                n = s32(a[2])
                text += " %s %d %s %d:" % (self.label(a[0]), n,
                                           self.cblabel(a[3]), s32(a[4]))
                text += "".join(" %08x" % em.u32(a[1] + 4 * i)
                                for i in range(n))
                if quiet:
                    if a[3]:
                        self.nested(a[3], s32(a[4]))
                    return 0
                if a[3]:
                    self.pend.append((a[3], s32(a[4]), False))
            elif kind == "dup":
                text += " %s %s" % (self.cstr(a[0]), self.cstr(a[1]))
            elif kind == "sound":
                text += " %s %d" % (self.cblabel(a[0]), s32(a[1]))
                if quiet:
                    if a[0]:
                        self.nested(a[0], s32(a[1]))
                    return 0
                if a[0]:
                    self.pend.append((a[0], s32(a[1]), False))
            elif kind == "bynum":
                want = s32(a[1])
                f = 0
                for k in range(s32(em.u32(NUM_DRIVERS))):
                    if self.s8(DI_BASE + DI * k + 1) == want:
                        f = DI_BASE + DI * k
                        break
                text += " %d -> %s" % (want, self.label(f))
                if a[0] != RP:
                    text += " on x%08x, not RaceParameters" % a[0]
                ret = f
            elif isinstance(kind, int):
                if a[0] != kind:
                    text += " on x%08x, not x%08x" % (a[0], kind)
            if not quiet:
                self.say(text)
            return ret
        return stub

    # ---- the ops --------------------------------------------------------

    def run_pending(self):
        if not self.pend:
            self.emit("  nothing pending")
            return
        fn, param, void = self.pend.pop(0)
        if void:
            self.e.call(fn, limit=LIMIT)
        else:
            self.e.call(fn, param, limit=LIMIT)

    def choose(self, car, units):
        e = self.e
        e.write(TEX_BUF, b"\xee" * 16)
        e.call(CHOOSE, car, units, TEX_BUF, limit=LIMIT)
        self.emit("  tex %08x %08x %08x %08x" % tuple(
            e.u32(TEX_BUF + 4 * i) for i in range(4)))

    def run(self, scenarios):
        e = self.e
        for k, sc in enumerate(scenarios):
            self.emit("B %d" % k)
            self.reset()
            for line in sc:
                self.emit("> " + line[:40])
                op, rest = line[0], line[2:]
                if op == "A":
                    car, off, data = rest.split(" ")
                    e.write(REC_BASE + REC * int(car) + int(off),
                            bytes.fromhex(data))
                elif op == "G":
                    nm, v = rest.split(" ")
                    self.set_global(nm, int(v))
                elif op == "d":
                    self.add_driver(*[int(x) for x in rest.split(" ")])
                elif op == "X":
                    if rest == "H":
                        e.call(LOAD_HUD, TESTCB, limit=LIMIT)
                    else:
                        e.call(STEPS[rest], 0, limit=LIMIT)
                    self.print_state()
                elif op == "D":
                    self.run_pending()
                    self.print_state()
                elif op == "T":
                    car, units = rest.split(" ")
                    self.choose(int(car), int(units))
                else:
                    raise SystemExit("bad op %r" % line)
        return self.out


def model(scenarios, recs):
    return Model(recs).run(scenarios)


# ================================================================ the build


def build_harness(tmp, name="trackflow_test"):
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

LTC_HEAD = ("    FreeMemoryBeforeLoadingTrackCommon = count_free_memory();\n"
            "    eDisableFixUpTables = 1;\n")
LTS_HEAD = ("    FreeMemoryBeforeLoadingTrackSpecific = count_free_memory();\n"
            "    eDisableFixUpTables = 1;\n")
NEW_RC = ("    pRaceCoordinator = gNewRaceCoordinatorFn != NULL\n"
          "                     ? gNewRaceCoordinatorFn() : NULL;")
END_EGG = ("    if (!RaceParametersAIDemoMode && !RaceParametersReplayDemoMode)\n"
           "        CALL(gSetRenderEggFromEasterEggsFn);\n")
UTS_EGGS = ("    if (!RaceParametersAIDemoMode && !RaceParametersReplayDemoMode) {\n"
            "        CALL(gResetRenderEggsFn);\n"
            "        CALL(gClearTemporaryEasterEggsFn);\n    }\n")
UTS_FLOW = ("        gf->skipFE = 0;\n"
            "        bgf_change_state(gf, pending != BGF_NONE ? pending\n"
            "                                                 : BGF_UNLOADING_TRACK_COMMON,\n"
            "                         BGF_NONE);\n")
UTS_FLOW_BLOCK = ("\n    if (gTrackFlowGameFlow != NULL) {\n"
                  "        BGameFlow *gf = gTrackFlowGameFlow;\n"
                  "        int pending = gf->pending;\n\n" + UTS_FLOW + "    }\n")
UTS_WAIT = ("    while (gBIsAsyncDoneFn != NULL && !gBIsAsyncDoneFn(NULL))\n"
            "        ;\n")
UTS_LEAK = ("    check_for_leak(FreeMemoryBeforeLoadingTrackSpecific,\n"
            "                   \"Memory Leak - Track Specific\");\n")
UTC_FILES = ("    while (gFindResourceFileFn != NULL && gUnloadResourceFileFn != NULL\n"
             "           && (file = gFindResourceFileFn(RESOURCE_FILE_INGAME)) != NULL)\n"
             "        gUnloadResourceFileFn(file);\n")
UTC_LEAK = ("    check_for_leak(FreeMemoryBeforeLoadingTrackCommon,\n"
            "                   \"Memory Leak - Track Common\");\n")
P1C_TRAFFIC_SKIN = ("        if (ct->UsageType == CAR_USAGE_TYPE_TRAFFIC)\n"
                    "            ri->SkinNumber = -1;\n")
P2C_SCUFFS = ("        snprintf(from, sizeof from, \"%s_SCUFFS\", base);\n"
              "        snprintf(to, sizeof to, \"%s_SCUFFS%d\", base, inst);\n"
              "        duplicate_solid(from, to);\n")

MUTATIONS = [
    # The helpers.
    ("count_pool_0", TFC,
     "gBCountFreeMemoryFn(MAIN_POOL) : 0;", "gBCountFreeMemoryFn(0) : 0;"),
    ("count_null_1", TFC,
     "gBCountFreeMemoryFn(MAIN_POOL) : 0;", "gBCountFreeMemoryFn(MAIN_POOL) : 1;"),
    ("count_unguarded", TFC,
     "    return gBCountFreeMemoryFn != NULL ? gBCountFreeMemoryFn(MAIN_POOL) : 0;",
     "    return gBCountFreeMemoryFn(MAIN_POOL);"),
    ("skipfe_ignored", TFC,
     "    return gTrackFlowGameFlow != NULL && gTrackFlowGameFlow->skipFE != 0;",
     "    return 0;"),
    ("skipfe_positive", TFC,
     "gTrackFlowGameFlow->skipFE != 0;", "gTrackFlowGameFlow->skipFE > 0;"),
    ("flow_pending_kept", TFC,
     "        bgf_change_state(gTrackFlowGameFlow, state, BGF_NONE);",
     "        bgf_change_state(gTrackFlowGameFlow, state,\n"
     "                         gTrackFlowGameFlow->pending);"),
    ("screen_0", TFC,
     "gSetFlailerScreenVisibilityFn(BGF_SCREEN_LOADING_TRACK, visibility);",
     "gSetFlailerScreenVisibilityFn(0, visibility);"),
    ("screen_unguarded", TFC,
     "    if (gSetFlailerScreenVisibilityFn != NULL)\n"
     "        gSetFlailerScreenVisibilityFn(BGF_SCREEN_LOADING_TRACK, visibility);",
     "    gSetFlailerScreenVisibilityFn(BGF_SCREEN_LOADING_TRACK, visibility);"),
    ("leak_inverted", TFC,
     "    if (count_free_memory() != before && gEFlashScreenFn != NULL)",
     "    if (count_free_memory() == before && gEFlashScreenFn != NULL)"),
    ("leak_unguarded", TFC,
     "    if (count_free_memory() != before && gEFlashScreenFn != NULL)",
     "    if (count_free_memory() != before)"),
    ("leak_red", TFC,
     "gEFlashScreenFn(0, 128, 0, why, 1.0f);", "gEFlashScreenFn(128, 0, 0, why, 1.0f);"),
    ("leak_bright", TFC,
     "gEFlashScreenFn(0, 128, 0, why, 1.0f);", "gEFlashScreenFn(0, 255, 0, why, 1.0f);"),
    ("leak_seconds", TFC,
     "gEFlashScreenFn(0, 128, 0, why, 1.0f);", "gEFlashScreenFn(0, 128, 0, why, 2.0f);"),
    ("dup_unguarded", TFC,
     "    if (gEDuplicateSolidFn != NULL)\n        gEDuplicateSolidFn(from, to);",
     "    gEDuplicateSolidFn(from, to);"),
    ("dup_swapped", TFC,
     "        gEDuplicateSolidFn(from, to);", "        gEDuplicateSolidFn(to, from);"),
    ("hudtex_two", TFC,
     "gLoadTexturesFromFileFn(pHudTexturePack, hash, 1, done, 0);",
     "gLoadTexturesFromFileFn(pHudTexturePack, hash, 2, done, 0);"),
    ("hudtex_param", TFC,
     "gLoadTexturesFromFileFn(pHudTexturePack, hash, 1, done, 0);",
     "gLoadTexturesFromFileFn(pHudTexturePack, hash, 1, done, 1);"),
    ("hudtex_null_stalls", TFC,
     "    else if (done != NULL)\n        done(0);", ""),
    ("hudtex_null_param", TFC,
     "        done(0);\n}", "        done(1);\n}"),
    ("hudtex_null_unguarded", TFC,
     "    else if (done != NULL)\n        done(0);", "    else\n        done(0);"),
    ("bundle_flags_hot", TFC,
     "    (RESOURCE_FILE_FLAG_HOTCHUNKABLE | RESOURCE_FILE_FLAG_LZCOMPRESSED)",
     "    (RESOURCE_FILE_FLAG_HOTCHUNKABLE)"),
    ("bundle_flags_lz", TFC,
     "    (RESOURCE_FILE_FLAG_HOTCHUNKABLE | RESOURCE_FILE_FLAG_LZCOMPRESSED)",
     "    (RESOURCE_FILE_FLAG_LZCOMPRESSED)"),
    ("call_unguarded", TFC,
     "#define CALL(fn) do { if ((fn) != NULL) (fn)(); } while (0)",
     "#define CALL(fn) do { (fn)(); } while (0)"),

    # The Begin of loading's common part.
    ("ltc_dft_first", TFC, LTC_HEAD,
     "    eDisableFixUpTables = 1;\n"
     "    FreeMemoryBeforeLoadingTrackCommon = count_free_memory();\n"),
    ("ltc_dft_kept", TFC, LTC_HEAD,
     "    FreeMemoryBeforeLoadingTrackCommon = count_free_memory();\n"),
    ("ltc_fc_into_fs", TFC, LTC_HEAD,
     "    FreeMemoryBeforeLoadingTrackSpecific = count_free_memory();\n"
     "    eDisableFixUpTables = 1;\n"),
    ("ltc_screen_inverted", TFC,
     "    if (!skip_fe())\n        set_loading_screen(FLAILER_SCREEN_VISIBLE);",
     "    if (skip_fe())\n        set_loading_screen(FLAILER_SCREEN_VISIBLE);"),
    ("ltc_screen_always", TFC,
     "    if (!skip_fe())\n        set_loading_screen(FLAILER_SCREEN_VISIBLE);",
     "    set_loading_screen(FLAILER_SCREEN_VISIBLE);"),
    ("ltc_screen_invisible", TFC,
     "    if (!skip_fe())\n        set_loading_screen(FLAILER_SCREEN_VISIBLE);",
     "    if (!skip_fe())\n        set_loading_screen(FLAILER_SCREEN_INVISIBLE);"),
    ("ltc_ingamea_flags", TFC,
     "RESOURCE_FILE_INGAME, 0, NULL,\n                       0);",
     "RESOURCE_FILE_INGAME, 8, NULL,\n                       0);"),
    ("ltc_ingamea_track", TFC,
     "RESOURCE_FILE_INGAME, 0, NULL,\n                       0);",
     "RESOURCE_FILE_TRACK, 0, NULL,\n                       0);"),
    ("ltc_ingamea_name", TFC, "INGAMEA.BUN", "INGAMEA.LZC"),
    ("ltc_adf_early", TFC,
     "    load_resource_file(\"GLOBAL\\\\INGAMEA.BUN\"",
     "    AnimatedDriverNeedsFixup = 1;\n"
     "    load_resource_file(\"GLOBAL\\\\INGAMEA.BUN\""),
    ("ltc_adf_late", TFC,
     "    AnimatedDriverNeedsFixup = 1;\n"
     "    while (!is_resource_loading_complete())\n"
     "        service_resource_loading();\n",
     "    while (!is_resource_loading_complete())\n"
     "        service_resource_loading();\n"
     "    AnimatedDriverNeedsFixup = 1;\n"),
    ("ltc_adf_2", TFC,
     "    AnimatedDriverNeedsFixup = 1;", "    AnimatedDriverNeedsFixup = 2;"),
    ("ltc_no_wait", TFC,
     "    while (!is_resource_loading_complete())\n"
     "        service_resource_loading();\n", ""),
    ("ltc_wait_once", TFC,
     "    while (!is_resource_loading_complete())",
     "    if (!is_resource_loading_complete())"),
    ("ltc_ingameb_track", TFC,
     "rf = load_resource_file(\"GLOBAL\\\\INGAMEB.LZC\", RESOURCE_FILE_INGAME,",
     "rf = load_resource_file(\"GLOBAL\\\\INGAMEB.LZC\", RESOURCE_FILE_TRACK,"),
    ("ltc_ingameb_param", TFC,
     "BUNDLE_FLAGS, GameFlowLoadingTrackCommonPart1, 0);",
     "BUNDLE_FLAGS, GameFlowLoadingTrackCommonPart1, 1);"),
    ("ltc_ingameb_bun", TFC,
     "\"GLOBAL\\\\INGAMEB.LZC\"", "\"GLOBAL\\\\INGAMEB.BUN\""),
    ("ltc_no_rename", TFC,
     "    change_filename_for_hot_chunking(rf, \"GLOBAL\\\\INGAMEB.BUN\");\n", ""),
    ("ltc_rename_lzc", TFC,
     "    change_filename_for_hot_chunking(rf, \"GLOBAL\\\\INGAMEB.BUN\");",
     "    change_filename_for_hot_chunking(rf, \"GLOBAL\\\\INGAMEB.LZC\");"),

    # Its Part1: the cars.
    ("p1c_fe_kept", TFC, "    TheCarLoader.InFrontEndFlag = 0;\n", ""),
    ("p1c_rr_kept", TFC, "    TheCarLoader.RoundRobinFlag = 0;\n", ""),
    ("p1c_rr_1", TFC,
     "    TheCarLoader.RoundRobinFlag = 0;", "    TheCarLoader.RoundRobinFlag = 1;"),
    ("p1c_first_loop_all", TFC,
     "        if (ri->CanBeVertexDamaged)\n            continue;\n", ""),
    ("p1c_first_loop_inverted", TFC,
     "        if (ri->CanBeVertexDamaged)\n            continue;",
     "        if (!ri->CanBeVertexDamaged)\n            continue;"),
    ("p1c_second_loop_all", TFC,
     "        if (ri->CanBeVertexDamaged)\n            ri->InstanceIndex",
     "        if (1)\n            ri->InstanceIndex"),
    ("p1c_second_loop_none", TFC,
     "            ri->InstanceIndex = (int8_t)carloader_load(&TheCarLoader, ri);",
     "            (void)0;"),
    ("p1c_second_loop_skips_first", TFC,
     "    for (i = 0; i < RaceParametersNumDriverInfo; i++) {\n"
     "        RideInfo *ri = &race_parameters_get_driver_info(i)",
     "    for (i = 1; i < RaceParametersNumDriverInfo; i++) {\n"
     "        RideInfo *ri = &race_parameters_get_driver_info(i)"),
    ("p1c_first_loop_over", TFC,
     "    for (i = 0; i < RaceParametersNumDriverInfo; i++) {\n"
     "        DriverInfo *di",
     "    for (i = 0; i <= RaceParametersNumDriverInfo; i++) {\n"
     "        DriverInfo *di"),
    ("p1c_traffic_skin_kept", TFC, P1C_TRAFFIC_SKIN, ""),
    ("p1c_cop_skin", TFC, P1C_TRAFFIC_SKIN,
     "        if (ct->UsageType == CAR_USAGE_TYPE_COP)\n"
     "            ri->SkinNumber = -1;\n"),
    ("p1c_skin_0", TFC,
     "            ri->SkinNumber = -1;", "            ri->SkinNumber = 0;"),
    ("p1c_skin_not_restored", TFC, "        ri->SkinNumber = skin;\n", ""),
    ("p1c_skin_restored_early", TFC,
     "        n = carloader_load(&TheCarLoader, ri);\n",
     "        ri->SkinNumber = skin;\n"
     "        n = carloader_load(&TheCarLoader, ri);\n"),
    ("p1c_traffic_instance", TFC,
     "                          ? (int8_t)n : 0;",
     "                          ? (int8_t)n : (int8_t)n;"),
    ("p1c_traffic_instance_1", TFC,
     "                          ? (int8_t)n : 0;", "                          ? (int8_t)n : 1;"),
    ("p1c_racing_or_cop", TFC,
     "        ri->InstanceIndex = ct->UsageType != CAR_USAGE_TYPE_TRAFFIC",
     "        ri->InstanceIndex = (ct->UsageType == CAR_USAGE_TYPE_RACING\n"
     "                             || ct->UsageType == CAR_USAGE_TYPE_COP)"),
    ("p1c_no_begin", TFC,
     "    carloader_begin_loading(&TheCarLoader, GameFlowLoadingTrackCommonPart2);",
     "    (void)0;"),
    ("p1c_begin_first", TFC,
     "    TheCarLoader.InFrontEndFlag = 0;\n",
     "    carloader_begin_loading(&TheCarLoader, GameFlowLoadingTrackCommonPart2);\n"
     "    TheCarLoader.InFrontEndFlag = 0;\n"),

    # Its Part2: the duplicated solids.
    ("p2c_inst_zero_too", TFC, "        if (inst <= 0)", "        if (inst < 0)"),
    ("p2c_inst_skips_1", TFC, "        if (inst <= 0)", "        if (inst <= 1)"),
    ("p2c_inst_unsigned", TFC,
     "        int inst = ri->InstanceIndex;",
     "        int inst = (uint8_t)ri->InstanceIndex;"),
    ("p2c_halves_always", TFC,
     "        if (ri->CanBeVertexDamaged) {\n            int c;",
     "        if (1) {\n            int c;"),
    ("p2c_halves_never", TFC,
     "        if (ri->CanBeVertexDamaged) {\n            int c;",
     "        if (0) {\n            int c;"),
    ("p2c_one_half", TFC, "c < 'C'; c++", "c < 'B'; c++"),
    ("p2c_halves_lower", TFC, "for (c = 'A'; c < 'C'; c++)", "for (c = 'a'; c < 'c'; c++)"),
    ("p2c_from_numbered", TFC,
     "\"%s_%c\", base, c);", "\"%s_%c%d\", base, c, inst);"),
    ("p2c_to_unnumbered", TFC,
     "\"%s_%c%d\", base, c, inst);", "\"%s_%c\", base, c);"),
    ("p2c_scuffs_name", TFC, "\"%s_SCUFFS\", base);", "\"%s_SCUFF\", base);"),
    ("p2c_scuffs_to", TFC, "\"%s_SCUFFS%d\", base, inst);", "\"%s_SCUFFS_%d\", base, inst);"),
    ("p2c_scuffs_damageable_only", TFC, P2C_SCUFFS,
     "        snprintf(from, sizeof from, \"%s_SCUFFS\", base);\n"
     "        snprintf(to, sizeof to, \"%s_SCUFFS%d\", base, inst);\n"
     "        if (ri->CanBeVertexDamaged)\n"
     "            duplicate_solid(from, to);\n"),
    ("p2c_scuffs_first", TFC,
     "        if (ri->CanBeVertexDamaged) {\n            int c;",
     P2C_SCUFFS + "        if (ri->CanBeVertexDamaged) {\n            int c;"),
    ("p2c_car_name", TFC,
     "cartypeinfo_get(ri->Type)->BaseModelName;",
     "cartypeinfo_get(ri->Type)->CarTypeName;"),
    ("p2c_one_driver", TFC,
     "    for (i = 0; i < RaceParametersNumDriverInfo; i++) {\n"
     "        const RideInfo *ri",
     "    for (i = 0; i < 1; i++) {\n"
     "        const RideInfo *ri"),
    ("p2c_flow_racing", TFC,
     "    change_game_flow(BGF_LOADING_TRACK_SPECIFIC);",
     "    change_game_flow(BGF_RACING);"),
    ("p2c_no_flow", TFC,
     "    change_game_flow(BGF_LOADING_TRACK_SPECIFIC);\n", ""),

    # LoadHudTextures.
    ("hud_np_at_least_1", TFC,
     "    if (RaceParametersNumPlayerCars == 1) {",
     "    if (RaceParametersNumPlayerCars >= 1) {"),
    ("hud_np_ignored", TFC,
     "    if (RaceParametersNumPlayerCars == 1) {", "    if (1) {"),
    ("hud_rank_zero_out", TFC,
     "        if (di == NULL || di->EliminatedRank > 0)",
     "        if (di == NULL || di->EliminatedRank >= 0)"),
    ("hud_no_fallback_on_rank", TFC,
     "        if (di == NULL || di->EliminatedRank > 0)",
     "        if (di == NULL)"),
    ("hud_no_fallback_on_null", TFC,
     "        if (di == NULL || di->EliminatedRank > 0)",
     "        if (di != NULL && di->EliminatedRank > 0)"),
    ("hud_fallback_2", TFC,
     "            di = race_parameters_get_driver_info_by_driver_number(1);",
     "            di = race_parameters_get_driver_info_by_driver_number(2);"),
    ("hud_second_rank_unchecked", TFC,
     "        if (di != NULL && di->EliminatedRank <= 0) {",
     "        if (di != NULL) {"),
    ("hud_second_rank_negative_out", TFC,
     "        if (di != NULL && di->EliminatedRank <= 0) {",
     "        if (di != NULL && di->EliminatedRank == 0) {"),
    ("hud_tach_always", TFC, "            if (t.Tach != 0) {", "            if (1) {"),
    ("hud_tach_first", TFC,
     "            speedo = t.Speedo;\n",
     "            tach = t.Tach;\n            load_hud_texture(&tach, NULL);\n"
     "            speedo = t.Speedo;\n"),
    ("hud_shadow_first", TFC,
     "            speedo = t.Speedo;\n            load_hud_texture(&speedo, NULL);\n"
     "            shadow = t.Shadow;\n            load_hud_texture(&shadow, NULL);\n",
     "            shadow = t.Shadow;\n            load_hud_texture(&shadow, NULL);\n"
     "            speedo = t.Speedo;\n            load_hud_texture(&speedo, NULL);\n"),
    ("hud_third_done", TFC,
     "            load_hud_texture(&third, NULL);", "            load_hud_texture(&third, done);"),
    ("hud_gauge_not_mph", TFC,
     "    gauge = bchunk_hash(units == UNITS_KPH ? \"3RDPERSONGAUGE_KMH\"",
     "    gauge = bchunk_hash(units != UNITS_MPH ? \"3RDPERSONGAUGE_KMH\""),
    ("hud_gauge_kph", TFC, "\"3RDPERSONGAUGE_KMH\"", "\"3RDPERSONGAUGE_KPH\""),
    ("hud_gauge_done_null", TFC,
     "    load_hud_texture(&gauge, done);", "    load_hud_texture(&gauge, NULL);"),
    ("hud_units_player", TFC,
     "            ChooseLoadableTextures(di->CurrentRideInfo.Type, units, &t);",
     "            ChooseLoadableTextures(di->CurrentRideInfo.Type, UNITS_MPH, &t);"),

    # ChooseLoadableTextures.
    ("ch_rpm_rounded", HTC,
     "(int)ee_trunc_w(max_rpm)", "(int)ee_trunc_w(max_rpm + 0.5f)"),
    ("ch_rpm_cast", HTC, "(int)ee_trunc_w(max_rpm)", "(int)max_rpm"),
    ("ch_rpm_offset", HTC,
     "#define HUD_MAX_RPM       16", "#define HUD_MAX_RPM       20"),
    ("ch_integrated_offset", HTC,
     "#define HUD_IS_INTEGRATED 0", "#define HUD_IS_INTEGRATED 4"),
    ("ch_third_name", HTC, "\"3RDPERSON_%d\"", "\"3RDPERSON%d\""),
    ("ch_lambo_ignored", HTC,
     "    if (strcmp(\"LAMBOCOP\", ct->CarTypeName) == 0) {", "    if (0) {"),
    ("ch_lambo_prefix", HTC,
     "    if (strcmp(\"LAMBOCOP\", ct->CarTypeName) == 0) {",
     "    if (strncmp(\"LAMBOCOP\", ct->CarTypeName, 8) == 0) {"),
    ("ch_lambo_base", HTC, "\"MURCIELAGO\"", "\"LAMBO\""),
    ("ch_cop_kept", HTC, "\"COP\") == 0 ? 3 : 0;", "\"COP\") == 0 ? 0 : 0;"),
    ("ch_cop_cut_2", HTC, "\"COP\") == 0 ? 3 : 0;", "\"COP\") == 0 ? 2 : 0;"),
    ("ch_hp_kept", HTC, "            cut = 2;", "            cut = 0;"),
    ("ch_hp_cut_3", HTC, "            cut = 2;", "            cut = 3;"),
    ("ch_cop_at_2", HTC,
     "strcmp(ct->CarTypeName + len - 3, \"COP\")",
     "strcmp(ct->CarTypeName + len - 2, \"OP\")"),
    ("ch_no_memset", HTC, "        memset(base, 0, sizeof base);\n", ""),
    ("ch_kph_not_mph", HTC,
     "    if (units == UNITS_KPH)", "    if (units != UNITS_MPH)"),
    ("ch_mph_else", HTC, "    else if (units == UNITS_MPH)", "    else"),
    ("ch_kmh_name", HTC, "\"%s_KMH\"", "\"%s_KPH\""),
    ("ch_mph_name", HTC, "\"%s_MPH\"", "\"%s_MPH_\""),
    ("ch_integrated_byte", HTC,
     "    if (integrated != 0) {", "    if ((integrated & 0xff) != 0) {"),
    ("ch_integrated_positive", HTC,
     "    if (integrated != 0) {", "    if (integrated > 0) {"),
    ("ch_integrated_tach_1", HTC, "        t->Tach = 0;", "        t->Tach = 1;"),
    ("ch_overlay_generic_named", HTC,
     "        snprintf(name, sizeof name, \"OVERLAY_GENERIC\");",
     "        snprintf(name, sizeof name, \"OVERLAY_%s\", base);"),
    ("ch_overlay_named_generic", HTC,
     "        snprintf(name, sizeof name, \"OVERLAY_%s\", base);",
     "        snprintf(name, sizeof name, \"OVERLAY_GENERIC\");"),
    ("ch_tach_name", HTC, "\"%s_TACH\"", "\"%s_TAC\""),
    ("ch_speedo_is_shadow", HTC,
     "    t->Speedo = bchunk_hash(name);", "    t->Speedo = bchunk_hash(\"\");"),

    # The Begin of loading's track part.
    ("lts_dft_first", TFC, LTS_HEAD,
     "    eDisableFixUpTables = 1;\n"
     "    FreeMemoryBeforeLoadingTrackSpecific = count_free_memory();\n"),
    ("lts_dft_kept", TFC, LTS_HEAD,
     "    FreeMemoryBeforeLoadingTrackSpecific = count_free_memory();\n"),
    ("lts_fs_into_fc", TFC, LTS_HEAD,
     "    FreeMemoryBeforeLoadingTrackCommon = count_free_memory();\n"
     "    eDisableFixUpTables = 1;\n"),
    ("lts_tracka_ingame", TFC,
     "    load_resource_file(name, RESOURCE_FILE_TRACK, 0, NULL, 0);",
     "    load_resource_file(name, RESOURCE_FILE_INGAME, 0, NULL, 0);"),
    ("lts_tracka_flags", TFC,
     "    load_resource_file(name, RESOURCE_FILE_TRACK, 0, NULL, 0);",
     "    load_resource_file(name, RESOURCE_FILE_TRACK, 1, NULL, 0);"),
    ("lts_tracka_name", TFC, "TRACKA%d.BUN", "TRACKA%d.LZC"),
    ("lts_trackb_name", TFC, "TRACKB%d.LZC", "TRACKB%d.BUN"),
    ("lts_trackb_cb", TFC,
     "BUNDLE_FLAGS,\n                            GameFlowLoadingTrackSpecificPart1, 0);",
     "BUNDLE_FLAGS,\n                            GameFlowLoadingTrackSpecificPart2, 0);"),
    ("lts_no_rename", TFC,
     "    change_filename_for_hot_chunking(rf, name);\n", ""),
    ("lts_track_unsigned", TFC,
     "    snprintf(name, sizeof name, \"TRACKS\\\\TRACKA%d.BUN\", (int)track);",
     "    snprintf(name, sizeof name, \"TRACKS\\\\TRACKA%u.BUN\", (unsigned)track);"),

    # Its parts.
    ("p1_no_speech", TFC,
     "        bgf_load_current_speech(gTrackFlowGameFlow);", "        (void)0;"),
    ("p1_speech_after_replay", TFC,
     "    if (gTrackFlowGameFlow != NULL)\n"
     "        bgf_load_current_speech(gTrackFlowGameFlow);\n"
     "    if (DemoModeReplayActiveFlag)\n        CALL(gDemoModeReplayLoadFn);\n",
     "    if (DemoModeReplayActiveFlag)\n        CALL(gDemoModeReplayLoadFn);\n"
     "    if (gTrackFlowGameFlow != NULL)\n"
     "        bgf_load_current_speech(gTrackFlowGameFlow);\n"),
    ("p1_replay_ungated", TFC,
     "    if (DemoModeReplayActiveFlag)\n        CALL(gDemoModeReplayLoadFn);",
     "    CALL(gDemoModeReplayLoadFn);"),
    ("p1_replay_positive", TFC,
     "    if (DemoModeReplayActiveFlag)", "    if (DemoModeReplayActiveFlag > 0)"),
    ("p1_sound_param", TFC,
     "gLoadSoundRegionsInGameFn(GameFlowLoadingTrackSpecificPart2, 0);",
     "gLoadSoundRegionsInGameFn(GameFlowLoadingTrackSpecificPart2, 1);"),
    ("p1_sound_cb", TFC,
     "gLoadSoundRegionsInGameFn(GameFlowLoadingTrackSpecificPart2, 0);",
     "gLoadSoundRegionsInGameFn(GameFlowLoadingTrackSpecificPart3, 0);"),
    ("p1_null_stalls", TFC,
     "    else\n        GameFlowLoadingTrackSpecificPart2(0);\n", ""),
    ("p2_cb", TFC,
     "    LoadHudTextures(GameFlowLoadingTrackSpecificPart3);",
     "    LoadHudTextures(GameFlowLoadingTrackSpecificPart4);"),
    ("p3_inverted", TFC,
     "    if (!skip_fe())\n        load_resource_file(\"GLOBAL",
     "    if (skip_fe())\n        load_resource_file(\"GLOBAL"),
    ("p3_flags", TFC,
     "                           RESOURCE_FILE_FLAG_LZCOMPRESSED,\n",
     "                           BUNDLE_FLAGS,\n"),
    ("p3_ingame", TFC,
     "\"GLOBAL\\\\PRERACEANIM.LZC\", RESOURCE_FILE_TRACK,",
     "\"GLOBAL\\\\PRERACEANIM.LZC\", RESOURCE_FILE_INGAME,"),
    ("p3_skip_stalls", TFC,
     "    else\n        GameFlowLoadingTrackSpecificPart4(0);\n", ""),
    ("p3_skip_to_5", TFC,
     "    else\n        GameFlowLoadingTrackSpecificPart4(0);",
     "    else\n        GameFlowLoadingTrackSpecificPart5(0);"),
    ("p4_track_flags_0", TFC,
     "                       RESOURCE_FILE_FLAG_HOTCHUNKABLE, NULL, 0);",
     "                       0, NULL, 0);"),
    ("p4_location_flags_0", TFC,
     "                       RESOURCE_FILE_FLAG_HOTCHUNKABLE,\n"
     "                       GameFlowLoadingTrackSpecificPart5, 0);",
     "                       0,\n                       GameFlowLoadingTrackSpecificPart5, 0);"),
    ("p4_cb_on_track", TFC,
     "                       RESOURCE_FILE_FLAG_HOTCHUNKABLE, NULL, 0);",
     "                       RESOURCE_FILE_FLAG_HOTCHUNKABLE,\n"
     "                       GameFlowLoadingTrackSpecificPart5, 0);"),
    ("p4_track_name", TFC, "TEX%dTRACK.BIN", "TEX%dTRACKS.BIN"),
    ("p4_location_name", TFC, "TEX%dLOCATION.BIN", "TEX%dLOC.BIN"),
    ("p5_flags", TFC,
     "\"GLOBAL\\\\DRIVTEX.BIN\", RESOURCE_FILE_TRACK, 0,",
     "\"GLOBAL\\\\DRIVTEX.BIN\", RESOURCE_FILE_TRACK, 1,"),
    ("p5_ingame", TFC,
     "\"GLOBAL\\\\DRIVTEX.BIN\", RESOURCE_FILE_TRACK, 0,",
     "\"GLOBAL\\\\DRIVTEX.BIN\", RESOURCE_FILE_INGAME, 0,"),
    ("p5_cb_null", TFC,
     "                       GameFlowLoadingTrackSpecificPart6, 0);",
     "                       NULL, 0);"),
    ("p6_visible", TFC,
     "    set_loading_screen(FLAILER_SCREEN_INVISIBLE);",
     "    set_loading_screen(FLAILER_SCREEN_VISIBLE);"),
    ("p6_flow_first", TFC,
     "    set_loading_screen(FLAILER_SCREEN_INVISIBLE);\n"
     "    change_game_flow(BGF_RACING);",
     "    change_game_flow(BGF_RACING);\n"
     "    set_loading_screen(FLAILER_SCREEN_INVISIBLE);"),
    ("p6_no_flow", TFC, "    change_game_flow(BGF_RACING);\n", ""),
    ("p6_flow_track_specific", TFC,
     "    change_game_flow(BGF_RACING);",
     "    change_game_flow(BGF_LOADING_TRACK_SPECIFIC);"),

    # The End of loading.
    ("end_keep_disable", TFC,
     "    eDisableFixUpTables = 0;\n    efix_up_tables();",
     "    efix_up_tables();"),
    ("end_disable_after_fixup", TFC,
     "    eDisableFixUpTables = 0;\n    efix_up_tables();",
     "    efix_up_tables();\n    eDisableFixUpTables = 0;"),
    ("end_no_fixup", TFC,
     "    efix_up_tables();\n    InGameFlag = 1;",
     "    InGameFlag = 1;"),
    ("end_ingame_before_fixup", TFC,
     "    efix_up_tables();\n    InGameFlag = 1;",
     "    InGameFlag = 1;\n    efix_up_tables();"),
    ("end_ingame_late", TFC,
     "    InGameFlag = 1;                     // the jal's delay slot\n\n"
     "    init_collision();",
     "\n    init_collision();\n    InGameFlag = 1;"),
    ("end_ingame_2", TFC,
     "    InGameFlag = 1;", "    InGameFlag = 2;"),
    ("end_body_before_collision", TFC,
     "    init_collision();\n    init_collision_body();",
     "    init_collision_body();\n    init_collision();"),
    ("end_no_contact", TFC,
     "    init_contact();\n    topotree_init_tree", "    topotree_init_tree"),
    ("end_tree_after_smokeables", TFC,
     "    topotree_init_tree(&TheTopologyTree);\n    CALL(gInitSmokeablesFn);",
     "    CALL(gInitSmokeablesFn);\n    topotree_init_tree(&TheTopologyTree);"),
    ("end_physics_no_drivers", TFC,
     "    InitPhysics(RaceParametersNumDriverInfo);", "    InitPhysics(0);"),
    ("end_physics_before_smokeables", TFC,
     "    CALL(gInitSmokeablesFn);\n    // Retail's InitPhysics",
     "    InitPhysics(RaceParametersNumDriverInfo);\n"
     "    CALL(gInitSmokeablesFn);\n    if (0) // Retail's InitPhysics"),
    ("end_sun_before_rain", TFC,
     "    rain_Load();\n    SunTrackLoader();",
     "    SunTrackLoader();\n    rain_Load();"),
    ("end_no_rain", TFC,
     "    rain_Load();\n", ""),
    ("end_rain_unloads", TFC,
     "    rain_Load();\n", "    rain_Unload();\n"),
    ("end_no_sky", TFC,
     "    SkyLoader();\n", ""),
    ("end_no_markers", TFC,
     "    CALL(gInitTrackMarkersFn);\n", ""),
    ("end_paths_before_zones", TFC,
     "    scenery_init_visible_zones();\n    init_track_paths();",
     "    init_track_paths();\n    scenery_init_visible_zones();"),
    ("end_reverse_after_routes", TFC,
     "    TheTrackPathManager.ReverseTrackDirection =\n"
     "        RaceParametersTrackDirection == TRACK_DIRECTION_BACKWARD;\n"
     "    init_track_routes(RaceParametersTrackDirection != TRACK_DIRECTION_BACKWARD);",
     "    init_track_routes(RaceParametersTrackDirection != TRACK_DIRECTION_BACKWARD);\n"
     "    TheTrackPathManager.ReverseTrackDirection =\n"
     "        RaceParametersTrackDirection == TRACK_DIRECTION_BACKWARD;"),
    ("end_reverse_before_paths", TFC,
     "    init_track_paths();\n\n",
     "    TheTrackPathManager.ReverseTrackDirection =\n"
     "        RaceParametersTrackDirection == TRACK_DIRECTION_BACKWARD;\n"
     "    init_track_paths();\n\n"),
    ("end_reverse_not_forward", TFC,
     "        RaceParametersTrackDirection == TRACK_DIRECTION_BACKWARD;",
     "        RaceParametersTrackDirection != TRACK_DIRECTION_FORWARD;"),
    ("end_reverse_raw", TFC,
     "        RaceParametersTrackDirection == TRACK_DIRECTION_BACKWARD;",
     "        RaceParametersTrackDirection;"),
    ("end_routes_forward_is_zero", TFC,
     "    init_track_routes(RaceParametersTrackDirection != TRACK_DIRECTION_BACKWARD);",
     "    init_track_routes(RaceParametersTrackDirection == TRACK_DIRECTION_FORWARD);"),
    ("end_routes_raw", TFC,
     "    init_track_routes(RaceParametersTrackDirection != TRACK_DIRECTION_BACKWARD);",
     "    init_track_routes(!RaceParametersTrackDirection);"),
    ("end_no_reverse", TFC,
     "    TheTrackPathManager.ReverseTrackDirection =\n"
     "        RaceParametersTrackDirection == TRACK_DIRECTION_BACKWARD;\n", ""),
    ("end_world_before_editor", TFC,
     "    CALL(gInitTrackRouteEditorFn);\n    CALL(gInitWorldObjectsFn);",
     "    CALL(gInitWorldObjectsFn);\n    CALL(gInitTrackRouteEditorFn);"),
    ("end_no_animdriver", TFC,
     "    CALL(gInitAnimatedDriverFn);\n", ""),
    ("end_jr2_after_ai", TFC,
     "    WeHaveCheckedIfJR2ServerExists = 0; // InitAIPlans' delay slot\n"
     "    CALL(gInitAIPlansFn);",
     "    CALL(gInitAIPlansFn);\n    WeHaveCheckedIfJR2ServerExists = 0;"),
    ("end_jr2_kept", TFC,
     "    WeHaveCheckedIfJR2ServerExists = 0; // InitAIPlans' delay slot\n", ""),
    ("end_rc_before_ai", TFC,
     "    CALL(gInitAIPlansFn);\n\n" + END_EGG + NEW_RC,
     NEW_RC + "\n    CALL(gInitAIPlansFn);\n\n" + END_EGG),
    ("end_rc_before_egg", TFC, END_EGG + NEW_RC, NEW_RC + "\n" + END_EGG),
    ("end_egg_ungated", TFC, END_EGG, "        CALL(gSetRenderEggFromEasterEggsFn);\n"),
    ("end_egg_ai_only", TFC, END_EGG,
     "    if (!RaceParametersAIDemoMode)\n"
     "        CALL(gSetRenderEggFromEasterEggsFn);\n"),
    ("end_egg_replay_only", TFC, END_EGG,
     "    if (!RaceParametersReplayDemoMode)\n"
     "        CALL(gSetRenderEggFromEasterEggsFn);\n"),
    ("end_rc_kept", TFC,
     "                     ? gNewRaceCoordinatorFn() : NULL;",
     "                     ? gNewRaceCoordinatorFn() : pRaceCoordinator;"),
    ("end_rc_unguarded", TFC, NEW_RC, "    pRaceCoordinator = gNewRaceCoordinatorFn();"),

    # The Begin of unloading the track's part.
    ("uts_disable_0", TFC,
     "    eDisableFixUpTables = 1;\n    InGameFlag = 0;",
     "    eDisableFixUpTables = 0;\n    InGameFlag = 0;"),
    ("uts_ingame_kept", TFC,
     "    eDisableFixUpTables = 1;\n    InGameFlag = 0;",
     "    eDisableFixUpTables = 1;"),
    ("uts_ingame_late", TFC,
     "    InGameFlag = 0;\n    set_loading_screen(FLAILER_SCREEN_VISIBLE);\n"
     "    CALL(gEWaitUntilRenderingDoneFn);",
     "    set_loading_screen(FLAILER_SCREEN_VISIBLE);\n"
     "    CALL(gEWaitUntilRenderingDoneFn);\n    InGameFlag = 0;"),
    ("uts_screen_invisible", TFC,
     "    set_loading_screen(FLAILER_SCREEN_VISIBLE);\n"
     "    CALL(gEWaitUntilRenderingDoneFn);",
     "    set_loading_screen(FLAILER_SCREEN_INVISIBLE);\n"
     "    CALL(gEWaitUntilRenderingDoneFn);"),
    ("uts_screen_after_wait", TFC,
     "    set_loading_screen(FLAILER_SCREEN_VISIBLE);\n"
     "    CALL(gEWaitUntilRenderingDoneFn);",
     "    CALL(gEWaitUntilRenderingDoneFn);\n"
     "    set_loading_screen(FLAILER_SCREEN_VISIBLE);"),
    ("uts_wait_first", TFC,
     "    eDisableFixUpTables = 1;\n    InGameFlag = 0;",
     "    CALL(gEWaitUntilRenderingDoneFn);\n    eDisableFixUpTables = 1;\n"
     "    InGameFlag = 0;"),
    ("uts_no_wait", TFC,
     "    CALL(gEWaitUntilRenderingDoneFn);\n", ""),
    ("uts_rc_delete_flags_1", TFC,
     "        gDeleteRaceCoordinatorFn(pRaceCoordinator, 3);",
     "        gDeleteRaceCoordinatorFn(pRaceCoordinator, 1);"),
    ("uts_rc_null_first", TFC,
     "        gDeleteRaceCoordinatorFn(pRaceCoordinator, 3);\n"
     "    pRaceCoordinator = NULL;",
     "        pRaceCoordinator = NULL;\n"
     "    gDeleteRaceCoordinatorFn(pRaceCoordinator, 3);"),
    ("uts_rc_kept", TFC,
     "        gDeleteRaceCoordinatorFn(pRaceCoordinator, 3);\n"
     "    pRaceCoordinator = NULL;",
     "        gDeleteRaceCoordinatorFn(pRaceCoordinator, 3);"),
    ("uts_rc_null_late", TFC,
     "    pRaceCoordinator = NULL;\n"
     "    if (gUnloadAllTexturesFromFileFn != NULL)\n"
     "        gUnloadAllTexturesFromFileFn(pHudTexturePack);",
     "    if (gUnloadAllTexturesFromFileFn != NULL)\n"
     "        gUnloadAllTexturesFromFileFn(pHudTexturePack);\n"
     "    pRaceCoordinator = NULL;"),
    ("uts_rc_delete_null", TFC,
     "    if (pRaceCoordinator != NULL && gDeleteRaceCoordinatorFn != NULL)",
     "    if (gDeleteRaceCoordinatorFn != NULL)"),
    ("uts_no_hud_unload", TFC,
     "        gUnloadAllTexturesFromFileFn(pHudTexturePack);", "        {}"),
    ("uts_hud_after_ai", TFC,
     "        gUnloadAllTexturesFromFileFn(pHudTexturePack);\n\n"
     "    CALL(gCloseAIPlansFn);",
     "        {}\n\n    CALL(gCloseAIPlansFn);\n"
     "    gUnloadAllTexturesFromFileFn(pHudTexturePack);"),
    ("uts_world_before_anim", TFC,
     "    CALL(gCloseAnimatedDriverFn);\n    CALL(gCloseWorldObjectsFn);",
     "    CALL(gCloseWorldObjectsFn);\n    CALL(gCloseAnimatedDriverFn);"),
    ("uts_zones_before_routes", TFC,
     "    close_track_routes();\n    scenery_close_visible_zones();",
     "    scenery_close_visible_zones();\n    close_track_routes();"),
    ("uts_no_close_routes", TFC,
     "    close_track_routes();\n", ""),
    ("uts_sky_before_sun", TFC,
     "    SunTrackUnloader();\n    SkyUnloader();",
     "    SkyUnloader();\n    SunTrackUnloader();"),
    ("uts_rain_first", TFC,
     "    CALL(gCloseTrackMarkersFn);\n",
     "    rain_Unload();\n    CALL(gCloseTrackMarkersFn);\n"),
    ("uts_no_rain", TFC,
     "    rain_Unload();\n", ""),
    ("uts_smoke_before_physics", TFC,
     "    ClosePhysics();\n    CALL(gCloseSmokeablesFn);",
     "    CALL(gCloseSmokeablesFn);\n    ClosePhysics();"),
    ("uts_paths_before_tree", TFC,
     "    topotree_close_tree(&TheTopologyTree);\n    close_track_paths();",
     "    close_track_paths();\n    topotree_close_tree(&TheTopologyTree);"),
    ("uts_collision_before_body", TFC,
     "    close_collision_body();\n    close_collision();",
     "    close_collision();\n    close_collision_body();"),
    ("uts_no_close_contact", TFC,
     "    close_contact();\n", ""),
    ("uts_files_ingame", TFC,
     "gFindResourceFileFn(RESOURCE_FILE_TRACK)", "gFindResourceFileFn(RESOURCE_FILE_INGAME)"),
    ("uts_files_once", TFC,
     "    while (gFindResourceFileFn != NULL && gUnloadResourceFileFn != NULL\n"
     "           && (file = gFindResourceFileFn(RESOURCE_FILE_TRACK))",
     "    if (gFindResourceFileFn != NULL && gUnloadResourceFileFn != NULL\n"
     "           && (file = gFindResourceFileFn(RESOURCE_FILE_TRACK))"),
    ("uts_files_unguarded", TFC,
     "    while (gFindResourceFileFn != NULL && gUnloadResourceFileFn != NULL\n"
     "           && (file = gFindResourceFileFn(RESOURCE_FILE_TRACK))",
     "    while (gFindResourceFileFn != NULL\n"
     "           && (file = gFindResourceFileFn(RESOURCE_FILE_TRACK))"),
    ("uts_no_sound_regions", TFC,
     "    CALL(gUnLoadSoundRegionsFn);\n", ""),
    ("uts_replay_after_speech", TFC,
     "    CALL(gDemoModeReplayUnloadFn);\n"
     "    if (gTrackFlowGameFlow != NULL)\n"
     "        bgf_unload_current_speech(gTrackFlowGameFlow);\n",
     "    if (gTrackFlowGameFlow != NULL)\n"
     "        bgf_unload_current_speech(gTrackFlowGameFlow);\n"
     "    CALL(gDemoModeReplayUnloadFn);\n"),
    ("uts_no_speech", TFC,
     "        bgf_unload_current_speech(gTrackFlowGameFlow);", "        (void)0;"),
    ("uts_no_slot_cleanup", TFC,
     "    bCleanupAllExpandedSlotPools();\n", ""),
    ("uts_slot_cleanup_early", TFC,
     "    CALL(gUnLoadSoundRegionsFn);\n",
     "    bCleanupAllExpandedSlotPools();\n    CALL(gUnLoadSoundRegionsFn);\n"),
    ("uts_async_once", TFC,
     "    while (gBIsAsyncDoneFn != NULL && !gBIsAsyncDoneFn(NULL))",
     "    if (gBIsAsyncDoneFn != NULL && !gBIsAsyncDoneFn(NULL))"),
    ("uts_async_inverted", TFC,
     "    while (gBIsAsyncDoneFn != NULL && !gBIsAsyncDoneFn(NULL))",
     "    while (gBIsAsyncDoneFn != NULL && gBIsAsyncDoneFn(NULL))"),
    ("uts_async_unguarded", TFC,
     "    while (gBIsAsyncDoneFn != NULL && !gBIsAsyncDoneFn(NULL))",
     "    while (!gBIsAsyncDoneFn(NULL))"),
    ("uts_leak_before_async", TFC, UTS_WAIT + UTS_LEAK, UTS_LEAK + UTS_WAIT),
    ("uts_no_leak_check", TFC, UTS_LEAK, ""),
    ("uts_leak_common", TFC,
     "    check_for_leak(FreeMemoryBeforeLoadingTrackSpecific,",
     "    check_for_leak(FreeMemoryBeforeLoadingTrackCommon,"),
    ("uts_leak_message", TFC,
     "\"Memory Leak - Track Specific\"", "\"Memory Leak - Track Common\""),
    ("uts_leak_after_flow", TFC, UTS_LEAK + UTS_FLOW_BLOCK,
     UTS_FLOW_BLOCK + UTS_LEAK),
    ("uts_skipfe_kept", TFC,
     "        gf->skipFE = 0;\n", ""),
    ("uts_skipfe_after_change", TFC, UTS_FLOW,
     UTS_FLOW.replace("        gf->skipFE = 0;\n", "") + "        gf->skipFE = 0;\n"),
    ("uts_pending_ignored", TFC,
     "pending != BGF_NONE ? pending\n"
     "                                                 : BGF_UNLOADING_TRACK_COMMON",
     "BGF_UNLOADING_TRACK_COMMON"),
    ("uts_default_frontend", TFC,
     "                                                 : BGF_UNLOADING_TRACK_COMMON,",
     "                                                 : BGF_LOADING_FRONTEND,"),
    ("uts_pending_kept", TFC,
     "                         BGF_NONE);\n    }", "                         pending);\n    }"),
    ("uts_pending_positive", TFC,
     "pending != BGF_NONE ? pending", "pending > BGF_NONE ? pending"),
    ("uts_eggs_ungated", TFC, UTS_EGGS,
     "    {\n        CALL(gResetRenderEggsFn);\n"
     "        CALL(gClearTemporaryEasterEggsFn);\n    }\n"),
    ("uts_eggs_ai_only", TFC,
     "    if (!RaceParametersAIDemoMode && !RaceParametersReplayDemoMode) {",
     "    if (!RaceParametersAIDemoMode) {"),
    ("uts_eggs_replay_only", TFC,
     "    if (!RaceParametersAIDemoMode && !RaceParametersReplayDemoMode) {",
     "    if (!RaceParametersReplayDemoMode) {"),
    ("uts_eggs_swapped", TFC,
     "        CALL(gResetRenderEggsFn);\n        CALL(gClearTemporaryEasterEggsFn);",
     "        CALL(gClearTemporaryEasterEggsFn);\n        CALL(gResetRenderEggsFn);"),
    ("uts_no_clear_eggs", TFC,
     "        CALL(gClearTemporaryEasterEggsFn);\n", ""),
    ("uts_eggs_before_flow", TFC,
     "\n    if (gTrackFlowGameFlow != NULL) {\n",
     "\n" + UTS_EGGS + "    if (gTrackFlowGameFlow != NULL) {\n"),

    # The Begin of unloading the common part.
    ("utc_files_track", TFC,
     "gFindResourceFileFn(RESOURCE_FILE_INGAME)", "gFindResourceFileFn(RESOURCE_FILE_TRACK)"),
    ("utc_files_once", TFC, UTC_FILES,
     UTC_FILES.replace("    while (", "    if (", 1)),
    ("utc_files_unguarded", TFC, UTC_FILES,
     UTC_FILES.replace(" && gUnloadResourceFileFn != NULL", "", 1)),
    ("utc_no_delete_dups", TFC,
     "    CALL(gEDeleteAllDuplicatedSolidsFn);\n", ""),
    ("utc_dups_after_cars", TFC,
     "    CALL(gEDeleteAllDuplicatedSolidsFn);\n"
     "    carloader_unload_everything(&TheCarLoader);\n",
     "    carloader_unload_everything(&TheCarLoader);\n"
     "    CALL(gEDeleteAllDuplicatedSolidsFn);\n"),
    ("utc_dups_first", TFC, UTC_FILES + "    CALL(gEDeleteAllDuplicatedSolidsFn);\n",
     "    CALL(gEDeleteAllDuplicatedSolidsFn);\n" + UTC_FILES),
    ("utc_no_unload_cars", TFC,
     "    carloader_unload_everything(&TheCarLoader);\n", ""),
    ("utc_leak_specific", TFC,
     "    check_for_leak(FreeMemoryBeforeLoadingTrackCommon,",
     "    check_for_leak(FreeMemoryBeforeLoadingTrackSpecific,"),
    ("utc_leak_first", TFC, UTC_FILES, UTC_LEAK + UTC_FILES),
    ("utc_leak_after_flow", TFC,
     UTC_LEAK + "    change_game_flow(BGF_LOADING_FRONTEND);",
     "    change_game_flow(BGF_LOADING_FRONTEND);\n" + UTC_LEAK),
    ("utc_no_leak_check", TFC, UTC_LEAK, ""),
    ("utc_flow_unloading", TFC,
     "    change_game_flow(BGF_LOADING_FRONTEND);",
     "    change_game_flow(BGF_UNLOADING_TRACK_COMMON);"),
    ("utc_no_flow", TFC, "    change_game_flow(BGF_LOADING_FRONTEND);\n", ""),
]

# Mutations that survive because they change nothing the image can tell.
EQUIVALENT = {
    # Port-only: the image has no seams. UnloadResourceFile is what takes a
    # file off the list FindResourceFile walks, so Find set with Unload NULL
    # spins in the image and in the port without the guard alike, and the
    # harness sets both or neither.
    "uts_files_unguarded",
    "utc_files_unguarded",
}


def mutate_pass(only=None):
    todo = [m for m in MUTATIONS if only is None or m[0] in only]
    if only:
        unknown = set(only) - {m[0] for m in MUTATIONS}
        if unknown:
            print("no such mutation: %s" % ", ".join(sorted(unknown)))
            return 1
    sc = script()
    recs = records()
    base = model(sc, recs)
    caught, survived, missing, equivalent = 0, [], [], []
    scdir = tempfile.TemporaryDirectory()
    scp = Path(scdir.name) / "scenarios.txt"
    scp.write_text(encode(sc, recs))
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

    sc = script()
    recs = records()
    lines = model(sc, recs)
    with tempfile.TemporaryDirectory() as tmp:
        exe = build_harness(tmp)
        scp = Path(tmp) / "scenarios.txt"
        scp.write_text(encode(sc, recs))
        out = Path(tmp) / "harness.txt"
        rc = run_harness(exe, scp, out)
        harness = out.read_text().splitlines()

    if args.dump:
        d_ = Path(args.dump)
        d_.parent.mkdir(parents=True, exist_ok=True)
        d_.with_suffix(".model").write_text(NL.join(lines) + NL)
        d_.with_suffix(".harness").write_text(NL.join(harness) + NL)

    n = diff(lines, harness)
    ops = sum(len(s) for s in sc)
    print("%d scenarios, %d ops, %d lines, %d differ"
          % (len(sc), ops, len(harness), n))
    sys.exit(1 if (n or rc) else 0)


if __name__ == "__main__":
    main()
