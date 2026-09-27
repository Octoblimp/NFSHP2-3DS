#!/usr/bin/env python3
"""Cross-check 3DS Files/source/trackflow.c -- EndGameFlowLoadingTrackSpecific
and BeginGameFlowUnloadingTrackSpecific -- against the image itself, run in
mipsemu.

The model is the image: both functions run as shipped, with every callee
stubbed. Each stub prints its name, its arguments, and the globals the two
steps write, read at the moment of the call:

    ig   InGameFlag                        gp-21960
    dft  eDisableFixUpTables               gp-25520
    rev  TheTrackPathManager.ReverseTrackDirection   0x0031376c
    jr2  WeHaveCheckedIfJR2ServerExists    gp-22284
    rc   pRaceCoordinator                  gp-22720
    sfe  SkipFE                            gp-23788

so a store that moves across a call shows. The harness links trackflow.c
with the same stubs, by name for the callees the port has and through the
seams for the rest, and prints the same lines.

**The pointers.** The RaceCoordinator a scenario starts with prints rc0 and
the one the End makes rc; the HUD pack hud; TheTopologyTree TT; the k-th
file FindResourceFile hands out fk. The three calls made on an object the
port has no global for -- DemoModeReplay::UnloadResourceFile,
LanguageManager::UnloadAllLanguages and SlotPoolManager::
CleanupExpandedSlotPools -- print only their names, and the model says so
if the image passed anything but TheDemoModeReplay, TheLanguageManager or
TheSlotPoolManager.

**The seams.** A scenario with null=1 clears every seam on the port's side
and makes the model's stubs for those callees silent: FindResourceFile
finds nothing, bIsAsyncDone is done, and the RaceCoordinator is NULL. The
callees the port calls directly still print.

Scenarios: both track directions and the values either side of backward;
the driver count; the demo disc on and off; a RaceCoordinator or none; the
HUD pack or none; 0 to 3 resource files; bIsAsyncDone busy 0 to 4 times;
nothing pending and something; and the steps run End-then-Begin, alone,
twice, and backwards.

    python tools/trackflow_check.py
    python tools/trackflow_check.py --mutate [--only a,b]
    python tools/trackflow_check.py --dump out/trackflow
"""
import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hostbuild
import physicscar_check as pcc
from mipsemu import Emu, M32, s32

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

HARNESS = "tools/src/trackflow_test.c"
TFC = "3DS Files/source/trackflow.c"
SOURCES = [HARNESS, TFC]

HARNESS_TIMEOUT = 60

# ================================================================ the image

GP = 0x00328bf0
IN_GAME = GP - 21960
HUD_PACK = GP - 21964
PENDING = GP - 21948
DISABLE_FIXUP = GP - 25520
JR2 = GP - 22284
RACE_COORD = GP - 22720
SKIP_FE = GP - 23788
REVERSE = 0x0031376c                 # TheTrackPathManager + 4
TRACK_DIR = 0x0031252c               # TheRaceParameters + 12
NUM_DRIVERS = 0x00312814             # TheRaceParameters + 756
DEMO_DISC = 0x002e8120               # TheDemoDiscManager.bActive
TOPO_TREE = 0x002f14c8
DEMO_REPLAY = 0x002e89b0
LANGUAGES = 0x00313c90
SLOT_POOLS = 0x00315268

END = 0x001645e8
BEGIN = 0x001646e0

# Where the model puts the objects a scenario names.
RC0, RC_NEW, HUD, FILES = 0x01000000, 0x01000100, 0x01000200, 0x01001000

# (address, name, kind, is_seam). The kinds say how the arguments print.
CALLEES = [
    (0x00103790, "eFixUpTables", "", False),
    (0x0020b238, "InitCollision", "", False),
    (0x001cb760, "InitCollisionBody", "", False),
    (0x001ca170, "InitContact", "", False),
    (0x0014fbb8, "InitTree", "ptr", False),
    (0x0020bb50, "InitSmokeables", "", True),
    (0x00135068, "InitPhysics", "drivers", False),
    (0x0011ce18, "SkyLoader", "", False),
    (0x00128bf8, "rain_Load", "", True),
    (0x00123de0, "SunTrackLoader", "", False),
    (0x001f18f0, "InitDebugTopology", "", True),
    (0x001b4338, "InitTrackMarkers", "", True),
    (0x0014cf18, "InitVisibleZones", "", False),
    (0x001f5f48, "InitTrackPaths", "", False),
    (0x001b9188, "InitTrackRoutes", "int", False),
    (0x001bbc78, "InitTrackRouteEditor", "", True),
    (0x001c3778, "InitWorldObjects", "", True),
    (0x0019ee50, "InitAnimatedDriver", "", True),
    (0x001bbf00, "InitAIPlans", "", True),
    (0x0023f0b8, "bMalloc", "malloc", True),
    (0x00147170, "RaceCoordinator", "ctor", True),
    (0x0014a3b8, "SetFlailerScreenVisibility", "flailer", True),
    (0x00110770, "eWaitUntilRenderingDone", "", True),
    (0x00147288, "~RaceCoordinator", "ptr_int", True),
    (0x001a2850, "UnloadAllTexturesFromFile", "ptr", True),
    (0x001bbf30, "CloseAIPlans", "", True),
    (0x0019f070, "CloseAnimatedDriver", "", True),
    (0x001c37a8, "CloseWorldObjects", "", True),
    (0x001bbcb0, "CloseTrackRouteEditor", "", True),
    (0x001b9428, "CloseTrackRoutes", "", False),
    (0x0014cf68, "CloseVisibleZones", "", False),
    (0x001b43a0, "CloseTrackMarkers", "", True),
    (0x001f18f8, "CloseDebugTopology", "", True),
    (0x00123ea0, "SunTrackUnloader", "", False),
    (0x0011ced8, "SkyUnloader", "", False),
    (0x00128c00, "rain_Unload", "", True),
    (0x001351b0, "ClosePhysics", "", False),
    (0x0020bb58, "CloseSmokeables", "", True),
    (0x0014fc00, "CloseTree", "ptr", False),
    (0x001f5f58, "CloseTrackPaths", "", False),
    (0x001ca1a0, "CloseContact", "", False),
    (0x001cb880, "CloseCollisionBody", "", False),
    (0x0020b268, "CloseCollision", "", False),
    (0x0018fd20, "UnloadResourceFile", "ptr", True),
    (0x0018fe88, "FindResourceFile", "find", True),
    (0x001a5ef0, "UnLoadSoundRegions", "", True),
    (0x0013cfd0, "DemoModeReplayUnload", DEMO_REPLAY, True),
    (0x0020b010, "UnloadAllLanguages", LANGUAGES, True),
    (0x00240028, "CleanupExpandedSlotPools", SLOT_POOLS, False),
    (0x0023c670, "bIsAsyncDone", "async", True),
    (0x0023f280, "bCountFreeMemory", "int", True),
    (0x001636e8, "ChangeGameFlow", "int_int", False),
]


class Scenario(object):
    FIELDS = ("dir", "ndi", "demo", "rc", "hud", "nfiles", "nbusy",
              "pending", "sfe", "ig", "dft", "rev", "jr2", "null")

    def __init__(self, ops, **kw):
        self.ops = ops
        for f in self.FIELDS:
            setattr(self, f, kw.pop(f, 0))
        if kw:
            raise TypeError("unknown fields: %s" % ", ".join(kw))

    def line(self):
        return "S " + " ".join(str(getattr(self, f)) for f in self.FIELDS) \
            + " " + self.ops


def script():
    S = Scenario
    sc = [
        # The plain race: forward, nothing pending, the End then the Begin.
        S("EB", dir=0, ndi=8, rc=1, hud=1),
        # Backward, the demo disc on, files and a busy reader, pending.
        S("EB", dir=1, ndi=1, demo=1, hud=1, nfiles=2, nbusy=3, pending=5,
          sfe=1),
        # Either side of backward, and the far ends.
        S("E", dir=2, ndi=0, ig=5, dft=3, rev=9, jr2=4),
        S("E", dir=-1, ndi=6, rev=1),
        S("E", dir=0x101, ndi=-3, rev=-1),
        S("E", dir=1, ndi=0x7fffffff, dft=1),
        # The Begin alone: a RaceCoordinator or none, the HUD pack or none.
        S("B", rc=1, hud=0, nfiles=1, nbusy=1, pending=8, sfe=7, ig=1),
        S("B", rc=0, hud=1, nfiles=3, nbusy=4, pending=-1, sfe=1, ig=1,
          dft=0),
        S("B", demo=2, pending=1, jr2=3),
        S("B", demo=-1, rc=1, pending=9),
        # Twice, and backwards.
        S("EE", dir=1, ndi=2, rc=1),
        S("BB", rc=1, hud=1, nfiles=2, nbusy=2, pending=3),
        S("BE", dir=0, ndi=4, rc=1, hud=1, nfiles=1, pending=2, sfe=1),
        S("EBEB", dir=1, ndi=3, nfiles=2, nbusy=1, pending=4, sfe=1),
        # Every seam NULL.
        S("EB", dir=1, ndi=5, rc=1, hud=1, nfiles=2, nbusy=2, pending=6,
          sfe=1, null=1),
        S("BE", dir=0, ndi=2, rc=1, demo=1, nfiles=1, null=1),
    ]
    return sc


class BigEmu(Emu):
    RAM = 128 << 20


class Model(object):
    def __init__(self):
        self.out = []
        self.e = BigEmu(ieee=True)
        self.sc = None
        for addr, name, kind, seam in CALLEES:
            self.e.stub(addr, self.make_stub(name, kind, seam))

    def emit(self, s):
        self.out.append(s)

    def label(self, a):
        a &= M32
        if a == 0:
            return "null"
        if a == RC0:
            return "rc0"
        if a == RC_NEW:
            return "rc"
        if a == HUD:
            return "hud"
        if a == TOPO_TREE:
            return "TT"
        if FILES <= a < FILES + 64 * 4 and (a - FILES) % 4 == 0:
            return "f%d" % ((a - FILES) // 4)
        return "x%08x" % a

    def snap(self):
        e = self.e
        return " | ig=%d dft=%d rev=%d jr2=%d rc=%s sfe=%d" % (
            s32(e.u32(IN_GAME)), s32(e.u32(DISABLE_FIXUP)),
            s32(e.u32(REVERSE)), s32(e.u32(JR2)),
            self.label(e.u32(RACE_COORD)), s32(e.u32(SKIP_FE)))

    def say(self, s):
        self.emit("  " + s + self.snap())

    def make_stub(self, name, kind, seam):
        def stub(em):
            a = [em.reg[4 + i] & M32 for i in range(4)]
            quiet = seam and self.sc.null
            ret = 0
            text = name
            if kind == "ptr":
                text += " " + self.label(a[0])
            elif kind == "int":
                text += " %d" % s32(a[0])
            elif kind == "int_int":
                text += " %d %d" % (s32(a[0]), s32(a[1]))
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
                f = 0
                if not quiet and self.found < self.sc.nfiles:
                    self.found += 1
                    f = FILES + 4 * self.found
                text += " %d -> %s" % (s32(a[0]), self.label(f))
                ret = f
            elif kind == "async":
                if quiet:
                    ret = 1
                else:
                    ret = 1 if self.busy <= 0 else 0
                    if self.busy > 0:
                        self.busy -= 1
                text += " %s -> %d" % (self.label(a[0]), ret)
            elif isinstance(kind, int):
                if a[0] != kind:
                    text += " on x%08x, not x%08x" % (a[0], kind)
            if kind == "int" and name == "bCountFreeMemory":
                ret = 12345
            if not quiet:
                self.say(text)
            return ret
        return stub

    def cstr(self, a, n=64):
        b = bytearray()
        while len(b) < n and self.e.mem[a]:
            b.append(self.e.mem[a])
            a += 1
        return b.decode("latin-1")

    def run(self, scenarios):
        e = self.e
        for k, sc in enumerate(scenarios):
            self.sc = sc
            self.found = 0
            self.busy = sc.nbusy
            e.put32(TRACK_DIR, sc.dir)
            e.put32(NUM_DRIVERS, sc.ndi)
            e.put32(DEMO_DISC, sc.demo)
            e.put32(RACE_COORD, RC0 if sc.rc else 0)
            e.put32(HUD_PACK, HUD if sc.hud else 0)
            e.put32(PENDING, sc.pending)
            e.put32(SKIP_FE, sc.sfe)
            e.put32(IN_GAME, sc.ig)
            e.put32(DISABLE_FIXUP, sc.dft)
            e.put32(REVERSE, sc.rev)
            e.put32(JR2, sc.jr2)
            self.emit("scenario %d %s" % (k, sc.ops))
            for o in sc.ops:
                if o == "E":
                    self.emit(" end")
                    e.call(END, limit=100000)
                    self.say("end done")
                else:
                    self.emit(" begin")
                    e.call(BEGIN, limit=100000)
                    self.say("begin done")
        return self.out


def model(scenarios):
    return Model().run(scenarios)


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


def encode(scenarios):
    return NL.join(s.line() for s in scenarios) + NL


diff = pcc.diff

# ============================================================ the mutations

MUTATIONS = [
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
     "    CALL(gInitSmokeablesFn);\n    InitPhysics(RaceParametersNumDriverInfo);",
     "    InitPhysics(RaceParametersNumDriverInfo);\n    CALL(gInitSmokeablesFn);"),
    ("end_sun_before_rain", TFC,
     "    CALL(gRainLoadFn);\n    SunTrackLoader();",
     "    SunTrackLoader();\n    CALL(gRainLoadFn);"),
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
     "    CALL(gInitAIPlansFn);\n\n    pRaceCoordinator",
     "    pRaceCoordinator = gNewRaceCoordinatorFn != NULL\n"
     "                     ? gNewRaceCoordinatorFn() : NULL;\n"
     "    CALL(gInitAIPlansFn);\n    if (0) pRaceCoordinator"),
    ("end_rc_kept", TFC,
     "                     ? gNewRaceCoordinatorFn() : NULL;",
     "                     ? gNewRaceCoordinatorFn() : pRaceCoordinator;"),
    ("end_rc_unguarded", TFC,
     "    pRaceCoordinator = gNewRaceCoordinatorFn != NULL\n"
     "                     ? gNewRaceCoordinatorFn() : NULL;",
     "    pRaceCoordinator = gNewRaceCoordinatorFn();"),
    ("end_call_unguarded", TFC,
     "#define CALL(fn) do { if ((fn) != NULL) (fn)(); } while (0)",
     "#define CALL(fn) do { (fn)(); } while (0)"),

    # The Begin of unloading.
    ("begin_disable_0", TFC,
     "    eDisableFixUpTables = 1;\n    InGameFlag = 0;",
     "    eDisableFixUpTables = 0;\n    InGameFlag = 0;"),
    ("begin_ingame_kept", TFC,
     "    eDisableFixUpTables = 1;\n    InGameFlag = 0;",
     "    eDisableFixUpTables = 1;"),
    ("begin_ingame_late", TFC,
     "    eDisableFixUpTables = 1;\n    InGameFlag = 0;",
     "    eDisableFixUpTables = 1;\n    CALL(gEWaitUntilRenderingDoneFn);\n"
     "    InGameFlag = 0;"),
    ("begin_demo_ignored", TFC,
     "    if (!TheDemoDiscManager.bActive && gSetFlailerScreenVisibilityFn != NULL)",
     "    if (gSetFlailerScreenVisibilityFn != NULL)"),
    ("begin_demo_inverted", TFC,
     "    if (!TheDemoDiscManager.bActive && gSetFlailerScreenVisibilityFn != NULL)",
     "    if (TheDemoDiscManager.bActive && gSetFlailerScreenVisibilityFn != NULL)"),
    ("begin_demo_eq1", TFC,
     "    if (!TheDemoDiscManager.bActive && gSetFlailerScreenVisibilityFn != NULL)",
     "    if (TheDemoDiscManager.bActive != 1 && gSetFlailerScreenVisibilityFn != NULL)"),
    ("begin_flailer_visible", TFC,
     "        gSetFlailerScreenVisibilityFn(BGF_SCREEN_LOADING_TRACK, 0);",
     "        gSetFlailerScreenVisibilityFn(BGF_SCREEN_LOADING_TRACK, 1);"),
    ("begin_flailer_unguarded", TFC,
     "    if (!TheDemoDiscManager.bActive && gSetFlailerScreenVisibilityFn != NULL)",
     "    if (!TheDemoDiscManager.bActive)"),
    ("begin_wait_first", TFC,
     "    eDisableFixUpTables = 1;\n    InGameFlag = 0;",
     "    CALL(gEWaitUntilRenderingDoneFn);\n    eDisableFixUpTables = 1;\n"
     "    InGameFlag = 0;"),
    ("begin_no_wait", TFC,
     "    CALL(gEWaitUntilRenderingDoneFn);\n", ""),
    ("begin_rc_delete_flags_1", TFC,
     "        gDeleteRaceCoordinatorFn(pRaceCoordinator, 3);",
     "        gDeleteRaceCoordinatorFn(pRaceCoordinator, 1);"),
    ("begin_rc_null_first", TFC,
     "        gDeleteRaceCoordinatorFn(pRaceCoordinator, 3);\n"
     "    pRaceCoordinator = NULL;",
     "        pRaceCoordinator = NULL;\n"
     "    gDeleteRaceCoordinatorFn(pRaceCoordinator, 3);"),
    ("begin_rc_kept", TFC,
     "        gDeleteRaceCoordinatorFn(pRaceCoordinator, 3);\n"
     "    pRaceCoordinator = NULL;",
     "        gDeleteRaceCoordinatorFn(pRaceCoordinator, 3);"),
    ("begin_rc_null_late", TFC,
     "    pRaceCoordinator = NULL;\n"
     "    if (gUnloadAllTexturesFromFileFn != NULL)\n"
     "        gUnloadAllTexturesFromFileFn(pHudTexturePack);",
     "    if (gUnloadAllTexturesFromFileFn != NULL)\n"
     "        gUnloadAllTexturesFromFileFn(pHudTexturePack);\n"
     "    pRaceCoordinator = NULL;"),
    ("begin_rc_delete_null", TFC,
     "    if (pRaceCoordinator != NULL && gDeleteRaceCoordinatorFn != NULL)",
     "    if (gDeleteRaceCoordinatorFn != NULL)"),
    ("begin_no_hud_unload", TFC,
     "        gUnloadAllTexturesFromFileFn(pHudTexturePack);", "        {}"),
    ("begin_hud_after_ai", TFC,
     "        gUnloadAllTexturesFromFileFn(pHudTexturePack);\n\n"
     "    CALL(gCloseAIPlansFn);",
     "        {}\n\n    CALL(gCloseAIPlansFn);\n"
     "    gUnloadAllTexturesFromFileFn(pHudTexturePack);"),
    ("begin_world_before_anim", TFC,
     "    CALL(gCloseAnimatedDriverFn);\n    CALL(gCloseWorldObjectsFn);",
     "    CALL(gCloseWorldObjectsFn);\n    CALL(gCloseAnimatedDriverFn);"),
    ("begin_zones_before_routes", TFC,
     "    close_track_routes();\n    scenery_close_visible_zones();",
     "    scenery_close_visible_zones();\n    close_track_routes();"),
    ("begin_no_close_routes", TFC,
     "    close_track_routes();\n", ""),
    ("begin_sky_before_sun", TFC,
     "    SunTrackUnloader();\n    SkyUnloader();",
     "    SkyUnloader();\n    SunTrackUnloader();"),
    ("begin_rain_first", TFC,
     "    CALL(gCloseTrackMarkersFn);\n",
     "    CALL(gRainUnloadFn);\n    CALL(gCloseTrackMarkersFn);\n"),
    ("begin_smoke_before_physics", TFC,
     "    ClosePhysics();\n    CALL(gCloseSmokeablesFn);",
     "    CALL(gCloseSmokeablesFn);\n    ClosePhysics();"),
    ("begin_paths_before_tree", TFC,
     "    topotree_close_tree(&TheTopologyTree);\n    close_track_paths();",
     "    close_track_paths();\n    topotree_close_tree(&TheTopologyTree);"),
    ("begin_collision_before_body", TFC,
     "    close_collision_body();\n    close_collision();",
     "    close_collision();\n    close_collision_body();"),
    ("begin_no_close_contact", TFC,
     "    close_contact();\n", ""),
    ("begin_files_type_2", TFC,
     "#define TRACK_RESOURCE_FILE 3", "#define TRACK_RESOURCE_FILE 2"),
    ("begin_files_once", TFC,
     "    while (gFindResourceFileFn != NULL && gUnloadResourceFileFn != NULL",
     "    if (gFindResourceFileFn != NULL && gUnloadResourceFileFn != NULL"),
    ("begin_files_unguarded", TFC,
     "    while (gFindResourceFileFn != NULL && gUnloadResourceFileFn != NULL",
     "    while (gFindResourceFileFn != NULL"),
    ("begin_no_sound_regions", TFC,
     "    CALL(gUnLoadSoundRegionsFn);\n",
     ""),
    ("begin_languages_before_replay", TFC,
     "    CALL(gDemoModeReplayUnloadFn);\n    CALL(gUnloadAllLanguagesFn);",
     "    CALL(gUnloadAllLanguagesFn);\n    CALL(gDemoModeReplayUnloadFn);"),
    ("begin_no_slot_cleanup", TFC,
     "    bCleanupAllExpandedSlotPools();\n", ""),
    ("begin_slot_cleanup_early", TFC,
     "    CALL(gUnLoadSoundRegionsFn);\n",
     "    bCleanupAllExpandedSlotPools();\n    CALL(gUnLoadSoundRegionsFn);\n"),
    ("begin_async_once", TFC,
     "    while (gBIsAsyncDoneFn != NULL && !gBIsAsyncDoneFn(NULL))",
     "    if (gBIsAsyncDoneFn != NULL && !gBIsAsyncDoneFn(NULL))"),
    ("begin_async_inverted", TFC,
     "    while (gBIsAsyncDoneFn != NULL && !gBIsAsyncDoneFn(NULL))",
     "    while (gBIsAsyncDoneFn != NULL && gBIsAsyncDoneFn(NULL))"),
    ("begin_async_unguarded", TFC,
     "    while (gBIsAsyncDoneFn != NULL && !gBIsAsyncDoneFn(NULL))",
     "    while (!gBIsAsyncDoneFn(NULL))"),
    ("begin_countfree_0", TFC,
     "        (void)gBCountFreeMemoryFn(16);", "        (void)gBCountFreeMemoryFn(0);"),
    ("begin_countfree_before_async", TFC,
     "    // bIsAsyncDone(NULL): every queued read, not one file.\n",
     "    if (gBCountFreeMemoryFn != NULL)\n        (void)gBCountFreeMemoryFn(16);\n"),
    ("begin_skipfe_kept", TFC,
     "        gf->skipFE = 0;\n", ""),
    ("begin_skipfe_after_change", TFC,
     "        gf->skipFE = 0;\n"
     "        bgf_change_state(gf, pending != 0 ? pending : UNLOADING_TRACK_COMMON,\n"
     "                         0);",
     "        bgf_change_state(gf, pending != 0 ? pending : UNLOADING_TRACK_COMMON,\n"
     "                         0);\n        gf->skipFE = 0;"),
    ("begin_pending_ignored", TFC,
     "pending != 0 ? pending : UNLOADING_TRACK_COMMON", "UNLOADING_TRACK_COMMON"),
    ("begin_default_7", TFC,
     "#define UNLOADING_TRACK_COMMON 8", "#define UNLOADING_TRACK_COMMON 7"),
    ("begin_pending_kept", TFC,
     "                         0);", "                         pending);"),
    ("begin_pending_positive", TFC,
     "pending != 0 ? pending", "pending > 0 ? pending"),
]

# Mutations that survive because they change nothing the image can tell.
EQUIVALENT = {
    # Port-only: the image has no seams. UnloadResourceFile is what takes a
    # file off the list FindResourceFile walks, so Find set with Unload NULL
    # spins in the image and in the port without the guard alike, and the
    # harness sets both or neither.
    "begin_files_unguarded",
}


def mutate_pass(only=None):
    todo = [m for m in MUTATIONS if only is None or m[0] in only]
    if only:
        unknown = set(only) - {m[0] for m in MUTATIONS}
        if unknown:
            print("no such mutation: %s" % ", ".join(sorted(unknown)))
            return 1
    sc = script()
    base = model(sc)
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
    lines = model(sc)
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
    print("%d scenarios, %d lines, %d differ" % (len(sc), len(harness), n))
    sys.exit(1 if (n or rc) else 0)


if __name__ == "__main__":
    main()
