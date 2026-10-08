#!/usr/bin/env python3
"""Cross-check Car's fourth slice -- the movement and control modes --
against the image itself, run in mipsemu.

    3DS Files/source/carmodes.{c,h}      Car::SetControlMode, SetMovementMode,
                                         SetToPhysicsMode, SetFrictionBoost;
                                         NullMover; the inlined NullController;
                                         the eight constructor seams.
    3DS Files/source/carcontroller.c     CarController's eight and
                                         NullController's eight, and their
                                         two tables.
    3DS Files/source/carcollisionbody.c  CarCollisionBody's SetupPhysicsPointers
                                         and SetToPhysicsMode.
    3DS Files/source/cardriver.c         NullDriver's five and both driver
                                         tables, called through them.
    3DS Files/source/carreset.c          Car::ResetCore, ResetToPosition,
                                         ResetToRoutePoint, DebugSetPosition.
    3DS Files/source/replay.c            ReplayManager::RegisterInterestingEvent
                                         and InvalidateInterestingEvents.
    3DS Files/source/carrace.c           Car's slice nine: GetDistanceAndSpeed,
                                         the blown tires, PleaseResetMeLater,
                                         GetDrivingLineSpeed, DeliverMeFromEvil.

The oracle and the machinery are mellowmover_check's and physicscar_check's,
imported: the header parse and the check against mdebug, the generated dump
functions, the emulator's stubs for the slot pools, the terrain and the
ticker. What is this slice's is here: the general heap, the stand-ins for
the eight classes task 26 has not ported, the labels, and the scenarios.

**The heap.** Every `new` in the four methods but NullMover's and
MellowMover's is `bMalloc(size, name, 0, 16)`, and every delete is
`__builtin_delete`. Both sides log each one -- the name, the image's size
(the harness maps the five ported records' host sizes back), the flags
and the pool -- fill a new block with 0xa5 and a freed one with 0xdd, and
never reuse either. So a field a constructor forgets shows as 0xa5, and a
read of a destroyed object as 0xdd, on both sides alike.

**The stand-ins.** TrafficCar, DeliveryMover, CopMover, BeltMover,
RealController, AIDriver, TrafficDriver and CopDriver are task 26's. In the
model their constructors are stubbed by symbol; in the harness the seams
point at the same stand-ins. RealController is ported now, and
realcontroller_check.py checks it; it stays a stand-in here so that this
checker sees only Car's side of the seam, and only its size is the real
one's. A mover's writes its vptr; a controller's
writes pCar, a fresh stand-in driver and its vptr. Their tables are at
fixed addresses above the image, installed on both sides, and every entry
the four methods reach logs its `this` and its arguments.

**Labels during a call** are the fixed objects and the heap's blocks only.
The mover being torn down is half freed then, and the port's slot pools
reuse what the model's never do, so a component's name would mean
different memory on the two sides. After each call the dump names the new
mover's components as well.

**Scenarios.** The six tables, slot by slot, against the port's function
map. Every ordered pair of movement modes, as one Eulerian circuit, and
every pair of control modes; then control switches under the two physics
movers. SetToPhysicsMode with no controller, the null one and a stand-in,
in each movement mode; the collision body's two methods on each kind of
`other` and each PhysicsMode; SetFrictionBoost in each mode. NullMover,
NullController and NullDriver called through their own tables, and the
three destructors without the delete bit.

**The resets** are last. The four take the car out of its movement mode and
put it back, so each is run under the null, physics, mellow and a stand-in
mover, and under the null and a stand-in controller, whose entries 40, 72
and 80 and whose driver's 48 log. The ground is the physics checkers'
plane, asked for through `GetElevation` with no normal;
`ClearInterestBBox` logs. The track path is a real one: a looping circle
loaded through `LoaderTrackPath`, its QuickSplines' heap unlogged on both
sides, so PathDirection turns and DebugSetPosition's heading is relative
to something. The replay is four snapshots, of which one is named
INSTANT_REPLAY and three nearly.

**The stack** is filled at each of the four's entries with one poison, and
the whole run done again with another. Every line the two runs print
alike is compared as it is. A line that differs may do so only in the
fourth lane of one of PAD_LANES -- the w that bNormalize and a three-store
bVector3 leave to the stack, which the port writes as 0 -- and that token
becomes `*`, which matches whatever the port printed. Any other
difference stops the check.

Slice ten, Car::TriggerCarTerrainEffects, is retail's now, and
careffects_check.py checks it against the retail image.

    python tools/carmode_check.py
    python tools/carmode_check.py --mutate
    python tools/carmode_check.py --dump out/carmode
"""
import argparse
import math
import os
import struct
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import difficulty_check as dcc
import hostbuild
import mellowmover_check as mmc
import physicscar_check as pcc
import trackpath_check as tpc
from mipsemu import M32, s32
from physicscar_check import LAYOUT, OFF, fb, hexw

ROOT = pcc.ROOT
NL = pcc.NL
HARNESS = ROOT / "tools" / "src" / "carmode_test.c"
CMC = "3DS Files/source/carmodes.c"
CMH = "3DS Files/source/carmodes.h"
CCC = "3DS Files/source/carcontroller.c"
CBC = "3DS Files/source/carcollisionbody.c"
CDC = "3DS Files/source/cardriver.c"
CRC = "3DS Files/source/carreset.c"
RPC = "3DS Files/source/replay.c"
CVC = "3DS Files/source/carmove.c"
DIC = "3DS Files/source/difficultyinfo.c"
DIH = "3DS Files/source/difficultyinfo.h"
TMC = "3DS Files/source/timer.c"
RCC = "3DS Files/source/race.c"
CRR = "3DS Files/source/carrace.c"
CFM = "3DS Files/source/carfinish.c"

SOURCES_PORT = [CMC, CCC, CBC, CDC, CRC, RPC, CVC,
                "3DS Files/source/espresso.c",
                DIC, "3DS Files/source/player.c", TMC, CRR,
                "3DS Files/source/terraintypetab.c",
                "3DS Files/source/copmanager.c",
                "3DS Files/source/cartrack.c",
                "3DS Files/source/drivetarget.c",
                "3DS Files/source/trackroute.c",
                "3DS Files/source/trackpath.c",
                "3DS Files/source/quickspline.c",
                "3DS Files/source/bchunk.c",
                # CarCollisionBody's constructor, destructor and move: slice C.
                "3DS Files/source/collisionbody.c",
                "3DS Files/source/polyhedra.c",
                "3DS Files/source/vclip.c",
                "3DS Files/source/terraintype.c",
                # FinishMovement, and the Collision tests it asks: slice 11.
                "3DS Files/source/carfinish.c",
                "3DS Files/source/collision.c"]
SOURCES_PORT += [s for s in mmc.SOURCES_PORT if s not in SOURCES_PORT]

# ================================================================ the layout

pcc.NESTED.add("CarController")
pcc.HEADERS.update({"NullMover": "carmodes.h",
                    "CarController": "carcontroller.h",
                    "NullController": "carcontroller.h"})
for _t in ("NullMover", "CarController", "NullController"):
    LAYOUT[_t] = pcc.parse(_t)
pcc.UNNAMED.update({("NullMover", "Mover"), ("NullController", "Base")})

# Nested records first.
DUMPED = pcc.DUMPED + ["Mellovator", "MellowMover", "NullMover",
                       "CarController", "NullController"]

# The fields the model reads by offset, and where mdebug puts them.
CAR = {"pCarTypeInfo": 12, "MyDriver": 20, "pPlayer": 24,
       "pRacingCar": 28, "TheControlMode": 32,
       "TheMovementMode": 36, "pCarController": 40, "pCarDriver": 44,
       "pCarMover": 48, "pDynamicCollisionBody": 52, "State": 64,
       "DispGear": 1088,
       "FrictionBoost": 1092, "DraftFactor": 1096, "RenderingEnabled": 1160,
       "pAnimatedDriver": 1172,
       "TheTopologyCoordinate": 1280, "TheTrackPathCoordinate": 1840,
       "BlownTireBits": 1944, "NumBlownTires": 1945,
       "fBlownTireControllerRumbleTimer": 1948, "pBaseCarSound": 1952,
       "ResetMe": 1956, "BlinkTimer": 1960, "BlinkDuration": 1964,
       "pCaffeineObj": 1992, "NitroEffectFlag": 1888,
       "WiperOnTime": 1928, "WiperOffTime": 1932, "WiperState": 1936,
       "pCarDamage": 1940, "NumTimesSkidding": 1984}
TC_SIZE = 560                      # TopologyCoordinate
TPC_SIZE = 40                      # TrackPathCoordinate
RM_SIZE = 116                      # ReplayManager, as far as replay.h has it
SNAP_SIZE = 332                    # ReplaySnapshot, to TotalInterestingValue
SNAP_NAME, SNAP_TIV = 8, 328
RM_CAPTURING, RM_SNAPSHOTS = 4, 108
RPT_SIZE = 112                     # TrackRoutePoint
CB = [("CollisionBody", "Type", 12, 8),
      ("DynamicCollisionBody", "PhysicsMode", 84, 32),
      ("DynamicCollisionBody", "pSystem", 92, 32),
      ("DynamicCollisionBody", "pBody", 96, 32),
      ("CarCollisionBody", "pCar", 256, 32),
      ("CarCollisionBody", "LastPenetrationTime", 260, 32)]
CB_TYPE, CB_MODE, CB_SYSTEM, CB_BODY, CB_CAR, CB_PEN = (x[2] for x in CB)
# The step's records, which the model reads by offset too.
STEP_FIELDS = [("RacingCar", "CurrentLapNumberExact", 20, 32),
               ("DifficultyInfo", "TwoPlayerCatchup", 700, 256),
               ("RaceParameters", "Boost", 740, 32),
               ("RaceParameters", "nMaxCops", 604, 32),
               ("RaceParameters", "BeACop", 624, 32),
               ("DriverInfo", "DriverType", 4, 32),
               ("RaceParameters", "DamageEnabled", 64, 32),
               ("CarDamage", "BreakableCarItemDamageAmounts", 204, 32),
               ("BodyDamage", "CompressedTotalDamage", 40, 16),
               ("TerrainTypeInfo", "DriveOverMinSpeed", 60, 32),
               ("TerrainTypeInfo", "DriveOverMaxSpeed", 64, 32),
               ("PhysicsCar", "pEngine", 64, 32),
               ("Engine", "NitroFlag", 80, 32)]
PC_FRICTION = 108                  # PhysicsCar.FrictionBoost


def layout_problems():
    out = []
    for t in DUMPED + ["RigidBodyState"]:
        out.extend(pcc.check_layout(LAYOUT[t]))
    md = pcc.mdebug_fields(pcc.mdebug_record("Car")[1])
    for name, off in CAR.items():
        if name not in md or md[name][0] != off:
            out.append("Car.%s: model %d, mdebug %s" % (name, off,
                                                        md.get(name)))
    for rec, name, off, bits in CB + STEP_FIELDS:
        md = pcc.mdebug_fields(pcc.mdebug_record(rec)[1])
        if md.get(name) != (off, bits):
            out.append("%s.%s: model %d/%d, mdebug %s"
                       % (rec, name, off, bits, md.get(name)))
    if OFF("PhysicsCar", "FrictionBoost") != PC_FRICTION:
        out.append("PhysicsCar.FrictionBoost is not at %d" % PC_FRICTION)
    return out


# ================================================================ the image

GP = pcc.GP
G_NULLMOVER_POOL = GP - 23372
POOLS = mmc.POOLS + ["NullMover"]

CAR_SIZE, CCB_SIZE = pcc.CAR_SIZE, pcc.CCB_SIZE
DRIVER_SIZE = pcc.DRIVER_SIZE
DRV_VT = 556                       # every driver's vptr
CTRL_VT = 8                        # every controller's
MOVER_VT = 4                       # every mover's
TGT_SIZE = 528                     # DriveTarget, CarDriver's head

VT = {"NullMover": 0x002923c0, "CarController": 0x0029a6e0,
      "NullController": 0x00292350, "CarDriver": 0x002924a8,
      "NullDriver": 0x00292400}
VT_CARMOVER = 0x002923e0
TABLES = ["NullMover", "CarController", "NullController", "CarDriver",
          "NullDriver"]
PURE = pcc.PURE
# CarDriver::DoSnapshot waits on ReplaySnapshot; the port leaves it NULL.
PENDING = {("CarDriver", 24), ("NullDriver", 24)}

# Each port function a table holds, and the image's symbol for it.
FNMAP = [
    ("nullmover_destroy", "_$_9NullMover"),
    ("nullmover_move", "Move__9NullMoverf"),
    ("carmover_do_snapshot", "DoSnapshot__8CarMoverP14ReplaySnapshot"),
    ("carcontroller_destroy", "_$_13CarController"),
    ("carcontroller_debug_display", "DebugDisplay__13CarController"),
    ("carcontroller_do_snapshot",
     "DoSnapshot__13CarControllerP14ReplaySnapshot"),
    ("carcontroller_set_to_physics_mode",
     "SetToPhysicsMode__13CarControllerP3Car"),
    ("carcontroller_force_boost", "ForceBoost__13CarControllerf"),
    ("carcontroller_release_boost", "ReleaseBoost__13CarController"),
    ("nullcontroller_destroy", "_$_14NullController"),
    ("nullcontroller_think", "Think__14NullControllerf"),
    ("nullcontroller_set_current_route",
     "SetCurrentRoute__14NullControllerP10TrackRouteP15TrackRoutePoint"),
    ("nullcontroller_get_current_route", "GetCurrentRoute__14NullController"),
    ("nullcontroller_get_current_route_point",
     "GetCurrentRoutePoint__14NullController"),
    ("nullcontroller_get_amount_out_of_bounds",
     "GetAmountOutOfBounds__14NullController"),
    ("nullcontroller_find_where_i_am", "FindWhereIAm__14NullController"),
    ("nullcontroller_just_reset", "JustReset__14NullController"),
    ("cardriver_destroy", "_$_9CarDriver"),
    ("cardriver_add_joy_handlers", "AddJoyHandlers__9CarDriver"),
    ("cardriver_remove_joy_handlers", "RemoveJoyHandlers__9CarDriver"),
    ("cardriver_set_target", "SetTarget__9CarDriverP11DriveTarget"),
    ("cardriver_set_steer_to_point", "SetSteerToPoint__9CarDriverP8bVector2"),
    ("cardriver_start_honk_horn", "StartHonkHorn__9CarDriver"),
    ("cardriver_stop_honk_horn", "StopHonkHorn__9CarDriver"),
    ("cardriver_is_honking", "IsHonking__9CarDriver"),
    ("cardriver_max_speed_to_target",
     "MaxSpeedToTarget__9CarDriverP11DriveTarget"),
    ("cardriver_zero_steering_memory", "ZeroSteeringMemory__9CarDriver"),
    ("cardriver_clear_steering_memory", "ClearSteeringMemory__9CarDriver"),
    ("cardriver_get_desired_speed", "GetDesiredSpeed__9CarDriver"),
    ("cardriver_get_desired_time_to_speed",
     "GetDesiredTimeToSpeed__9CarDriver"),
    ("cardriver_set_physics_mode", "SetPhysicsMode__9CarDriveri"),
    ("cardriver_get_steer_to_point", "GetSteerToPoint__9CarDriver"),
    ("nulldriver_destroy", "_$_10NullDriver"),
    ("nulldriver_drive", "Drive__10NullDriverf"),
    ("nulldriver_set_low_gear", "SetLowGear__10NullDriver"),
    ("nulldriver_set_desired_speed", "SetDesiredSpeed__10NullDriverffb"),
    ("nulldriver_set_target", "SetTarget__10NullDriverP11DriveTarget"),
    ("nulldriver_get_driver_number", "GetDriverNumber__10NullDriver"),
]

SYM = {
    "move": "SetMovementMode__3Car12MovementMode",
    "ctrl": "SetControlMode__3Car11ControlMode",
    "stpm": "SetToPhysicsMode__3CarP3Car",
    "friction": "SetFrictionBoost__3Carf",
    "ccb-stpm": "SetToPhysicsMode__16CarCollisionBodyP13CollisionBody",
    "ccb-setup": "SetupPhysicsPointers__16CarCollisionBody",
    "cc-ctor": "__13CarControllerP3Car",
    "get-driver": "GetDriver__13CarController",
    "cd-ctor": "__9CarDriver",
    "nm-delete": "__dl__9NullMoverPv",
    "reset-core": "ResetCore__3CarP8bVector3fUs",
    "reset-pos": "ResetToPosition__3CarP8bVector3fUs",
    "reset-route": "ResetToRoutePoint__3CarP10TrackRouteP15TrackRoutePointfbf",
    "debug-pos": "DebugSetPosition__3CarP8bVector3fUs",
    "tp-loader": "LoaderTrackPath__FP6bChunk",
    "clear-bbox": "ClearInterestBBox__18TopologyCoordinate",
    "car-move": "Move__3Carf",
    "diff-loader": "LoaderDifficultyInfo__FP6bChunk",
    "diff-unloader": "UnloaderDifficultyInfo__FP6bChunk",
    "adrv-gear": "BeginGearChange__14AnimatedDriver",
    "adrv-back": "BeginDrivingBackwards__14AnimatedDriver",
    "adrv-unback": "EndDrivingBackwards__14AnimatedDriver",
    "esp-pos": "espSetObjectPosition__FUiP11FloatVector",
    "dist": "GetDistanceAndSpeed__3CarPfP3CarT2",
    "fix": "FixBlownTires__3Car",
    "blow": "TriggerTireBlowOut__3Cari",
    "later": "PleaseResetMeLater__3Car",
    "line": "GetDrivingLineSpeed__3Car",
    "deliver": "DeliverMeFromEvil__3CarP8bVector2Usff",
    "fx": "TriggerEffect__3Car9CarEffectfiP8bVector3",
    "snd-blow": "TriggerTireBlowOut__12BaseCarSound",
    "ebrake": "ForceEBrakeStop__10RealDriveri",
    "pursued": "IsBeingPursued__11tCopManagerP3Car",
    "ai-line": "GetCurrentDrivingLineSpeed__15AICarController",
    "setdest": "SetDestination__13DeliveryMoverP8bVector2Usff",
    "finish": "FinishMovement__3Carf",
    "hastopo": "HasTopology__18TopologyCoordinatePC8bVector2",
    "clearzone": "ClearZone__6Playerb",
    "requestzone": "RequestZone__6Playeribbb",
    "jumpcam": "IsJumpCamAvailable__6Player",
    "cleanup": "CleanUpJumpCam__6Player",
}
RESET_ENTRIES = ("reset-core", "reset-pos", "reset-route", "debug-pos")
G_WORLD_TIMER = pcc.G_WORLDTIMER
G_REPLAY = GP - 23008              # pReplayManager
TP_MGR = tpc.MGR                   # TheTrackPathManager
MGR_POINTS = 20                    # its pPoints

# The stand-ins: mode, class, the image's constructor, the size SetXMode
# asks bMalloc for.
MOVERS = [(2, "TrafficCar", "__10TrafficCarP3Car", 36),
          (3, "DeliveryMover", "__13DeliveryMoverP3Car", 192),
          (5, "CopMover", "__8CopMoverP3Car", 112),
          (6, "BeltMover", "__9BeltMoverP3Car", 72)]
CONTROLLERS = [(1, "RealController", "__14RealControllerP3Car", 84),
               (2, "AIDriver", "__8AIDriverP3Car", 720),
               (3, "TrafficDriver", "__13TrafficDriverP3Car", 720),
               (4, "CopDriver", "__9CopDriverP3Car", 76)]
FAKE_VT = 0x01E10000               # a stand-in's table, 0x100 apart
FAKE_VT_DRIVER = FAKE_VT + 0x800
FAKE_FN = 0x01E20000               # the stand-ins' entries, 16 apart


def fake_vt(kind, k):
    return FAKE_VT + 0x100 * (k if kind == "mover" else 4 + k)


# ============================================================ the scenarios

DT = 0.25
FRICTION0 = 1.25                   # the car's before anything sets it
FRICTION = [0.75 + 0.0625 * m for m in range(7)]
STRAY = 128                        # bytes after the mover s_friction watches
BOOST = (1.5, 2.5)
DSPEED = (10.0, 2.0)               # SetDesiredSpeed's two floats
JUNK_F = 7.0                       # in $f0 before a float return


def circuit(n):
    """Every ordered pair (a, b) of 0 .. n-1, loops included, as one walk
    from 0 back to 0 -- Hierholzer's, taking the lowest edge first."""
    left = {a: list(range(n)) for a in range(n)}
    stack, walk = [0], []
    while stack:
        a = stack[-1]
        if left[a]:
            stack.append(left[a].pop(0))
        else:
            walk.append(stack.pop())
    walk.reverse()
    assert len(walk) == n * n + 1
    return walk


MOVE_WALK = circuit(7)
CTRL_WALK = circuit(5)
# SetToPhysicsMode's three kinds of controller.
STPM_KINDS = ["none", "null", "fake"]
# (PhysicsMode, movement mode) for SetupPhysicsPointers called directly.
SETUP_CASES = [(0, 1), (0, 4), (1, 0), (1, 1), (1, 4), (2, 1), (-1, 4),
               (1, 2), (1, 6)]
# `other` for CarCollisionBody::SetToPhysicsMode: NULL, or ccb2 with this
# Type.
CCB_OTHER = [None, 0, 1, 0x80]


def tgt_pattern():
    # No byte above 0x3f, so no word is a NaN: a copy through the FPU
    # would keep it, but nothing need depend on that.
    return bytes((i * 7 + 0x11) % 0x2f + 0x10 for i in range(TGT_SIZE))


# ---- the resets

WORLD_TIMER = 0x00012345
BLINK0 = (77, 0.75)                # BlinkTimer, BlinkDuration before each
POISONS = (0xC4424000, 0x43A6A000)
SCRUB = 8192                       # bytes below sp each entry poisons
# What the image leaves to the stack is two words. One is the w of
# ResetCore's bNormalize result, 12(sp) as 0x0013134c copies it into
# Velocity whole: bNormalize writes three lanes. The other is the w of
# ResetToRoutePoint's position, 12(sp) there, three stores and a
# four-lane copy into Position, which PutFlatOnTrack carries into
# GeometryPosition. The rest are those two carried on: the movers
# ResetCore builds again take the state's w lanes into the body and the
# wheels. Zero just those two words and the poisoned runs are identical,
# so nothing else the resets reach reads the stack. Every one is a
# fourth lane. The step's physics case, after its resets, carries them
# once more: the integration is four lanes wide, so the angular momentum
# at body.State@96 takes a w from them too.
PAD_LANES = {"cs.Velocity", "cs.Position", "cs.GeometryPosition",
             "body.State@0", "body.State@80", "body.State@96",
             "body.Velocity",
             "body.ForceAccumulator", "body.MomentAccumulator",
             "wheel0.Velocity", "wheel1.Velocity", "wheel2.Velocity",
             "wheel3.Velocity"}

RESET_KINDS = ["pos", "core", "debug"]
# No player; a player and a replay that is not capturing; one that is; a
# player and no replay at all; a replay capturing and no player, which
# has to be left alone.
PLAYERS = [None, "idle", "cap", "nomgr", "bystander"]
# (kind, control mode, movement mode, player, pos with its w, speed, angle)
RESETS = [
    ("pos", 0, 0, None, (197.0, 19.9, 5.0, 0.625), 12.5, 0x1234),
    ("pos", 0, 1, None, (-60.0, 190.0, -2.0, 1.5), 0.0, 0xc000),
    ("pos", 2, 4, "cap", (140.0, -140.0, 0.25, -3.0), -7.25, 0x8001),
    ("pos", 2, 6, "idle", (35.0, 196.0, 0.0, 0.0), 2.0, 0x7fff),
    ("core", 2, 2, "idle", (0.0, -205.0, 1.0, 0.0), 30.0, 0x4000),
    ("core", 0, 1, "cap", (10.0, 10.0, 100.0, 2.0), 1e-3, 0xffff),
    ("core", 0, 0, "nomgr", (-190.0, -30.0, 0.0, 0.0), 4.0, 0x0100),
    ("debug", 0, 1, None, (180.0, 90.0, 7.0, 0.5), 15.0, 0x2000),
    ("debug", 2, 4, "cap", (-150.0, -120.0, -1.0, 9.0), -3.0, 0xf000),
    ("debug", 0, 0, None, (5000.0, 0.0, 0.0, 0.0), 0.0, 0),
    ("debug", 0, 3, None, (0.0, 199.0, 0.0, 0.0), 8.0, 0x9000),
    # The last three walk the track path one point a time. From 0,199 the
    # coordinate is kept, being near enough, and the search is only
    # ever to a point's neighbours on the path: 50,90 lands on point 2.
    # From there 150,40 goes to 1, and only the second update, from 1,
    # gets it to 0. Back at 50,90 the first update reaches 1 and the
    # second 2, which leaves ResetToRoutePoint's 150,40 two steps out
    # in turn.
    ("core", 0, 1, "bystander", (50.0, 90.0, 0.0, 0.0), 6.0, 0x6000),
    ("pos", 2, 4, None, (150.0, 40.0, 1.0, 0.0), 9.0, 0x0800),
    ("pos", 0, 0, None, (50.0, 90.0, 0.0, 0.0), 3.0, 0x3000),
]
# (control mode, movement mode, player, route?, point?, speed, blink,
# direction)
ROUTE_RESETS = [
    (0, 0, None, False, True, 5.0, 1, 1.0),
    (0, 0, None, True, False, 5.0, 1, 1.0),
    (2, 1, None, True, True, 5.0, 1, 1.0),
    (2, 4, "cap", True, True, 20.0, 0, -1.0),
    (0, 1, "idle", True, True, 0.0, 1, 0.5),
]
# Two named INSTANT_REPLAY, so that the walk has to go on past the first.
SNAPS = [("INSTANT_REPLAY", 10.0), ("LAP", 20.0),
         ("INSTANT_REPLAYS", 30.0), ("INSTANT_REPLA", 40.0),
         ("INSTANT_REPLAY", 50.0)]
RM_FREE = 100                      # FreeReplaySnapshotList, empty

# ---- the step

G_BOOST = 0x00312804               # TheRaceParameters.Boost
G_NUMPLAYERS = GP - 21520          # Player::NumPlayers, 0x003237e0
G_BYNUMBER = GP - 21536            # Player::pPlayersByNumber, 0x003237d0
DIFF = 0x002e81c0                  # TheDifficultyInfo
DIFF_SIZE = 744
PL_SIZE, PL_MYCAR, PL_NUMBER = 20, 4, 16
RC_SIZE, RC_LAPS = 192, 20
ADRV_SIZE = 112                    # AnimatedDriver, only ever a label
BUN = ROOT / "extracted" / "GLOBAL" / "GLOBALB.BUN"
DIFF_AT = 761472                   # chunk 0x34b00 in it
# The port's table is retail's 992 bytes, and the harness loads retail's
# chunk; the image loads the demo's 744. The catchup reads only
# TwoPlayerCatchup, whose four knees are the same in both, so only they
# are dumped. difficulty_check runs the loaders and holds the rest of the
# table to the retail image.
DIFF_KNEES = 700                   # TwoPlayerCatchup, the demo's
MOVE_DT = 0.03125
MOVE_RET0 = 0.5                    # the stand-ins' first answer, then +0.25
BOOST_MARK = 0.8125                # BoostFactor before each step
W = WORLD_TIMER
NO_PLAYER = -99                    # no pPlayer at all


def mv(ctl=2, move=2, gear=3, disp=3, adrv=True, reset=0, bt=0, bd=0.0,
       pen=0, player=None, boost=0, np=0, laps=(0.0, 0.0, 0.0), caff=False,
       full=False, now=W):
    return (ctl, move, gear, disp, int(adrv), reset, bt & M32, bd, pen & M32,
            NO_PLAYER if player is None else player, boost, np, laps,
            int(caff), int(full), now & M32)


# laps are the car's, player 0's (car3) and player 1's (car2). The graph's
# knees are at -500, -200, -100 and -40 metres of lead; a lap of this
# track is 2 pi 200.
CATCHUP = [
    mv(player=0, boost=1, np=2, laps=(1.3, 1.1, 1.55)),
]
MOVES = [
    # The dispatch under every kind of mover: the three real ones and the
    # four stand-ins, whose Move logs.
    mv(ctl=0, move=0, full=True),
    mv(move=2), mv(move=3), mv(move=5), mv(move=6),
    mv(ctl=0, move=1, full=True),
    mv(ctl=0, move=4, full=True),
    mv(ctl=2, move=2),
    # UpdatePosition's editor link.
    mv(caff=True),
    # ChangeGear.
    mv(gear=3, disp=1), mv(gear=3, disp=2, adrv=False), mv(gear=2, disp=0),
    mv(gear=0, disp=2), mv(gear=4, disp=3), mv(gear=1, disp=0),
    mv(gear=0, disp=1), mv(gear=0, disp=0), mv(gear=0, disp=5, adrv=False),
    mv(gear=0, disp=-1), mv(gear=-2, disp=0, adrv=False),
    # ResetMe: under a stand-in controller, whose route and point the
    # reset reaches; under the NullController, whose NULLs stop it; and
    # with a blink the tail would have stretched.
    mv(reset=1, full=True),
    mv(ctl=0, move=0, reset=1, full=True),
    mv(ctl=0, move=0, reset=1, bt=W - 4000, bd=1.25, pen=W - 1000),
    mv(ctl=2, move=4, reset=-7, bt=W - 4000, bd=1.25, pen=W - 1000,
       full=True),
    mv(ctl=2, move=2),
    # The blink tail. WorldTimer is W unless a case says otherwise; a tick
    # is a quarter millisecond.
    mv(bt=0, bd=2.0, pen=W - 1000),
    mv(bt=0x7fffffff, bd=2.0, pen=W - 1000),
    mv(bt=W - 4000, bd=1.25, pen=0),
    mv(bt=W - 4000, bd=1.25, pen=0x7fffffff),
    mv(bt=W - 4000, bd=1.25, pen=0x7ffffffe),
    mv(bt=W - 4000, bd=1.25, pen=1),
    # The sentinels inside the window, which needs a WorldTimer a quarter
    # second past each; and the stamps next to them, which stretch.
    mv(now=1000, bt=1000 - 4000, bd=1.25, pen=0),
    mv(now=1001, bt=1001 - 4000, bd=1.25, pen=1),
    mv(now=0x7fffffff + 1000, bt=0x7fffffff + 1000 - 4000, bd=1.25,
       pen=0x7fffffff),
    mv(now=0x7fffffff + 1000, bt=0x7fffffff + 1000 - 4000, bd=1.25,
       pen=0x7ffffffe),
    mv(bt=W - 400, bd=2.0, pen=W - 1000),
    mv(bt=W - 4000, bd=1.25, pen=W - 1000),
    mv(bt=W - 4000, bd=1.25, pen=W - 2000),
    mv(bt=W - 4000, bd=1.25, pen=W - 1999),
    mv(bt=W - 4000, bd=1.25, pen=W),
    mv(bt=W - 4000, bd=1.25, pen=W + 4),
    mv(bt=W - 2000, bd=1.0, pen=W - 1000),
    mv(bt=W - 2001, bd=1.0, pen=W - 1000),
    mv(bt=W - 3999, bd=1.0, pen=W - 1000),
    mv(bt=W - 4000, bd=1.0, pen=W - 1000),
    mv(bt=W + 4000, bd=-0.25, pen=W - 1000),
    mv(bt=W + 4000, bd=-0.75, pen=W - 1000),
    mv(bt=W - 4000, bd=1.25, pen=W + 0x80000000),
    mv(bt=W - 4000, bd=1.25, pen=W - 0x7ffffff0),
    mv(bt=W - 0x7ffffff0, bd=3e5, pen=W - 1000),
    # The catchup, over GLOBALB.BUN's table.
    mv(player=0, boost=1, np=2, laps=(1.3, 1.1, 1.55)),
    mv(player=1, boost=1, np=2, laps=(1.3, 1.55, 1.1)),
    mv(player=5, boost=1, np=2, laps=(1.3, 1.55, 1.1)),
    mv(player=-1, boost=1, np=2, laps=(1.3, 1.55, 1.1)),
    mv(player=0, boost=0, np=2, laps=(1.3, 1.1, 1.55)),
    mv(player=0, boost=-1, np=2, laps=(1.3, 1.1, 1.55)),
    mv(player=0, boost=1, np=1, laps=(1.3, 1.1, 1.55)),
    mv(player=0, boost=1, np=3, laps=(1.3, 1.1, 1.55)),
    mv(player=None, boost=1, np=2, laps=(1.3, 1.1, 1.55)),
    mv(player=0, boost=1, np=2, laps=(1.0, 9.0, 1.5)),
    mv(player=0, boost=1, np=2, laps=(2.0, 9.0, 2.1)),
    mv(player=0, boost=1, np=2, laps=(2.0, 9.0, 2.05)),
    mv(player=0, boost=1, np=2, laps=(2.5, 9.0, 2.51)),
    mv(player=0, boost=1, np=2, laps=(3.0, 9.0, 2.0)),
    mv(player=0, boost=1, np=2, laps=(0.7, 9.0, 0.9)),
    mv(player=0, boost=1, np=2, laps=(4.1, 9.0, 4.2)),
    # Each car's product, then the difference: (me - other) * L is a
    # different lead, and on these two a different boost by one ulp.
    mv(player=0, boost=1, np=2, laps=(1.97, 9.0, 2.1000001430511475)),
    mv(player=0, boost=1, np=2, laps=(1.69, 9.0, 1.99)),
    # All of it at once: the catchup, the step, the gear, the link and a
    # stretched blink.
    mv(ctl=0, move=1, gear=2, disp=0, caff=True, bt=W - 4000, bd=1.25,
       pen=W - 1000, player=0, boost=1, np=2, laps=(1.3, 1.1, 1.55),
       full=True),
]

# ---- slice nine: what the race, the AI and the pursuit ask of a car

G_BEACOP = 0x00312790              # TheRaceParameters.BeACop
G_MAXCOPS = 0x0031277c             # TheRaceParameters.nMaxCops
G_COPMGR = GP - 16500              # pCopManager, 0x00324b7c
DI_TYPE = 4                        # DriverInfo.DriverType
SND_SIZE = 16                      # BaseCarSound, only ever a label
COPMGR_SIZE = 16                   # tCopManager, likewise
DIST_MARK = 0x5a5a5a5a             # the speed's word before each distance
RACE_TIMER0 = 3.75                 # the rumble timer before each case
RESET_MARK = 0x55                  # ResetMe before each PleaseResetMeLater
LINE_SPEED0 = 21.5                 # the stand-in's first answer, then +0.5
# FixBlownTires: the control mode it is called under. Only REAL_CONTROL's
# driver is a RealDriver.
FIX = [0, 1, 2, 3, 4]
# TriggerTireBlowOut: the bits already blown, the mask, NumBlownTires
# before, and whether the car has a sound.
BLOW = [
    (0x00, 0x1, 9, True),
    (0x00, 0xf, 0, True),
    (0x05, 0x2, 2, True),
    # The same two again: the count is rebuilt, and the effect goes off
    # at both once more.
    (0x03, 0x3, 2, True),
    (0x00, 0x0, 1, True),
    # Bits past the fourth wheel: kept, and counted by nothing.
    (0x80, 0x10, 0, False),
    (0x00, -1, 0, True),
    (0x0a, 0x100, 3, True),
    (0x00, 0x8, 0, False),
    (0xf0, 0x6, 7, True),
]
# PleaseResetMeLater: BeACop, nMaxCops, the driver's type, the cop
# manager's answer, and whether pCopManager is set.
LATER = [
    (0, 1, 2, 1, True),
    (1, 0, 2, 1, True),
    (1, -1, 2, 1, True),
    (1, -0x80000000, 2, 1, True),
    (1, 1, 1, 1, True),
    (1, 1, 3, 1, True),
    (1, 1, 0x102, 1, True),
    (1, 1, 2, 1, True),
    (1, 1, 2, 0, True),
    (2, 3, 2, 7, True),
    (-1, 0x7fffffff, 2, 0, False),
    (1, 1, 2, 1, False),
]
# GetDrivingLineSpeed: the control mode.
LINE = [0, 1, 2, 3, 4, 2]
# DeliverMeFromEvil: the movement mode it is called from, the angle's word
# as passed (the image masks it), the speed and the time.
DELIVER = [
    (0, 0x1234, 12.5, 3.0),
    (1, 0x12345, -4.0, 0.25),
    (3, 0xffff, 0.0, 1e6),
    (2, 0x8000, 99.0, -1.0),
]

# ---- slice eleven: FinishMovement

G_LOOP = GP - 20200                # WorldLoopCounter, 100000 on the disc
G_BORING = GP - 23156              # BoringAIForCameraTuningOn
G_NOREPLAY = GP - 23472            # g_DisableAutoReplay
G_WORLD = GP - 22624               # pCurrentWorld
G_WLIST = GP - 18352               # CollisionBodyWitnessList
LOOP0 = 100000
FM_CAR = {"vOldVel": 1120, "vOldAngVel": 1136, "AirTimeSwitch": 1156,
          "ForceHeadlightsOn": 1916, "HeadlightsState": 1920}
# The Player: all 2480 bytes, and the three fields FinishMovement reads.
FM_PL_SIZE, FM_PL_ZONE, FM_PL_WRONG, FM_PL_EYEZ = 2480, 76, 736, 1640
WD_AI, WD_COP, WD_TABLE = 32, 36, 44   # World
FM_NCARS = 5                           # the table: this car, then four
COL_SIZE, COL_LCT, COL_WIT = 96, 12, 84
WIT_SIZE, WIT_B1, WIT_B2, WIT_COL = 112, 96, 100, 104
CB_BODY_SIZE, CB_NCOL = 84, 18
FM_KINDS = ["car", "smoke", "static"]  # the other body: ccb2, or a plain one
FM_KIND_TYPE = {"car": 0, "smoke": 1, "static": 2}
TP_NUMPATHS = 8                    # TheTrackPathManager.NumPaths
FM_OLDVEL = (40.0, 1.5, -2.0, 0.125)
FM_ANG = (0.5, -0.25, 2.0, 0.75)
FM_OLDANG = (0.25, 0.5, -1.0, 0.0)
FM_ACC = (111.0, 222.0, 333.0, 444.0)  # the accelerations before each case
FM_NOW = 40000                     # WorldTimer: ten seconds
FM_POS = (600.0, 10.0, 21.0, 0.25)
FM_VEL = (44.0, 0.0, 0.0, 0.5)
FM_FAR = ((1000.0, 0.0, 0.0), (0.0, 1000.0, 0.0), (0.0, 0.0, 1000.0),
          (5.0, 0.0, 0.0))         # the four others, from the car
# High enough that AverageAir's jump is long and high enough for the jump
# cam. And the height at which, rising at 5, its highest point is exactly
# 1.5 above the plane (found by reading the image's frame after the call).
FM_JUMP = (600.0, 10.0, 26.0, 0.25)
FM_H15 = 0x41a15446


def fm_points():
    t = tpc.Track()
    t.add_path(tpc.circle(12, 200.0, 0.0, 0.0, 0.1), 1)
    return t.pos


def fm_offset(pos, pt):
    """FinishMovement's distance to the track path's point, in float32."""
    dx = tpc.f32(pos[0] - pt[0])
    dy = tpc.f32(pos[1] - pt[1])
    return tpc.f32(math.sqrt(tpc.f32(tpc.f32(dx * dx) + tpc.f32(dy * dy))))


def fm_along(pt, dist):
    """Two x's at pt's y: the first exactly `dist` from pt, and the first
    past it."""
    x = tpc.f32(pt[0] + dist)
    step = lambda v, k: tpc.bf(fb(v) + k)
    xs = [step(x, k) for k in range(-8, 9)]
    eq = [v for v in xs if fm_offset((v, pt[1]), pt) == dist]
    up = [v for v in xs if fm_offset((v, pt[1]), pt) > dist]
    assert eq and up, (pt, dist)
    return eq[0], up[0]


FM_PT = fm_points()
# 5000 from point 0 along +x, where point 0 is the nearest: exactly, and
# the next float out. 300 from point 3 along +x, where point 1 is the
# nearest but a search that starts at point 4 stops at point 3.
FM_5000 = fm_along(FM_PT[0], 5000.0)
FM_300 = fm_along(FM_PT[3], 300.0)


def fm(dt=0.03125, vmag=45.0, odo=100.0, pos=FM_POS, vel=FM_VEL, tp=None,
       nopaths=False, loop=5, now=FM_NOW, mode=7, topo=(), boring=0,
       player=True, zone=0, wheels=0, wrong=0, jc=1, rz=1, disable=0,
       angle=0, fwd=30.0, eye=0.0, ats=0.0, ai=1, cop=4, close=None,
       col=None, rm=True, lights=0):
    """A case. `tp` is the track path coordinate's point before, or None;
    it is put at the car, so the search starts from that point. `close`
    is up to four offsets from the car for the table's others (FM_FAR
    otherwise). `col` is None for no collision, else (kind, ticks since
    the last contact, which of the witness's two bodies is the car's,
    whether the witness has its Collision, the car's own body's Type)."""
    others = list(close or ()) + list(FM_FAR[len(close or ()):])
    table = [tuple(tpc.f32(pos[k] + o[k]) for k in range(3)) for o in others]
    return dict(dt=dt, vmag=vmag, odo=odo, pos=pos, vel=vel, tp=tp,
                nopaths=nopaths, loop=loop, now=now, mode=mode,
                topo=tuple(topo), boring=boring, player=player, zone=zone,
                wheels=wheels, wrong=wrong, jc=jc, rz=rz, disable=disable,
                angle=angle, fwd=fwd, eye=eye, ats=ats, ai=ai, cop=cop,
                table=table, col=col, rm=rm, lights=lights)


FINISH = [
    # dt: none, negative, minus zero, a denormal (1/dt is FLT_MAX), large.
    fm(dt=0.0, player=False, lights=1),
    fm(dt=-0.03125, player=False),
    fm(dt=-0.0, player=False),
    fm(dt=tpc.bf(1), player=False),
    fm(dt=2.0, player=False),
    # The odometer: at 0 and at 1000 it runs (the 0 shows on a -0
    # odometer, which it makes +0); below and above it does not; a NaN
    # speed runs it.
    fm(vmag=0.0, player=False), fm(vmag=-0.0, player=False),
    fm(vmag=0.0, odo=-0.0, player=False),
    fm(vmag=-1.0, player=False), fm(vmag=1000.0, player=False),
    fm(vmag=1000.0001, player=False), fm(vmag=float("nan"), player=False),
    # The topology test, every thirty-second step on (loop + 7) & 31: the
    # car's own spot, then a metre along x; a car with no movement mode is
    # not asked; nor is a step off the phase.
    fm(loop=25, topo=(1,), player=False),
    fm(loop=25, topo=(0, 1), player=False),
    fm(loop=25, topo=(0, 0), player=False),
    fm(loop=25, mode=0, player=False),
    fm(loop=24, player=False),
    fm(loop=-7, topo=(0, 0), player=False),
    fm(loop=57, topo=(0, 1), player=False),
    # Lost: exactly 5000 from the point, then the next float out; the
    # camera tuner's boring AI keeps it.
    fm(pos=(FM_5000[0], FM_PT[0][1], 21.0, 0.25), player=False),
    fm(pos=(FM_5000[1], FM_PT[0][1], 21.0, 0.25), player=False),
    fm(pos=(FM_5000[1], FM_PT[0][1], 21.0, 0.25), boring=1, player=False),
    # Searched afresh: a search from point 4 stops at point 3, exactly 300
    # away, though point 1 is nearer. Past 300, on a sixtieth step (0, 60
    # and -60, a signed remainder) and moving, the coordinate forgets its
    # point and finds point 1.
    fm(pos=(FM_300[0], FM_PT[3][1], 21.0, 0.25), tp=4, loop=60,
       player=False),
    fm(pos=(FM_300[1], FM_PT[3][1], 21.0, 0.25), tp=4, loop=60,
       player=False),
    fm(pos=(FM_300[1], FM_PT[3][1], 21.0, 0.25), tp=4, loop=0,
       player=False),
    fm(pos=(FM_300[1], FM_PT[3][1], 21.0, 0.25), tp=4, loop=-60,
       player=False),
    fm(pos=(FM_300[1], FM_PT[3][1], 21.0, 0.25), tp=4, loop=30,
       player=False),
    fm(pos=(FM_300[1], FM_PT[3][1], 21.0, 0.25), tp=4, loop=60, mode=0,
       player=False),
    fm(pos=(FM_300[1], FM_PT[3][1], 21.0, 0.25), tp=4, loop=61,
       player=False),
    # Lost from point 3 as well, 5100 out: put back, and not searched.
    fm(pos=(tpc.f32(FM_PT[3][0] + 5100.0), FM_PT[3][1], 21.0, 0.25), tp=4,
       loop=60, player=False),
    fm(pos=(tpc.f32(FM_PT[3][0] + 5100.0), FM_PT[3][1], 21.0, 0.25), tp=4,
       loop=60, boring=1, player=False),
    # No paths at all: no point, so a distance of 0 however far out.
    fm(pos=(6000.0, 10.0, 21.0, 0.25), nopaths=True, loop=60,
       player=False),
    # A player's car: the lights are left alone. Off the eighth step, only
    # the zone clear runs.
    fm(lights=1, loop=6),
    fm(zone=6, wheels=2, loop=6),
    fm(zone=7, wheels=1, loop=6),
    fm(zone=5, wheels=1, loop=6),
    fm(zone=7, wheels=0, loop=6),
    # Nor on 9, which a sixteenth step and a fourth would both take.
    fm(loop=9),
    # A cleared zone is read again: nothing of the jump cam's follows.
    fm(zone=6, wheels=1, ats=0.0),
    # The default: in the air above 40 and flying straight, but too low
    # for the jump cam: AverageAir lands it inside half a second.
    fm(),
    fm(loop=-3),
    # A jump the jump cam takes; falling, so the new zone, read again,
    # keeps the height.
    fm(pos=FM_JUMP),
    fm(pos=FM_JUMP, vel=(44.0, 0.0, -1.0, 0.5)),
    fm(pos=FM_JUMP, jc=0),
    fm(pos=FM_JUMP, rz=0),
    fm(pos=FM_JUMP, disable=1),
    fm(pos=FM_JUMP, wrong=1),
    fm(pos=FM_JUMP, wheels=-1),
    fm(pos=FM_JUMP, wheels=3),
    fm(pos=FM_JUMP, wheels=4),
    fm(pos=FM_JUMP, zone=7),
    # AverageAir's answers at the edges: exactly 0.9 s, so half of it;
    # exactly 0.5 s, too short; exactly 1.5 high, too low, and the next
    # float up; never down in the three seconds.
    fm(pos=(600.0, 10.0, 28.0, 0.25), vmag=30.5),
    fm(pos=(600.0, 10.0, 22.0, 0.25), vmag=30.5),
    fm(pos=(600.0, 10.0, tpc.bf(FM_H15), 0.25), vel=(44.0, 0.0, 5.0, 0.5)),
    fm(pos=(600.0, 10.0, tpc.bf(FM_H15 + 1), 0.25),
       vel=(44.0, 0.0, 5.0, 0.5)),
    fm(pos=FM_JUMP, vel=(44.0, 0.0, 60.0, 0.5)),
    # The speeds: at 40, just over 30, at 30.
    fm(pos=FM_JUMP, vmag=40.0),
    fm(pos=FM_JUMP, vmag=tpc.bf(fb(30.0) + 1)),
    fm(pos=FM_JUMP, vmag=30.0),
    # The yaw either side of 3.14/32 -- 1023 and 1024 are the nearest two
    # angles, and no angle is exactly on it -- both ways round; and too
    # slow to have a yaw.
    fm(angle=1023, wheels=2),
    fm(angle=1024, wheels=2),
    fm(angle=-1023, wheels=2),
    fm(angle=-1024, wheels=2),
    fm(angle=4000, fwd=4.9, wheels=2),
    # In the jump cam's zone: the height kept while falling, the switch
    # time either side of now, and the zone after.
    fm(zone=6, vel=(44.0, 0.0, -1.0, 0.5), eye=0.0, ats=20.0),
    fm(zone=6, vel=(44.0, 0.0, -1.0, 0.5), eye=21.0, ats=20.0),
    fm(zone=6, vel=(44.0, 0.0, -1.0, 0.5), eye=30.0, ats=20.0),
    fm(zone=6, pos=(600.0, 10.0, 0.0, 0.25), vel=(44.0, 0.0, -1.0, 0.5),
       eye=-0.0, ats=20.0),
    fm(zone=6, vel=(44.0, 0.0, 0.0, 0.5), eye=0.0, ats=20.0),
    fm(zone=6, ats=10.0),
    fm(zone=6, ats=tpc.bf(fb(10.0) - 1)),
    fm(zone=6, ats=tpc.bf(fb(10.0) + 1)),
    fm(zone=6, disable=1, ats=0.0, vel=(44.0, 0.0, -1.0, 0.5)),
    fm(zone=7, ats=0.0, vel=(44.0, 0.0, -1.0, 0.5)),
    # CloseCars: one, three, one at exactly 40, one just inside; the car
    # itself when the AI run starts at it; the cop's slot; no AI at all.
    fm(close=[(10.0, 0.0, 0.0)], wheels=4),
    fm(close=[(10.0, 0.0, 0.0), (0.0, 20.0, 0.0), (0.0, 0.0, 30.0)],
       wheels=4),
    fm(close=[(40.0, 0.0, 0.0), (0.0, -40.0, 0.0), (0.0, 0.0, 40.0)],
       wheels=4),
    fm(close=[(39.999, 0.0, 0.0), (0.0, 0.0, -39.999)], wheels=4),
    fm(close=[(20.0, 20.0, 20.0), (30.0, 30.0, 0.0)], wheels=4),
    fm(ai=0, wheels=4),
    fm(cop=5, wheels=4),
    fm(ai=1, cop=1, close=[(1.0, 0.0, 0.0)], wheels=4),
    fm(ai=3, cop=1, close=[(1.0, 0.0, 0.0)], wheels=4),
    fm(vmag=40.0, close=[(1.0, 0.0, 0.0)], wheels=4),
    # Sliding, either side of 3.14/8: 4093 and 4094 are the nearest two.
    fm(angle=4093, wheels=4),
    fm(angle=4094, wheels=4),
    fm(angle=-4094, wheels=4),
    fm(angle=-4093, wheels=4),
    fm(angle=4100, vmag=30.0, wheels=4),
    # The collision: two cars, above 40, under it and at it; a smokeable,
    # either way round, above 30 and at it; a static body; a witness with
    # no Collision; the half second; a car's own body that is not a car's,
    # so no player is in it; no replay to tell.
    fm(col=("car", 0, 0, True, 0), wheels=4),
    fm(col=("car", 0, 1, True, 0), wheels=4),
    fm(col=("car", 0, 0, True, 0), vmag=35.0, wheels=4),
    fm(col=("car", 0, 0, True, 0), vmag=40.0, wheels=4),
    fm(col=("smoke", 0, 0, True, 0), wheels=4),
    fm(col=("smoke", 0, 1, True, 0), vmag=35.0, wheels=4),
    fm(col=("smoke", 0, 0, True, 0), vmag=30.0, wheels=4),
    fm(col=("static", 0, 0, True, 0), wheels=4),
    fm(col=("car", 0, 0, False, 0), wheels=4),
    fm(col=("smoke", 1999, 0, True, 0), wheels=4),
    fm(col=("smoke", 2000, 0, True, 0), wheels=4),
    fm(col=("smoke", -100, 0, True, 0), wheels=4),
    fm(col=("smoke", -0x80000000, 0, True, 0), wheels=4),
    fm(col=("smoke", 0, 0, True, 2), wheels=4),
    fm(col=("car", 0, 1, True, 2), wheels=4),
    fm(col=("car", 0, 0, True, 0), rm=False, angle=4100,
       close=[(1.0, 0.0, 0.0)]),
]


def diff_chunk():
    with open(BUN, "rb") as f:
        f.seek(DIFF_AT)
        b = f.read(8 + DIFF_SIZE)
    assert struct.unpack_from("<II", b) == (0x34b00, DIFF_SIZE)
    return b


def track_words():
    t = tpc.Track()
    t.add_path(tpc.circle(12, 200.0, 0.0, 0.0, 0.1), 1)
    return t.chunk_words()


def rpt_bytes():
    # Position, Elevation, Direction, then every other float distinct, so
    # a read of the wrong one shows.
    b = struct.pack("<11f", 150.0, 40.0, 3.5, 0.6, 0.8, 11.0, 12.0, 13.0,
                    0.125, 0.25, 99.0) + struct.pack("<I", 0xffffffff)
    return b + bytes((i * 5 + 3) & 0xff for i in range(RPT_SIZE - len(b)))


def generate(cti):
    g = []
    w = g.append
    w("// Generated by tools/carmode_check.py. Do not edit.")
    w("#define CM_GENERATED 1")
    w("#include <stddef.h>")
    w("#include <stdint.h>")
    w("#include <stdio.h>")
    w('#include "carcontroller.h"')
    w('#include "cardriver.h"')
    w('#include "carmodes.h"')
    w('#include "mellowmover.h"')
    w('#include "physicscar.h"')
    w('#include "vtable.h"')
    w("")
    w("typedef struct PcField { const char *name; size_t hoff, hsize; } PcField;")
    w("typedef struct PcType { const char *name; const PcField *f; int n; } PcType;")
    g.extend(pcc.c_dumps(DUMPED))
    w("static const uint8_t cm_cti[1368] = {")
    for i in range(0, 1368, 24):
        w("    " + ", ".join("%d" % b for b in cti[i:i + 24]) + ",")
    w("};")
    w("static const uint8_t cm_tgt[%d] = {" % TGT_SIZE)
    t = tgt_pattern()
    for i in range(0, TGT_SIZE, 24):
        w("    " + ", ".join("%d" % b for b in t[i:i + 24]) + ",")
    w("};")
    w("static const int cm_move_walk[] = {%s};"
      % ", ".join(str(x) for x in MOVE_WALK))
    w("static const int cm_ctrl_walk[] = {%s};"
      % ", ".join(str(x) for x in CTRL_WALK))
    w("static const int cm_setup_cases[][2] = {%s};"
      % ", ".join("{%d, %d}" % c for c in SETUP_CASES))
    w("static const int cm_ccb_other[] = {%s};"
      % ", ".join("-1" if o is None else str(o) for o in CCB_OTHER))
    w("static const uint32_t cm_friction[7] = {%s};"
      % pcc.c_u32_list([fb(f) for f in FRICTION]))
    w("#define CM_N(a) ((int)(sizeof(a) / sizeof((a)[0])))")
    w("#define CM_DT 0x%08xu" % fb(DT))
    w("#define CM_FRICTION0 0x%08xu" % fb(FRICTION0))
    w("#define CM_BOOST0 0x%08xu" % fb(BOOST[0]))
    w("#define CM_BOOST1 0x%08xu" % fb(BOOST[1]))
    w("#define CM_DSPEED0 0x%08xu" % fb(DSPEED[0]))
    w("#define CM_DSPEED1 0x%08xu" % fb(DSPEED[1]))
    w("#define CM_FAKE_VT 0x%08xu" % FAKE_VT)
    w("#define CM_FAKE_VT_DRIVER 0x%08xu" % FAKE_VT_DRIVER)
    # The image's sizes for the eight records the port allocates itself,
    # which the harness's log shows in place of the host's.
    w("#define CM_IMG_PHYSICSCAR %d" % pcc.PC_SIZE)
    w("#define CM_IMG_NULLCONTROLLER %d" % 12)
    w("#define CM_IMG_NULLDRIVER %d" % DRIVER_SIZE)
    w("#define CM_IMG_REALCONTROLLER %d" % 84)
    w("#define CM_IMG_BELTMOVER %d" % 72)
    w("#define CM_IMG_TRAFFICCAR %d" % 36)
    w("#define CM_IMG_COPMOVER %d" % 112)
    w("#define CM_IMG_AIDRIVER %d" % 720)
    w("#define CM_IMG_TRAFFICDRIVER %d" % 720)
    w("#define CM_STRAY %d" % STRAY)
    w("#define CM_NORMAL_X 0x%08xu" % pcc.NORMAL[0])
    w("#define CM_NORMAL_Y 0x%08xu" % pcc.NORMAL[1])
    w("#define CM_NORMAL_Z 0x%08xu" % pcc.NORMAL[2])
    w("static const uint32_t CM_TERRAIN[4][3] = {%s};" % ", ".join(
        "{%s}" % pcc.c_u32_list(v) for v in pcc.TERRAIN))

    w("#define CM_WORLD_TIMER %d" % WORLD_TIMER)
    w("#define CM_BLINK0_TIMER %d" % BLINK0[0])
    w("#define CM_BLINK0_DURATION 0x%08xu" % fb(BLINK0[1]))
    tw = track_words()
    w("static const uint32_t cm_track[%d] = {" % len(tw))
    for i in range(0, len(tw), 6):
        w("    " + pcc.c_u32_list(tw[i:i + 6]) + ",")
    w("};")
    w("#define CM_NSNAPS %d" % len(SNAPS))
    w("static const char *const cm_snap_name[%d] = {%s};" % (
        len(SNAPS), ", ".join('"%s"' % n for n, _ in SNAPS)))
    w("static const uint32_t cm_snap_tiv[%d] = {%s};" % (
        len(SNAPS), pcc.c_u32_list([fb(v) for _, v in SNAPS])))
    rb = rpt_bytes()
    w("static const uint8_t cm_rpt[%d] = {%s};" % (
        RPT_SIZE, ", ".join("%d" % x for x in rb)))
    w("typedef struct CmReset { int kind, ctrl, move, player; "
      "uint32_t pos[4], speed; int angle; } CmReset;")
    w("static const CmReset cm_resets[] = {")
    for kind, ctl, mv, pl, pos, speed, angle in RESETS:
        w("    { %d, %d, %d, %d, {%s}, 0x%08xu, 0x%04x }," % (
            RESET_KINDS.index(kind), ctl, mv, PLAYERS.index(pl),
            pcc.c_u32_list([fb(v) for v in pos]), fb(speed), angle))
    w("};")
    w("typedef struct CmRouteReset { int ctrl, move, player, route, point; "
      "uint32_t speed; int blink; uint32_t dir; } CmRouteReset;")
    w("static const CmRouteReset cm_route_resets[] = {")
    for ctl, mv, pl, route, point, speed, blink, d in ROUTE_RESETS:
        w("    { %d, %d, %d, %d, %d, 0x%08xu, %d, 0x%08xu }," % (
            ctl, mv, PLAYERS.index(pl), int(route), int(point), fb(speed),
            blink, fb(d)))
    w("};")
    w("")
    w("#define CM_MOVE_DT 0x%08xu" % fb(MOVE_DT))
    w("#define CM_MOVE_RET0 0x%08xu" % fb(MOVE_RET0))
    w("#define CM_BOOST_MARK 0x%08xu" % fb(BOOST_MARK))
    w("#define CM_ADRV_SIZE %d" % ADRV_SIZE)
    w("#define CM_NO_PLAYER %d" % NO_PLAYER)
    d = dcc.disc_chunk(dcc.RETAIL_BUN, dcc.SIZE)
    w("static const uint8_t cm_diff[%d] = {" % len(d))
    for i in range(0, len(d), 24):
        w("    " + ", ".join("%d" % x for x in d[i:i + 24]) + ",")
    w("};")
    w("typedef struct CmMove { int ctl, move, gear, disp, adrv, reset; "
      "uint32_t bt, bd, pen; int player, boost, np; uint32_t laps[3]; "
      "int caff, full; uint32_t now; } CmMove;")
    for name, table in (("cm_catchup", CATCHUP), ("cm_moves", MOVES)):
        w("static const CmMove %s[] = {" % name)
        for (ctl, move, gear, disp, adrv, reset, bt, bd, pen, player, boost,
             np, laps, caff, full, now) in table:
            w("    { %d, %d, %d, %d, %d, %d, 0x%08xu, 0x%08xu, 0x%08xu, %d, "
              "%d, %d, {%s}, %d, %d, 0x%08xu }," % (
                  ctl, move, gear, disp, adrv, reset, bt, fb(bd), pen,
                  player, boost, np, pcc.c_u32_list([fb(x) for x in laps]),
                  caff, full, now))
        w("};")
    w("")
    w("#define CM_SND_SIZE %d" % SND_SIZE)
    w("#define CM_COPMGR_SIZE %d" % COPMGR_SIZE)
    w("#define CM_DIST_MARK 0x%08xu" % DIST_MARK)
    w("#define CM_RACE_TIMER0 0x%08xu" % fb(RACE_TIMER0))
    w("#define CM_RESET_MARK %d" % RESET_MARK)
    w("#define CM_LINE_SPEED0 0x%08xu" % fb(LINE_SPEED0))

    def i32s(vals):
        return ", ".join("(int32_t)0x%08xu" % (v & M32) for v in vals)

    def f32s(vals):
        return pcc.c_u32_list([fb(v) for v in vals])
    w("static const int32_t cm_fix[] = {%s};" % i32s(FIX))
    w("typedef struct CmBlow { int32_t bits, tires, num, snd; } CmBlow;")
    w("static const CmBlow cm_blow[] = {")
    for bits, tires, num, snd in BLOW:
        w("    { %s }," % i32s((bits, tires, num, int(snd))))
    w("};")
    w("typedef struct CmLater { int32_t beacop, maxcops, dtype, pursued, "
      "mgr; } CmLater;")
    w("static const CmLater cm_later[] = {")
    for bc, mc, dt, pu, mgr in LATER:
        w("    { %s }," % i32s((bc, mc, dt, pu, int(mgr))))
    w("};")
    w("static const int32_t cm_line[] = {%s};" % i32s(LINE))
    w("typedef struct CmDeliver { int32_t from; uint32_t angle, speed, "
      "time; } CmDeliver;")
    w("static const CmDeliver cm_deliver[] = {")
    for frm, angle, speed, t in DELIVER:
        w("    { %d, 0x%08xu, 0x%08xu, 0x%08xu }," % (frm, angle & M32,
                                                     fb(speed), fb(t)))
    w("};")
    w("")
    w("#define CM_FM_PL_SIZE %d" % FM_PL_SIZE)
    w("#define CM_FM_NCARS %d" % FM_NCARS)
    w("#define CM_LOOP0 %d" % LOOP0)
    for name, v in (("acc", FM_ACC), ("oldvel", FM_OLDVEL), ("ang", FM_ANG),
                    ("oldang", FM_OLDANG)):
        w("static const uint32_t cm_fm_%s[4] = {%s};" % (name, f32s(v)))
    w("typedef struct CmFm { uint32_t dt, vmag, odo, pos[4], vel[4]; "
      "int32_t tp, nopaths, loop, now, mode, ntopo, topo[2], boring, "
      "player, zone, wheels, wrong, jc, rz, disable, angle; uint32_t fwd, "
      "eye, ats; int32_t ai, cop; uint32_t table[4][3]; int32_t col, iscar, "
      "type, ago, order, has, selftype, rm, lights; } CmFm;")
    w("static const CmFm cm_fm[] = {")
    for c in FINISH:
        topo = list(c["topo"]) + [0] * (2 - len(c["topo"]))
        col = c["col"] or ("car", 0, 0, False, 0)
        kind, ago, order, has, selftype = col
        w("    { 0x%08xu, 0x%08xu, 0x%08xu, {%s}, {%s}, %s, {%s}, %s, "
          "0x%08xu, 0x%08xu, 0x%08xu, %s, {%s}, %s }," % (
              fb(c["dt"]), fb(c["vmag"]), fb(c["odo"]), f32s(c["pos"]),
              f32s(c["vel"]),
              i32s((-1 if c["tp"] is None else c["tp"], int(c["nopaths"]),
                    c["loop"], c["now"], c["mode"], len(c["topo"]))),
              i32s(topo),
              i32s((c["boring"], int(c["player"]), c["zone"], c["wheels"],
                    c["wrong"], c["jc"], c["rz"], c["disable"], c["angle"])),
              fb(c["fwd"]), fb(c["eye"]), fb(c["ats"]),
              i32s((c["ai"], c["cop"])),
              ", ".join("{%s}" % f32s(p) for p in c["table"]),
              i32s((int(c["col"] is not None), int(kind == "car"),
                    FM_KIND_TYPE[kind], ago,
                    order, int(has), selftype, int(c["rm"]), c["lights"]))))
    w("};")
    w("")
    w("typedef struct CmFn { VtFn fn; uint32_t addr; } CmFn;")
    w("static const CmFn cm_fnmap[] = {")
    from mipsemu import Emu
    syms = Emu(ieee=True).elf.syms
    for cname, sym in FNMAP:
        w("    { (VtFn)%s, 0x%08xu }," % (cname, syms[sym][0]))
    w("};")
    w("typedef struct CmTable { const char *name; uint32_t vt; } CmTable;")
    w("static const CmTable cm_tables[] = {")
    for t in TABLES:
        w('    { "%s", 0x%08xu },' % (t, VT[t]))
    w("};")
    w("#line 1 \"carmode_test.c\"")
    return NL.join(g) + NL


# ================================================================= the model

class Model(mmc.Model):
    def __init__(self, cti, poison=None):
        mmc.Model.__init__(self, [cti])
        e = self.e
        self.inuse.append(0)
        base = pcc.POOL_BASE + 0x100 * 9
        e.put32(G_NULLMOVER_POOL, base)
        self.pool_of[base] = 9
        self.reg = []              # (name, addr, size, type), oldest first
        self.names = {}            # addr -> name
        self.nalloc = 0
        self.nfake = 0
        self.full = False
        self.quiet = False         # a block nobody logs: the QuickSplines'
        self.car = self.car2 = self.ccb = self.ccb2 = 0
        self.di = self.tgt = 0
        self.rm = self.player = self.route = self.rpt = self.vec = 0
        self.snaps = []
        self.adrv = self.caff = self.plc = self.car3 = 0
        self.pl = []
        self.rc = []
        self.nmove = 0
        self.dist = self.snd = self.copmgr = self.dpos = 0
        self.pursued = 0
        self.nline = 0
        self.fm_topo = []          # slice eleven's scripted answers
        self.fm_jc = self.fm_rz = 0
        e.stub("bMalloc__FiPCcii", self.on_malloc)
        e.stub("__builtin_delete", self.on_free)
        e.stub("bFree__FPv", self.on_free)
        e.stub(SYM["clear-bbox"], self.on_clear_bbox)
        for k, what in (("adrv-gear", "begin-gear"), ("adrv-back", "begin-back"),
                        ("adrv-unback", "end-back")):
            e.stub(SYM[k], self.on_adrv(what))
        e.stub(SYM["esp-pos"], self.on_esp)
        for k, fn in (("fx", self.on_effect), ("snd-blow", self.on_snd_blow),
                      ("ebrake", self.on_ebrake),
                      ("pursued", self.on_pursued),
                      ("ai-line", self.on_line_speed),
                      ("setdest", self.on_setdest),
                      ("hastopo", self.on_has_topology),
                      ("clearzone", self.on_clear_zone),
                      ("requestzone", self.on_request_zone),
                      ("jumpcam", self.on_jump_cam),
                      ("cleanup", self.on_clean_up)):
            e.stub(SYM[k], fn)
        # Clear leaves retail's -1 in LastPointToScore.
        pcc.retail_clear(e)
        self.install_fakes()
        self.put(pcc.G_USENEWCAL, 1)
        self.put(pcc.G_UGLY, fb(1.0))
        if poison is not None:
            fill = struct.pack("<I", poison) * (SCRUB // 4)

            def scrub(em):
                sp = em.reg[29] & M32
                em.mem[sp - SCRUB:sp] = fill
            for k in RESET_ENTRIES + ("finish",):
                e.hook(SYM[k], scrub)

    # ---- the heap

    def cstr(self, a):
        s = bytearray()
        while self.e.mem[a] and len(s) < 64:
            s.append(self.e.mem[a])
            a += 1
        return s.decode("ascii", "replace")

    def register(self, name, a, size, t=None):
        self.reg.append((name, a, size, t))
        self.names[a] = name

    def on_malloc(self, em):
        size, flags, pool = s32(em.reg[4]), s32(em.reg[6]), s32(em.reg[7])
        if self.quiet:
            # trackpath_check's slack: the spline reads past its points.
            p = em.alloc(size + 16, 64)
            em.mem[p:p + size + 16] = bytes(size + 16)
            return p
        name = self.cstr(em.reg[5] & M32)
        p = em.alloc(size, 64)
        em.mem[p:p + size] = b"\xa5" * size
        self.nalloc += 1
        nm = "%s#%d" % (name, self.nalloc)
        t = name if name in ("PhysicsCar", "NullController") else None
        self.register(nm, p, size, t)
        self.say("alloc %s size=%d flags=%d pool=%d" % (nm, size, flags,
                                                         pool))
        return p

    def free(self, p):
        nm = self.names.get(p)
        self.say("free %s" % (nm if nm else self.label(p)))
        if nm:
            size = [r[2] for r in self.reg if r[1] == p][-1]
            self.e.mem[p:p + size] = b"\xdd" * size

    def on_free(self, em):
        self.free(em.reg[4] & M32)

    # ---- the ground and the topology

    def elevation(self, em):
        # physicscar_check's plane, which always writes a normal; the
        # flat-on-track probe asks for none, so what it writes at 0 is put
        # back.
        if em.reg[7] & M32:
            mmc.Model.elevation(self, em)
        else:
            low = bytes(self.e.mem[0:16])
            mmc.Model.elevation(self, em)
            self.e.mem[0:16] = low

    def on_clear_bbox(self, em):
        self.say("clearbbox tc=%s" % self.label(em.reg[4] & M32))

    # ---- the animated driver and the editor link

    def on_adrv(self, what):
        def f(em):
            self.say("adrv %s this=%s" % (what, self.label(em.reg[4] & M32)))
        return f

    def on_esp(self, em):
        self.say("esp obj=%s pos=%s" % (self.label(em.reg[4] & M32),
                                        self.label(em.reg[5] & M32)))

    # ---- slice nine's five seams, and RealDriver::ForceEBrakeStop

    def on_effect(self, em):
        pos = em.reg[7] & M32
        at = ""
        if pos:
            at = " at=" + " ".join("%08x" % self.w(pos + 4 * k)
                                   for k in range(4))
        self.say("effect car=%s fx=%d scale=%08x where=%08x pos=%s%s" % (
            self.label(em.reg[4] & M32), s32(em.reg[5]),
            em.fpr[12] & M32, em.reg[6] & M32, self.label(pos), at))

    def on_snd_blow(self, em):
        self.say("sound blowout %s" % self.label(em.reg[4] & M32))

    def on_ebrake(self, em):
        self.say("ebrake drv=%s on=%d" % (self.label(em.reg[4] & M32),
                                          s32(em.reg[5])))

    def on_pursued(self, em):
        self.say("pursued mgr=%s car=%s -> %d" % (
            self.label(em.reg[4] & M32), self.label(em.reg[5] & M32),
            self.pursued))
        return self.pursued & M32

    def on_line_speed(self, em):
        r = LINE_SPEED0 + 0.5 * self.nline
        self.nline += 1
        self.say("linespeed ctl=%s -> %08x" % (self.label(em.reg[4] & M32),
                                               fb(r)))
        em.set_f(0, r)

    def on_setdest(self, em):
        self.say("setdest mover=%s pos=%s angle=%d speed=%08x time=%08x" % (
            self.label(em.reg[4] & M32), self.label(em.reg[5] & M32),
            s32(em.reg[6]), em.fpr[12] & M32, em.fpr[13] & M32))

    # ---- slice eleven's topology test and the four Player seams

    def on_has_topology(self, em):
        xy = em.reg[5] & M32
        if not self.fm_topo:
            raise RuntimeError("HasTopology reached with no answer scripted")
        r = self.fm_topo.pop(0)
        self.say("hastopo tc=%s xy=%08x %08x -> %d" % (
            self.label(em.reg[4] & M32), self.w(xy), self.w(xy + 4), r))
        return r

    def on_clear_zone(self, em):
        p = em.reg[4] & M32
        self.say("clearzone p=%s sound=%d zone=%d" % (
            self.label(p), s32(em.reg[5]), s32(self.w(p + FM_PL_ZONE))))
        self.put(p + FM_PL_ZONE, 0)

    def on_request_zone(self, em):
        p = em.reg[4] & M32
        z = s32(em.reg[5])
        self.say("requestzone p=%s zone=%d force=%d b2=%d b3=%d -> %d" % (
            self.label(p), z, s32(em.reg[6]), s32(em.reg[7]),
            s32(em.reg[8]), self.fm_rz))
        if self.fm_rz:
            self.put(p + FM_PL_ZONE, z & M32)
        return self.fm_rz

    def on_jump_cam(self, em):
        self.say("jumpcam p=%s -> %d" % (self.label(em.reg[4] & M32),
                                         self.fm_jc))
        return self.fm_jc

    def on_clean_up(self, em):
        self.say("cleanupjumpcam p=%s" % self.label(em.reg[4] & M32))

    # ---- the stand-ins

    def new_fake_driver(self):
        p = self.zalloc(DRIVER_SIZE)
        self.put(p + DRV_VT, FAKE_VT_DRIVER)
        self.nfake += 1
        self.register("fdrv#%d" % self.nfake, p, DRIVER_SIZE)
        return p

    def say_ctor(self, cls, mem, car):
        # The car's two modes as the constructor finds them: both methods
        # store the new mode before the arm, and a class may read it.
        self.say("ctor %s mem=%s car=%s modes=%d/%d" % (
            cls, self.label(mem), self.label(car),
            s32(self.w(car + CAR["TheControlMode"])),
            s32(self.w(car + CAR["TheMovementMode"]))))

    def install_fakes(self):
        e = self.e
        fns = [FAKE_FN]

        def entry(vt, slot, fn):
            a = fns[0]
            fns[0] += 16
            e.stub(a, fn)
            e.mem[vt + slot:vt + slot + 4] = bytes(4)
            e.put32(vt + slot + 4, a)

        def dtor(cls):
            def f(em):
                this, flags = em.reg[4] & M32, s32(em.reg[5])
                self.say("dtor %s this=%s flags=%d" % (cls, self.label(this),
                                                       flags))
                if flags & 1:
                    self.free(this)
            return f

        for k, (mode, cls, ctor, size) in enumerate(MOVERS):
            vt = fake_vt("mover", k)
            entry(vt, 8, dtor(cls))

            def mctor(em, cls=cls, vt=vt):
                mem, car = em.reg[4] & M32, em.reg[5] & M32
                self.say_ctor(cls, mem, car)
                self.put(mem + MOVER_VT, vt)
                return mem
            e.stub(ctor, mctor)

        for k, (mode, cls, ctor, size) in enumerate(CONTROLLERS):
            vt = fake_vt("controller", k)
            entry(vt, 8, dtor(cls))

            def stpm(em, cls=cls):
                self.say("stpm %s this=%s other=%s" % (
                    cls, self.label(em.reg[4] & M32),
                    self.label(em.reg[5] & M32)))
            entry(vt, 88, stpm)

            # The three the resets reach.
            def setroute(em, cls=cls):
                self.say("setroute %s this=%s route=%s point=%s" % (
                    cls, self.label(em.reg[4] & M32),
                    self.label(em.reg[5] & M32), self.label(em.reg[6] & M32)))
            entry(vt, 40, setroute)

            def findwhere(em, cls=cls):
                self.say("findwhere %s this=%s" % (
                    cls, self.label(em.reg[4] & M32)))
            entry(vt, 72, findwhere)

            def justreset(em, cls=cls):
                self.say("justreset %s this=%s" % (
                    cls, self.label(em.reg[4] & M32)))
            entry(vt, 80, justreset)

            def cctor(em, cls=cls, vt=vt):
                mem, car = em.reg[4] & M32, em.reg[5] & M32
                self.say_ctor(cls, mem, car)
                d = self.new_fake_driver()
                self.put(mem, car)
                self.put(mem + 4, d)
                self.put(mem + CTRL_VT, vt)
                return mem
            e.stub(ctor, cctor)

        entry(FAKE_VT_DRIVER, 8, dtor("fdrv"))

        def snap(em):
            self.say("snapshot this=%s snap=%s" % (
                self.label(em.reg[4] & M32), self.label(em.reg[5] & M32)))
        entry(FAKE_VT_DRIVER, 24, snap)

        def lowgear(em):
            self.say("lowgear fdrv this=%s" % self.label(em.reg[4] & M32))
        entry(FAKE_VT_DRIVER, 48, lowgear)

        # The step's: each mover's Move, and the route and point the
        # controllers hand Move's reset.
        for k, (mode, cls, ctor, size) in enumerate(MOVERS):
            def mmove(em, cls=cls):
                r = MOVE_RET0 + 0.25 * self.nmove
                self.nmove += 1
                self.say("mover-move %s this=%s dt=%08x -> %08x" % (
                    cls, self.label(em.reg[4] & M32), em.fpr[12] & M32,
                    fb(r)))
                em.set_f(0, r)
            entry(fake_vt("mover", k), 16, mmove)
        for k, (mode, cls, ctor, size) in enumerate(CONTROLLERS):
            def getroute(em, cls=cls):
                self.say("getroute %s this=%s" % (
                    cls, self.label(em.reg[4] & M32)))
                return self.route
            entry(fake_vt("controller", k), 48, getroute)

            def getpoint(em, cls=cls):
                self.say("getpoint %s this=%s" % (
                    cls, self.label(em.reg[4] & M32)))
                return self.rpt
            entry(fake_vt("controller", k), 56, getpoint)

    # ---- labels

    def mover_objects(self):
        car = self.car
        m = self.w(car + CAR["pCarMover"])
        mode = s32(self.w(car + CAR["TheMovementMode"]))
        if not m:
            return []
        if mode == 0:
            return [("nm", m, "NullMover")]
        o = []
        if mode == 1:
            po = LAYOUT["PhysicsCar"]
            o.append(("pc", m, "PhysicsCar"))
            for nm, fld, t in (("body", "pBody", "RigidBody"),
                               ("steer", "pSteering",
                                "TwoWheelAckermanSteering")):
                o.append((nm, self.w(m + po.off(fld)), t))
            for i in range(4):
                o.append(("wheel%d" % i, self.w(m + po.off("pWheel") + 4 * i),
                          "Wheel"))
            for i in range(4):
                o.append(("susp%d" % i,
                          self.w(m + po.off("pSuspension") + 4 * i),
                          "Suspension"))
            for nm, fld, t in (("engine", "pEngine", "Engine"),
                               ("dtrain", "pDriveTrain", "DriveTrain"),
                               ("aero", "pAerodynamics", "Aerodynamics")):
                o.append((nm, self.w(m + po.off(fld)), t))
        elif mode == 4:
            mo = LAYOUT["MellowMover"]
            o.append(("mm", m, "MellowMover"))
            for nm, fld, t in (("mv", "pMellovator", "Mellovator"),
                               ("body", "pBody", "RigidBody"),
                               ("aero", "pAerodynamics", "Aerodynamics")):
                o.append((nm, self.w(m + mo.off(fld)), t))
            for i in range(4):
                o.append(("wheel%d" % i,
                          self.w(m + mo.off("pWheels") + 4 * i), "Wheel"))
        return [x for x in o if x[1]]

    def objects(self):
        o = []
        if self.car:
            o.append(("cs", self.car + CAR["State"], "CarState"))
            o.append(("tc", self.car + CAR["TheTopologyCoordinate"], TC_SIZE))
            o.append(("tpc", self.car + CAR["TheTrackPathCoordinate"],
                      TPC_SIZE))
            o.append(("car", self.car, CAR_SIZE))
            o.append(("car2", self.car2, CAR_SIZE))
            o.append(("ccb", self.ccb, CCB_SIZE))
            o.append(("ccb2", self.ccb2, CCB_SIZE))
            o.append(("cti", self.cti, 1368))
            o.append(("topo", pcc.TOPO, 16))
            o.append(("di", self.di, 20))
            o.append(("tgt", self.tgt, TGT_SIZE))
            if self.rm:
                o.append(("rm", self.rm, RM_SIZE))
                for i, s in enumerate(self.snaps):
                    o.append(("snap%d" % i, s, SNAP_SIZE))
                o.append(("player", self.player, 16))
                o.append(("route", self.route, 16))
                o.append(("rpt", self.rpt, RPT_SIZE))
                o.append(("pos", self.vec, 16))
            if self.full:
                o.extend(self.mover_objects())
        for nm, a, size, t in reversed(self.reg):
            o.append((nm, a, t if t else size))
        return o

    # ---- the dump

    def pools(self):
        self.say("pools " + " ".join("%s=%d" % (n, c)
                                     for n, c in zip(POOLS, self.inuse)))

    def car_line(self):
        c = self.car
        mover = self.w(c + CAR["pCarMover"])
        self.say("car ctrl=%d move=%d controller=%s driver=%s mover=%s "
                 "mover.drv=%s friction=%08x boost=%08x" % (
                     s32(self.w(c + CAR["TheControlMode"])),
                     s32(self.w(c + CAR["TheMovementMode"])),
                     self.label(self.w(c + CAR["pCarController"])),
                     self.label(self.w(c + CAR["pCarDriver"])),
                     self.label(mover),
                     self.label(self.w(mover)) if mover else "-",
                     self.w(c + CAR["FrictionBoost"]),
                     self.w(c + CAR["State"] + OFF("CarState",
                                                   "BoostFactor"))))

    def ccb_line(self):
        b = self.ccb
        self.say("ccb mode=%d system=%s body=%s" % (
            s32(self.w(b + CB_MODE)), self.label(self.w(b + CB_SYSTEM)),
            self.label(self.w(b + CB_BODY))))

    def mover_dump(self):
        c = self.car
        m = self.w(c + CAR["pCarMover"])
        mode = s32(self.w(c + CAR["TheMovementMode"]))
        if mode == 0:
            self.dump("NullMover", "nm", m)
        elif mode == 1:
            po = LAYOUT["PhysicsCar"]
            self.dump("PhysicsCar", "pc", m)
            self.dump("RigidBody", "body", self.w(m + po.off("pBody")))
            self.dump("TwoWheelAckermanSteering", "steer",
                      self.w(m + po.off("pSteering")))
            for i in range(4):
                self.dump("Wheel", "wheel%d" % i,
                          self.w(m + po.off("pWheel") + 4 * i))
            for i in range(4):
                self.dump("Suspension", "susp%d" % i,
                          self.w(m + po.off("pSuspension") + 4 * i))
            self.dump("Engine", "engine", self.w(m + po.off("pEngine")))
            self.dump("DriveTrain", "dtrain", self.w(m + po.off("pDriveTrain")))
            self.dump("Aerodynamics", "aero",
                      self.w(m + po.off("pAerodynamics")))
        elif mode == 4:
            mo = LAYOUT["MellowMover"]
            self.dump("MellowMover", "mm", m)
            self.dump("Mellovator", "mv", self.w(m + mo.off("pMellovator")))
            self.dump("RigidBody", "body", self.w(m + mo.off("pBody")))
            self.dump("Aerodynamics", "aero",
                      self.w(m + mo.off("pAerodynamics")))
            for i in range(4):
                self.dump("Wheel", "wheel%d" % i,
                          self.w(m + mo.off("pWheels") + 4 * i))
        else:
            self.say("mover vt=%08x" % self.w(m + MOVER_VT))

    def step(self, tag, driver=False):
        self.full = True
        self.say("-- " + tag)
        self.car_line()
        self.ccb_line()
        self.mover_dump()
        ctrl = self.w(self.car + CAR["pCarController"])
        if ctrl:
            self.dump("CarController", "ctrl", ctrl)
        if driver:
            self.raw("drv", "bytes", self.w(self.car + CAR["pCarDriver"]),
                     DRIVER_SIZE)
        self.dump("CarState", "cs", self.car + CAR["State"])
        self.pools()
        self.full = False

    # ---- calls

    def fcall(self, fn, *args, floats=()):
        for i, v in enumerate(floats):
            self.e.fpr[12 + i] = fb(v)
        return self.e.call(fn, *args)

    def vcall(self, obj, vptr_off, slot, *args, floats=()):
        vt = self.w(obj + vptr_off)
        delta = struct.unpack("<h", self.e.read(vt + slot, 2))[0]
        return self.fcall(self.w(vt + slot + 4), (obj + delta) & M32, *args,
                          floats=floats)

    def set_move(self, m):
        self.fcall(SYM["move"], self.car, m)

    def set_ctrl(self, m):
        self.fcall(SYM["ctrl"], self.car, m)

    def cur_ctrl(self):
        return self.w(self.car + CAR["pCarController"])

    def cur_drv(self):
        return self.w(self.car + CAR["pCarDriver"])

    def cur_mover(self):
        return self.w(self.car + CAR["pCarMover"])

    def f0(self):
        return self.e.fpr[0] & M32

    # ---- the scenarios

    def s_tables(self):
        self.say("== tables")
        syms = self.e.elf.syms
        for t in TABLES:
            vt = VT[t]
            n = syms["_vt$%d%s" % (len(t), t)][1] // 8
            cells = ["n=%d" % n]
            for i in range(1, n):
                delta = struct.unpack("<h", self.e.read(vt + 8 * i, 2))[0]
                fn = self.w(vt + 8 * i + 4)
                if fn == PURE or (t, 8 * i) in PENDING:
                    fn = 0
                cells.append("%d/%s" % (delta, "%08x" % fn if fn else "null"))
            self.say("vt %s %s" % (t, " ".join(cells)))

    def s_setup(self):
        e = self.e
        cti = self.cti = e.alloc(1376, 64)
        e.write(cti, self.ctis[0] + bytes(8))
        car = self.car = self.zalloc(CAR_SIZE)
        self.car2 = self.zalloc(CAR_SIZE)
        ccb = self.ccb = self.zalloc(CCB_SIZE)
        self.ccb2 = self.zalloc(CCB_SIZE)
        di = self.di = self.zalloc(20)
        tgt = self.tgt = self.zalloc(TGT_SIZE)
        e.mem[tgt:tgt + TGT_SIZE] = tgt_pattern()
        self.put(car + CAR["pCarTypeInfo"], cti)
        self.put(car + CAR["MyDriver"], di)
        self.put(car + CAR["pDynamicCollisionBody"], ccb)
        self.put(ccb + CB_CAR, car)
        self.put(self.ccb2 + CB_CAR, self.car2)
        self.put(car + CAR["FrictionBoost"], fb(FRICTION0))
        e.mem[car + CAR["RenderingEnabled"]] = 1
        cs = car + CAR["State"]
        L = LAYOUT["CarState"]
        self.put(cs + L.off("pCarInfo"), cti)
        self.put(cs + L.off("pTopologyCoordinate"), pcc.TOPO)
        self.put(cs + L.off("Position") + 8, fb(0.4375))
        for i in range(3):
            self.put(cs + L.off("BodyMatrix") + 20 * i, fb(1.0))
        self.put(cs + L.off("BodyMatrix") + 60, fb(1.0))
        for i in range(4):
            e.mem[cs + L.off("WheelTouchingGround") + i] = 1
        self.put(cs + L.off("nWheelsTouchingGround"), 4)
        self.put(cs + L.off("BoostFactor"), fb(1.0))

        self.say("== setup")
        self.set_move(0)
        self.step("move null->0")
        self.set_ctrl(0)
        self.step("ctrl null->0", driver=True)

    def s_move_walk(self):
        for a, b in zip(MOVE_WALK, MOVE_WALK[1:]):
            self.say("== move %d->%d" % (a, b))
            self.set_move(b)
            self.step("after")

    def s_ctrl_walk(self):
        for a, b in zip(CTRL_WALK, CTRL_WALK[1:]):
            self.say("== ctrl %d->%d" % (a, b))
            self.set_ctrl(b)
            self.step("after", driver=(b == 0))

    def s_ctrl_under(self):
        # The tail stores the new driver into whichever mover there is.
        for mv in (1, 4):
            self.say("== ctrl under %d" % mv)
            self.set_move(mv)
            for b in (2, 0):
                self.set_ctrl(b)
                self.step("ctrl %d" % b)
        self.set_move(0)

    def s_stpm(self):
        for kind in STPM_KINDS:
            want = 2 if kind == "fake" else 0
            for m in range(7):
                self.say("== stpm %s %d" % (kind, m))
                if s32(self.w(self.car + CAR["TheControlMode"])) != want:
                    self.set_ctrl(want)
                self.set_move(m)
                saved = self.cur_ctrl()
                if kind == "none":
                    self.put(self.car + CAR["pCarController"], 0)
                self.fcall(SYM["stpm"], self.car, self.car2)
                if kind == "none":
                    self.put(self.car + CAR["pCarController"], saved)
                self.step("after")
        self.set_ctrl(0)
        self.set_move(0)

    def s_ccb(self):
        c2 = self.ccb2
        for ctl, mv in ((2, 1), (0, 0), (0, 2)):
            for o in CCB_OTHER:
                self.say("== ccb stpm ctrl=%d move=%d other=%s"
                         % (ctl, mv, "null" if o is None else o))
                if s32(self.w(self.car + CAR["TheControlMode"])) != ctl:
                    self.set_ctrl(ctl)
                self.set_move(mv)
                if o is not None:
                    self.e.mem[c2 + CB_TYPE] = o
                # Stale pointers, so the set-up after the call shows even
                # where the mode switch inside it did one already.
                self.put(self.ccb + CB_SYSTEM, self.cti + 4)
                self.put(self.ccb + CB_BODY, self.cti + 8)
                self.fcall(SYM["ccb-stpm"], self.ccb, 0 if o is None else c2)
                self.step("after")
        self.set_ctrl(0)
        for pm, mv in SETUP_CASES:
            self.say("== ccb setup mode=%d move=%d" % (pm, mv))
            self.set_move(mv)
            self.put(self.ccb + CB_MODE, pm & M32)
            self.put(self.ccb + CB_SYSTEM, self.cti + 4)
            self.put(self.ccb + CB_BODY, self.cti + 8)
            self.fcall(SYM["ccb-setup"], self.ccb)
            self.full = True
            self.ccb_line()
            self.full = False
        self.set_move(0)

    def mover_extent(self, m):
        # The pooled two by their record's size; the rest by what bMalloc
        # was asked for.
        mode = s32(self.w(self.car + CAR["TheMovementMode"]))
        if mode == 0:
            return LAYOUT["NullMover"].size
        if mode == 4:
            return LAYOUT["MellowMover"].size
        return [r[2] for r in self.reg if r[1] == m][-1]

    def s_friction(self):
        # Past the mover's last byte is the next slot or the next block,
        # which no dump reaches; a store through the wrong type lands there.
        for m in range(7):
            self.say("== friction %d" % m)
            self.set_move(m)
            mv = self.cur_mover()
            end = mv + self.mover_extent(mv)
            before = bytes(self.e.mem[end:end + STRAY])
            self.fcall(SYM["friction"], self.car, floats=[FRICTION[m]])
            after = bytes(self.e.mem[end:end + STRAY])
            self.say("past mover %s" % ("same" if after == before
                                         else "written"))
            self.step("after")
        self.set_move(0)

    def s_nullmover(self):
        self.say("== nullmover")
        nm = self.cur_mover()
        self.e.fpr[0] = fb(JUNK_F)
        self.vcall(nm, MOVER_VT, 16, floats=[DT])
        self.say("move ret=%08x" % self.f0())
        self.vcall(nm, MOVER_VT, 24, self.cti + 40)
        self.step("move")
        self.vcall(nm, MOVER_VT, 8, 0)
        self.say("dtor0 vt=%08x" % self.w(nm + MOVER_VT))
        self.pools()
        self.fcall(SYM["nm-delete"], nm)
        self.pools()
        self.put(self.car + CAR["pCarMover"], 0)
        self.set_move(0)
        self.step("again")

    def s_nullcontroller(self):
        self.say("== nullcontroller")
        c = self.cur_ctrl()
        self.vcall(c, CTRL_VT, 16)
        self.vcall(c, CTRL_VT, 32, floats=[DT])
        self.vcall(c, CTRL_VT, 40, self.cti + 16, self.cti + 32)
        self.say("route=%s" % self.label(self.vcall(c, CTRL_VT, 48) & M32))
        self.say("point=%s" % self.label(self.vcall(c, CTRL_VT, 56) & M32))
        self.e.fpr[0] = fb(JUNK_F)
        self.vcall(c, CTRL_VT, 64)
        self.say("oob=%08x" % self.f0())
        self.vcall(c, CTRL_VT, 72)
        self.vcall(c, CTRL_VT, 80)
        bf = self.car + CAR["State"] + OFF("CarState", "BoostFactor")
        self.vcall(c, CTRL_VT, 96, floats=[BOOST[0]])
        self.say("force boost=%08x" % self.w(bf))
        self.vcall(c, CTRL_VT, 104)
        self.say("release boost=%08x" % self.w(bf))
        self.vcall(c, CTRL_VT, 96, floats=[BOOST[1]])
        self.put(c, 0)
        self.vcall(c, CTRL_VT, 104)
        self.say("release no car boost=%08x" % self.w(bf))
        self.vcall(c, CTRL_VT, 96, floats=[BOOST[0]])
        self.say("force no car boost=%08x" % self.w(bf))
        self.put(c, self.car)
        self.vcall(c, CTRL_VT, 104)
        self.say("driver=%s" % self.label(
            self.fcall(SYM["get-driver"], c) & M32))
        self.step("after")

    def driver_calls(self, d, table):
        """Every entry of the driver's table but the destructor and
        DoSnapshot, and the pure ones of CarDriver's."""
        v = lambda slot, *a, **k: self.vcall(d, DRV_VT, slot, *a, **k)
        null = table == "NullDriver"
        if null:
            v(16, floats=[DT])
        v(32)
        v(40)
        if null:
            v(48)
            v(56, 1, floats=list(DSPEED))
        v(64, self.tgt)
        v(72, self.cti + 8)
        if null:
            self.say("number=%d" % v(80))
        v(88)
        v(96)
        self.say("honking=%d" % v(104))
        self.e.fpr[0] = fb(JUNK_F)
        v(112, self.tgt)
        self.say("maxspeed=%08x" % self.f0())
        v(120)
        v(128)
        self.e.fpr[0] = fb(JUNK_F)
        v(136)
        self.say("speed=%08x" % self.f0())
        self.e.fpr[0] = fb(JUNK_F)
        v(144)
        self.say("time=%08x" % self.f0())
        v(152, 1)
        self.say("point=%s" % self.label(v(160) & M32))
        self.raw("drv", "bytes", d, DRIVER_SIZE)

    def s_nulldriver(self):
        self.say("== nulldriver")
        self.driver_calls(self.cur_drv(), "NullDriver")
        # A CarDriver of its own, from the image's out-of-line constructor,
        # over the heap's pattern.
        self.say("== cardriver")
        p = self.zalloc(DRIVER_SIZE)
        self.e.mem[p:p + DRIVER_SIZE] = b"\xa5" * DRIVER_SIZE
        self.register("cdrv", p, DRIVER_SIZE)
        self.fcall(SYM["cd-ctor"], p)
        self.raw("cdrv", "bytes", p, DRIVER_SIZE)
        self.driver_calls(p, "CarDriver")
        self.vcall(p, DRV_VT, 8, 0)
        self.say("dtor0 vt=%08x" % self.w(p + DRV_VT))
        self.vcall(p, DRV_VT, 8, 1)

    def s_dtors(self):
        # NullController without the delete bit: the driver goes, the
        # controller stays with the base's vptr.
        self.say("== dtor nullcontroller 0")
        c = self.cur_ctrl()
        self.vcall(c, CTRL_VT, 8, 0)
        self.say("ctrl vt=%08x" % self.w(c + CTRL_VT))
        self.free(c)
        self.put(self.car + CAR["pCarController"], 0)
        self.set_ctrl(0)
        self.step("again", driver=True)

        # NullDriver without the delete bit, then through CarDriver's table
        # with it; the controller is then left with no driver, which its
        # destructor skips.
        self.say("== dtor nulldriver 0")
        d = self.cur_drv()
        self.vcall(d, DRV_VT, 8, 0)
        self.say("drv vt=%08x" % self.w(d + DRV_VT))
        self.vcall(d, DRV_VT, 8, 1)
        self.put(self.cur_ctrl() + 4, 0)
        self.set_ctrl(0)
        self.step("again", driver=True)

        # NullController over a stand-in driver, which prints the flags its
        # destructor is handed: 3, though nothing below tests bit 1.
        self.say("== dtor nullcontroller fdrv")
        c = self.cur_ctrl()
        self.put(c + 4, self.new_fake_driver())
        self.vcall(c, CTRL_VT, 8, 1)
        self.put(self.car + CAR["pCarController"], 0)
        self.set_ctrl(0)
        self.step("again", driver=True)

        # The base on its own: its constructor, DoSnapshot through a
        # stand-in driver, and its destructor both ways.
        self.say("== carcontroller")
        cc = self.zalloc(12)
        self.e.mem[cc:cc + 12] = b"\xa5" * 12
        self.register("cc", cc, 12, "CarController")
        self.fcall(SYM["cc-ctor"], cc, self.car)
        self.put(cc + 4, self.new_fake_driver())
        self.full = True
        self.dump("CarController", "cc", cc)
        self.full = False
        self.vcall(cc, CTRL_VT, 24, self.cti + 40)
        self.vcall(cc, CTRL_VT, 16)
        self.vcall(cc, CTRL_VT, 8, 0)
        self.say("cc vt=%08x" % self.w(cc + CTRL_VT))
        self.vcall(cc, CTRL_VT, 8, 1)
        self.pools()

    # ---- the resets

    def reset_setup(self):
        e = self.e
        self.say("== reset setup")
        ws = track_words()
        ch = self.zalloc(4 * len(ws))
        for i, x in enumerate(ws):
            self.put(ch + 4 * i, x)
        self.quiet = True
        r = self.fcall(SYM["tp-loader"], ch)
        self.quiet = False
        self.say("loader -> %d" % s32(r))
        self.put(G_WORLD_TIMER, WORLD_TIMER)

        rm = self.rm = self.zalloc(RM_SIZE)
        self.put(rm + RM_FREE, rm + RM_FREE)
        self.put(rm + RM_FREE + 4, rm + RM_FREE)
        head = rm + RM_SNAPSHOTS
        for name, tiv in SNAPS:
            s = self.zalloc(SNAP_SIZE)
            e.mem[s + SNAP_NAME:s + SNAP_NAME + len(name)] = name.encode()
            self.put(s + SNAP_TIV, fb(tiv))
            self.snaps.append(s)
        ring = [head] + self.snaps
        for i, a in enumerate(ring):
            self.put(a, ring[(i + 1) % len(ring)])
            self.put(a + 4, ring[i - 1])
        self.player = self.zalloc(16)
        self.route = self.zalloc(16)
        self.rpt = self.zalloc(RPT_SIZE)
        e.mem[self.rpt:self.rpt + RPT_SIZE] = rpt_bytes()
        self.vec = self.zalloc(16)

    def reset_prep(self, ctl, mv, player):
        c = self.car
        if s32(self.w(c + CAR["TheControlMode"])) != ctl:
            self.set_ctrl(ctl)
        self.set_move(mv)
        self.put(c + CAR["pPlayer"],
                 self.player if player not in (None, "bystander") else 0)
        self.put(G_REPLAY, 0 if player == "nomgr" else self.rm)
        self.put(self.rm + RM_CAPTURING,
                 1 if player in ("cap", "bystander") else 0)
        self.put(c + CAR["BlinkTimer"], BLINK0[0])
        self.put(c + CAR["BlinkDuration"], fb(BLINK0[1]))

    def reset_dump(self):
        self.step("after")
        c = self.car
        t = c + CAR["TheTrackPathCoordinate"]
        pt = self.w(t + 8)
        idx = -1 if pt == 0 else s32(pt - self.w(TP_MGR + MGR_POINTS)) // 20
        self.say("tpc pos=%s pt=%d param=%08x ratio=%08x dist=%08x dir=%s" % (
            hexw([self.w(t), self.w(t + 4)]), idx, self.w(t + 12),
            self.w(t + 16), self.w(t + 20),
            hexw([self.w(t + 24), self.w(t + 28)])))
        self.say("blink timer=%d duration=%08x" % (
            s32(self.w(c + CAR["BlinkTimer"])), self.w(c + CAR["BlinkDuration"])))
        self.say("replay tiv=%s" % hexw([self.w(s + SNAP_TIV)
                                         for s in self.snaps]))

    def s_reset(self):
        self.reset_setup()
        for i, (kind, ctl, mv, pl, pos, speed, angle) in enumerate(RESETS):
            self.say("== reset %d %s" % (i, kind))
            self.reset_prep(ctl, mv, pl)
            for k, v in enumerate(pos):
                self.put(self.vec + 4 * k, fb(v))
            sym = {"pos": "reset-pos", "core": "reset-core",
                   "debug": "debug-pos"}[kind]
            self.fcall(SYM[sym], self.car, self.vec, angle, floats=[speed])
            self.reset_dump()
        for i, (ctl, mv, pl, route, point, speed, blink, d) in enumerate(
                ROUTE_RESETS):
            self.say("== reset route %d" % i)
            self.reset_prep(ctl, mv, pl)
            self.fcall(SYM["reset-route"], self.car,
                       self.route if route else 0, self.rpt if point else 0,
                       blink, floats=[speed, d])
            self.reset_dump()
        self.set_ctrl(0)
        self.set_move(0)

    # ---- the step

    def move_setup(self):
        self.say("== move setup")
        self.adrv = self.zalloc(ADRV_SIZE)
        self.register("adrv", self.adrv, ADRV_SIZE)
        self.caff = self.zalloc(16)
        self.register("caff", self.caff, 16)
        self.car3 = self.zalloc(CAR_SIZE)
        self.plc = self.zalloc(PL_SIZE)
        self.pl = [self.zalloc(PL_SIZE) for _ in range(2)]
        self.rc = [self.zalloc(RC_SIZE) for _ in range(3)]
        self.put(self.plc + PL_MYCAR, self.car)
        for i, (pl, car) in enumerate(zip(self.pl, (self.car3, self.car2))):
            self.put(pl + PL_MYCAR, car)
            self.put(pl + PL_NUMBER, i)
            self.put(G_BYNUMBER + 4 * i, pl)
        for car, rc in zip((self.car, self.car3, self.car2), self.rc):
            self.put(car + CAR["pRacingCar"], rc)
        self.say("tracklength=%08x" % self.w(TP_MGR))

    def diff_dump(self):
        ws = [self.w(DIFF + DIFF_KNEES + 4 * i) for i in range(8)]
        self.say("diff knees = %s" % hexw(ws))

    def move_case(self, i, m):
        (ctl, move, gear, disp, adrv, reset, bt, bd, pen, player, boost,
         np, laps, caff, full, now) = m
        c = self.car
        cs = c + CAR["State"]
        self.say("== move %d" % i)
        if s32(self.w(c + CAR["TheControlMode"])) != ctl:
            self.set_ctrl(ctl)
        if s32(self.w(c + CAR["TheMovementMode"])) != move:
            self.set_move(move)
        self.put(cs + OFF("CarState", "CurrentGear"), gear & M32)
        self.put(c + CAR["DispGear"], disp & M32)
        self.put(c + CAR["pAnimatedDriver"], self.adrv if adrv else 0)
        self.put(c + CAR["ResetMe"], reset & M32)
        self.put(c + CAR["BlinkTimer"], bt)
        self.put(c + CAR["BlinkDuration"], fb(bd))
        self.put(self.ccb + CB_PEN, pen)
        self.put(c + CAR["pCaffeineObj"], self.caff if caff else 0)
        self.put(c + CAR["pPlayer"], 
                 self.plc if player != NO_PLAYER else 0)
        self.put(self.plc + PL_NUMBER, player & M32)
        self.put(G_BOOST, boost & M32)
        self.put(G_NUMPLAYERS, np & M32)
        for rc, lap in zip(self.rc, laps):
            self.put(rc + RC_LAPS, fb(lap))
        self.put(cs + OFF("CarState", "BoostFactor"), fb(BOOST_MARK))
        self.put(G_WORLD_TIMER, now)
        self.fcall(SYM["car-move"], c, floats=[MOVE_DT])
        r = self.f0()
        self.say("moved -> %08x gear=%d disp=%d resetme=%d blink=%d/%08x "
                 "boost=%08x" % (
                     r, s32(self.w(cs + OFF("CarState", "CurrentGear"))),
                     s32(self.w(c + CAR["DispGear"])),
                     s32(self.w(c + CAR["ResetMe"])),
                     s32(self.w(c + CAR["BlinkTimer"])),
                     self.w(c + CAR["BlinkDuration"]),
                     self.w(cs + OFF("CarState", "BoostFactor"))))
        if full:
            self.step("after")

    def s_move(self):
        self.move_setup()
        d = diff_chunk()
        good = self.zalloc(len(d))
        self.e.mem[good:good + len(d)] = d
        bad = self.zalloc(len(d))
        self.e.mem[bad:bad + len(d)] = d
        self.e.mem[bad] ^= 1
        self.say("== difficulty")
        self.say("unload %d %d" % (self.fcall(SYM["diff-unloader"], bad),
                                   self.fcall(SYM["diff-unloader"], good)))
        self.say("load bad -> %d" % self.fcall(SYM["diff-loader"], bad))
        self.diff_dump()
        for i, m in enumerate(CATCHUP):
            self.move_case(-1 - i, m)
        self.say("load -> %d" % self.fcall(SYM["diff-loader"], good))
        self.diff_dump()
        for i, m in enumerate(MOVES):
            self.move_case(i, m)
        self.set_ctrl(0)
        self.set_move(0)

    # ---- slice nine

    def blown(self, what):
        c = self.car
        self.say("%s bits=%02x num=%d timer=%08x" % (
            what, self.e.mem[c + CAR["BlownTireBits"]],
            self.e.mem[c + CAR["NumBlownTires"]],
            self.w(c + CAR["fBlownTireControllerRumbleTimer"])))

    def set_blown(self, bits, num):
        c = self.car
        self.e.mem[c + CAR["BlownTireBits"]] = bits & 0xff
        self.e.mem[c + CAR["NumBlownTires"]] = num & 0xff
        self.put(c + CAR["fBlownTireControllerRumbleTimer"], fb(RACE_TIMER0))

    def s_race(self):
        c = self.car
        self.say("== race setup")
        self.dist = self.zalloc(4)
        self.register("dist", self.dist, 4)
        self.snd = self.zalloc(SND_SIZE)
        self.register("snd", self.snd, SND_SIZE)
        self.copmgr = self.zalloc(COPMGR_SIZE)
        self.register("copmgr", self.copmgr, COPMGR_SIZE)
        self.dpos = self.zalloc(8)
        self.register("dpos", self.dpos, 8)
        for i, (a, b) in enumerate(((self.car, self.car2),
                                    (self.car2, self.car))):
            self.say("== dist %d" % i)
            self.put(self.dist, DIST_MARK)
            self.fcall(SYM["dist"], self.dist, a, b)
            self.say("dist -> %08x speed=%08x" % (self.f0(),
                                                  self.w(self.dist)))
        for i, mode in enumerate(FIX):
            self.say("== fix %d" % i)
            if s32(self.w(c + CAR["TheControlMode"])) != mode:
                self.set_ctrl(mode)
            self.set_blown(0x0b, 3)
            self.fcall(SYM["fix"], c)
            self.blown("fixed")
        self.set_ctrl(0)
        for i, (bits, tires, num, snd) in enumerate(BLOW):
            self.say("== blow %d" % i)
            self.set_blown(bits, num)
            self.put(c + CAR["pBaseCarSound"], self.snd if snd else 0)
            self.fcall(SYM["blow"], c, tires & M32)
            self.blown("blown")
        self.put(c + CAR["pBaseCarSound"], 0)
        self.set_blown(0, 0)
        self.put(c + CAR["fBlownTireControllerRumbleTimer"], 0)
        dtype = self.w(self.di + DI_TYPE)
        for i, (bc, mc, dt, pu, mgr) in enumerate(LATER):
            self.say("== later %d" % i)
            self.put(G_BEACOP, bc & M32)
            self.put(G_MAXCOPS, mc & M32)
            self.put(self.di + DI_TYPE, dt & M32)
            self.pursued = pu
            self.put(G_COPMGR, self.copmgr if mgr else 0)
            self.put(c + CAR["ResetMe"], RESET_MARK)
            self.fcall(SYM["later"], c)
            self.say("later resetme=%d" % s32(self.w(c + CAR["ResetMe"])))
        self.put(G_BEACOP, 0)
        self.put(G_MAXCOPS, 0)
        self.put(self.di + DI_TYPE, dtype)
        self.put(G_COPMGR, 0)
        self.put(c + CAR["ResetMe"], 0)
        for i, mode in enumerate(LINE):
            self.say("== line %d" % i)
            if s32(self.w(c + CAR["TheControlMode"])) != mode:
                self.set_ctrl(mode)
            self.fcall(SYM["line"], c)
            self.say("line -> %08x" % self.f0())
        self.set_ctrl(0)
        for i, (frm, angle, speed, t) in enumerate(DELIVER):
            self.say("== deliver %d" % i)
            if s32(self.w(c + CAR["TheMovementMode"])) != frm:
                self.set_move(frm)
            self.fcall(SYM["deliver"], c, self.dpos, angle & M32,
                       floats=[speed, t])
            self.say("delivered move=%d mover=%s" % (
                s32(self.w(c + CAR["TheMovementMode"])),
                self.label(self.cur_mover())))
        self.set_move(0)

    def s_finish(self):
        c = self.car
        e = self.e
        cs = c + CAR["State"]

        def at(field, k=0):
            return cs + OFF("CarState", field) + k
        self.say("== finish setup")
        self.set_ctrl(0)
        pl = self.zalloc(FM_PL_SIZE)
        self.register("fmplayer", pl, FM_PL_SIZE)
        world = self.zalloc(WD_TABLE + 4 * FM_NCARS)
        self.register("world", world, WD_TABLE + 4 * FM_NCARS)
        others = []
        for i in range(FM_NCARS - 1):
            o = self.zalloc(CAR_SIZE)
            self.register("other%d" % i, o, CAR_SIZE)
            others.append(o)
            self.put(world + WD_TABLE + 4 * (i + 1), o)
        self.put(world + WD_TABLE, c)
        col = self.zalloc(COL_SIZE)
        self.register("col", col, COL_SIZE)
        wit = self.zalloc(WIT_SIZE)
        self.register("wit", wit, WIT_SIZE)
        body = self.zalloc(CB_BODY_SIZE)
        self.register("obody", body, CB_BODY_SIZE)
        self.put(col + COL_WIT, wit)
        wlist0 = (self.w(G_WLIST), self.w(G_WLIST + 4))
        type0 = (e.mem[self.ccb + CB_TYPE], e.mem[self.ccb2 + CB_TYPE])
        mode0 = self.w(c + CAR["TheMovementMode"])
        player0 = self.w(c + CAR["pPlayer"])
        paths0 = self.w(TP_MGR + TP_NUMPATHS)
        rm0 = self.w(G_REPLAY)
        for r in range(4):
            for k in range(4):
                v = fb(1.0 if r == k else 0.0)
                self.put(at("BodyMatrix", 16 * r + 4 * k), v)
                self.put(at("WheelMatrix", 16 * r + 4 * k), v)
        self.put(self.rm + RM_CAPTURING, 1)
        self.put(G_WORLD, world)
        t = c + CAR["TheTrackPathCoordinate"]
        for n, x in enumerate(FINISH):
            self.say("== finish %d" % n)
            for k in range(4):
                self.put(at("Acceleration", 4 * k), fb(FM_ACC[k]))
                self.put(at("AngularAcceleration", 4 * k), fb(FM_ACC[k]))
                self.put(at("Velocity", 4 * k), fb(x["vel"][k]))
                self.put(c + FM_CAR["vOldVel"] + 4 * k, fb(FM_OLDVEL[k]))
                self.put(at("AngularVelocity", 4 * k), fb(FM_ANG[k]))
                self.put(c + FM_CAR["vOldAngVel"] + 4 * k, fb(FM_OLDANG[k]))
                self.put(at("Position", 4 * k), fb(x["pos"][k]))
            self.put(at("Odometer"), fb(x["odo"]))
            self.put(at("VelocityMagnitude"), fb(x["vmag"]))
            self.put(at("nWheelsTouchingGround"), x["wheels"] & M32)
            self.put(at("ForwardSpeed"), fb(x["fwd"]))
            e.mem[at("Angle"):at("Angle") + 2] = struct.pack(
                "<H", x["angle"] & 0xffff)
            self.put(t, fb(x["pos"][0]))
            self.put(t + 4, fb(x["pos"][1]))
            self.put(t + 8, 0 if x["tp"] is None
                     else self.w(TP_MGR + MGR_POINTS) + 20 * x["tp"])
            self.put(TP_MGR + TP_NUMPATHS, 0 if x["nopaths"] else paths0)
            self.put(c + CAR["TheMovementMode"], x["mode"] & M32)
            self.put(c + CAR["ResetMe"], 0)
            self.put(c + FM_CAR["ForceHeadlightsOn"], x["lights"])
            self.put(c + FM_CAR["HeadlightsState"], 0)
            self.put(G_LOOP, x["loop"] & M32)
            self.put(G_WORLD_TIMER, x["now"] & M32)
            self.put(G_BORING, x["boring"])
            self.put(G_NOREPLAY, x["disable"])
            self.put(c + CAR["pPlayer"], pl if x["player"] else 0)
            self.put(pl + FM_PL_ZONE, x["zone"] & M32)
            self.put(pl + FM_PL_WRONG, x["wrong"] & M32)
            self.put(pl + FM_PL_EYEZ, fb(x["eye"]))
            self.put(c + FM_CAR["AirTimeSwitch"], fb(x["ats"]))
            self.fm_topo = list(x["topo"])
            self.fm_jc, self.fm_rz = x["jc"], x["rz"]
            self.put(world + WD_AI, x["ai"] & M32)
            self.put(world + WD_COP, x["cop"] & M32)
            for o, p in zip(others, x["table"]):
                for k in range(3):
                    self.put(o + CAR["State"] + OFF("CarState", "Position")
                             + 4 * k, fb(p[k]))
            if x["col"] is not None:
                kind, ago, order, has, selftype = x["col"]
                other = self.ccb2 if kind == "car" else body
                e.mem[other + CB_TYPE] = FM_KIND_TYPE[kind]
                e.mem[self.ccb + CB_TYPE] = selftype
                e.mem[self.ccb + CB_NCOL] = 1
                b1, b2 = (self.ccb, other) if order == 0 else (other, self.ccb)
                self.put(wit + WIT_B1, b1)
                self.put(wit + WIT_B2, b2)
                self.put(wit + WIT_COL, col if has else 0)
                self.put(wit, G_WLIST)
                self.put(wit + 4, G_WLIST)
                self.put(G_WLIST, wit)
                self.put(G_WLIST + 4, wit)
                self.put(col + COL_LCT, (x["now"] - ago) & M32)
            self.put(G_REPLAY, self.rm if x["rm"] else 0)
            for s in self.snaps:
                self.put(s + SNAP_TIV, 0)
            self.fcall(SYM["finish"], c, floats=[x["dt"]])
            if self.fm_topo:
                raise RuntimeError("finish %d left HasTopology answers" % n)
            self.put(G_WLIST, wlist0[0])
            self.put(G_WLIST + 4, wlist0[1])
            e.mem[self.ccb + CB_TYPE], e.mem[self.ccb2 + CB_TYPE] = type0
            e.mem[self.ccb + CB_NCOL] = 0
            pt = self.w(t + 8)
            idx = -1 if pt == 0 else s32(pt - self.w(TP_MGR + MGR_POINTS)) // 20
            self.say("fm acc=%s ang=%s odo=%08x resetme=%d lights=%d" % (
                hexw([self.w(at("Acceleration", 4 * k)) for k in range(4)]),
                hexw([self.w(at("AngularAcceleration", 4 * k))
                      for k in range(4)]),
                self.w(at("Odometer")), s32(self.w(c + CAR["ResetMe"])),
                s32(self.w(c + FM_CAR["HeadlightsState"]))))
            self.say("fm tpc=%s pt=%d zone=%d eye=%08x ats=%08x tiv=%s" % (
                hexw([self.w(t), self.w(t + 4)]), idx,
                s32(self.w(pl + FM_PL_ZONE)), self.w(pl + FM_PL_EYEZ),
                self.w(c + FM_CAR["AirTimeSwitch"]),
                hexw([self.w(s + SNAP_TIV) for s in self.snaps])))
        self.put(c + CAR["pPlayer"], player0)
        self.put(c + CAR["TheMovementMode"], mode0)
        self.put(c + CAR["ResetMe"], 0)
        self.put(G_WORLD, 0)
        self.put(G_LOOP, LOOP0)
        self.put(G_BORING, 0)
        self.put(G_NOREPLAY, 0)
        self.put(G_REPLAY, rm0)
        self.put(TP_MGR + TP_NUMPATHS, paths0)

    def run(self):
        self.s_tables()
        self.s_setup()
        self.s_move_walk()
        self.s_ctrl_walk()
        self.s_ctrl_under()
        self.s_stpm()
        self.s_ccb()
        self.s_friction()
        self.s_nullmover()
        self.s_nullcontroller()
        self.s_nulldriver()
        self.s_dtors()
        self.s_reset()
        self.s_move()
        self.s_race()
        self.s_finish()
        return self.out


def cti_record():
    return pcc.cti_records()[0]


class Garbage(Exception):
    pass


def merge(a, b):
    """The two poisoned runs, as one transcript with `*` for the fourth
    lane of a PAD_LANES line that differs between them. Nothing else may."""
    if len(a) != len(b):
        raise Garbage("the two poisoned runs printed %d and %d lines: the "
                      "image's control flow reads unwritten memory"
                      % (len(a), len(b)))
    out, stray = [], []
    for i, (x, y) in enumerate(zip(a, b)):
        if x == y:
            out.append(x)
            continue
        tx, ty = x.split(" "), y.split(" ")
        if (len(tx) == len(ty) == 6 and tx[1] == "=" and tx[0] in PAD_LANES
                and tx[:5] == ty[:5]):
            out.append(" ".join(tx[:5] + ["*"]))
        else:
            stray.append((i, x, y))
            out.append(x)
    if stray:
        msg = ["a token outside the pad lanes depends on unwritten memory:"]
        for i, x, y in stray[:10]:
            msg.append("  %d: %s" % (i, x))
            msg.append("  %d: %s" % (i, y))
        raise Garbage(NL.join(msg))
    return out


def unmask(img, port):
    """A `*` matches whatever the port printed in that column, on a line
    whose every other token is the same."""
    out = []
    for i, x in enumerate(img):
        tx = x.split(" ")
        if "*" in tx and i < len(port):
            tp = port[i].split(" ")
            if len(tp) == len(tx) and all(u == "*" or u == v
                                          for u, v in zip(tx, tp)):
                out.append(port[i])
                continue
        out.append(x)
    return out


def model(cti=None):
    cti = cti or cti_record()
    return merge(Model(cti, POISONS[0]).run(), Model(cti, POISONS[1]).run())


# ================================================================ the build

def build_harness(tmp, cti, name="carmode_test"):
    text = generate(cti) + HARNESS.read_text(encoding="utf-8")
    src = Path(tmp) / "carmode_test.c"
    src.write_text(text, encoding="utf-8", newline=NL)
    return hostbuild.build(tmp, [str(src)] + SOURCES_PORT, name=name)


run_harness = pcc.run_harness


def diff(img, port, quiet=False):
    return pcc.diff(unmask(img, port), port, quiet=quiet)

# ============================================================ the mutations

CCH = "3DS Files/source/carcontroller.h"
CDH = "3DS Files/source/cardriver.h"
MOVE_DTOR = "CARMOVER_VT_DTOR);" + NL + "        ((DtorFn)e->fn)(vt_this(old, e), "
CTRL_DTOR = "CARCONTROLLER_VT_DTOR);" + NL + "        ((DtorFn)e->fn)(vt_this(old, e), "
CC_SKIP = ("    if (car->TheMovementMode == PHYSICS_MOVEMENT" + NL
           + "        || car->TheMovementMode == MELLOW_MOVEMENT)" + NL
           + "        return;")
SETUP_MODES = ("    if (car->TheMovementMode != PHYSICS_MOVEMENT" + NL
               + "        && car->TheMovementMode != MELLOW_MOVEMENT)")


def swap(a, b):
    """Two adjacent lines the other way round, in the first place they are
    adjacent."""
    return [(a + NL + b, b + NL + a, 1)]


def moved(line, anchor, after):
    """`line` out of where it is and next to `anchor`, before or after."""
    return [(line + NL, "", 1),
            (anchor, anchor + NL + line if after else line + NL + anchor, 1)]


MUTATIONS = [
    # ---- NullMover
    ("nm-delete-wrong-pool", CMC, "    bSlotFree(NullMoverSlotPool, p);",
     "    bSlotFree(MellowMoverSlotPool, p);"),
    ("nm-dtor-no-base", CMC, "    carmover_destroy(&m->Mover, 0);" + NL, ""),
    ("nm-dtor-always-delete", CMC,
     "    if (flags & 1)" + NL + "        nullmover_delete(m);",
     "    nullmover_delete(m);"),
    ("nm-dtor-never-delete", CMC,
     "    if (flags & 1)" + NL + "        nullmover_delete(m);",
     "    (void)flags;"),
    ("nm-move-returns-zero", CMC, "    return dt;", "    return 0.0f;"),
    ("nm-move-no-wheel-matrices", CMC,
     "    carstate_calculate_wheel_matrices(m->pState);" + NL, ""),
    ("nm-vt-move-snapshot-swap", CMC, swap(
        "    { 0, 0, (VtFn)nullmover_move },                 // 16  0x0012f1f0",
        "    { 0, 0, (VtFn)carmover_do_snapshot },           // 24  0x0012f1e8")),
    ("nm-vt-address", CMH, "#define NULLMOVER_VTABLE     0x002923c0u",
     "#define NULLMOVER_VTABLE     0x002923c8u"),

    # ---- SetControlMode
    ("ctrl-no-old-dtor", CMC,
     "    if (old != NULL) {" + NL
     + "        const VtEntry *e = vt_slot(old->_vtable, CARCONTROLLER_VT_DTOR);",
     "    if (0 && old != NULL) {" + NL
     + "        const VtEntry *e = vt_slot(old->_vtable, CARCONTROLLER_VT_DTOR);"),
    ("ctrl-dtor-flags-1", CMC, CTRL_DTOR + "3);", CTRL_DTOR + "1);"),
    ("ctrl-mode-after-arm", CMC, moved("    c->TheControlMode = mode;",
                                       "    c->pCarController = ctrl;", True)),
    ("ctrl-no-controller-store", CMC, "    c->pCarController = ctrl;" + NL, ""),
    ("ctrl-driver-kept", CMC, "    c->pCarDriver = ctrl->Driver;" + NL, ""),
    ("ctrl-no-mover-driver", CMC,
     "    c->pCarDriver = ctrl->Driver;" + NL
     + "    c->pCarMover->Driver = c->pCarDriver;",
     "    c->pCarDriver = ctrl->Driver;"),
    ("ctrl-ai-seam-traffic", CMC,
     "new_controller(gAIDriverCtorFn, AIDRIVER_SIZE,",
     "new_controller(gTrafficDriverCtorFn, AIDRIVER_SIZE,"),
    ("ctrl-ai-traffic-cases", CMC, [
        ("    case AI_CONTROL:", "    case 99:", 1),
        ("    case TRAFFIC_CONTROL:", "    case AI_CONTROL:", 1),
        ("    case 99:", "    case TRAFFIC_CONTROL:", 1)]),
    ("ctrl-real-name", CMC, '"RealController", c);', '"RealControl", c);'),
    ("ctrl-cop-size-real", CMC,
     "new_controller(gCopDriverCtorFn, COPDRIVER_SIZE,",
     "new_controller(gCopDriverCtorFn, REALCONTROLLER_SIZE,"),
    # new_mover's is the first of the two.
    ("ctrl-flags-1", CMC,
     "    mem = bMalloc(size, name, 0, CAR_MEMORY_POOL);" + NL
     + "    return ctor(mem, car);" + NL + "}" + NL + NL + "// ---",
     "    mem = bMalloc(size, name, 1, CAR_MEMORY_POOL);" + NL
     + "    return ctor(mem, car);" + NL + "}" + NL + NL + "// ---"),
    ("mover-flags-1", CMC, [
        ("    mem = bMalloc(size, name, 0, CAR_MEMORY_POOL);",
         "    mem = bMalloc(size, name, 1, CAR_MEMORY_POOL);", 1)]),
    ("size-trafficcar", CMH,
     "#define TRAFFICCAR_SIZE       ((int)sizeof(TrafficCar))",
     "#define TRAFFICCAR_SIZE       ((int)sizeof(TrafficCar) + 4)"),
    ("size-deliverymover", CMH, "#define DELIVERYMOVER_SIZE   192",
     "#define DELIVERYMOVER_SIZE   196"),
    ("size-copmover", CMH,
     "#define COPMOVER_SIZE        ((int)sizeof(CopMover))",
     "#define COPMOVER_SIZE        ((int)sizeof(CopMover) + 4)"),
    ("size-beltmover", CMH,
     "#define BELTMOVER_SIZE       ((int)sizeof(BeltMover))",
     "#define BELTMOVER_SIZE       ((int)sizeof(BeltMover) + 4)"),
    ("size-realcontroller", CMH,
     "#define REALCONTROLLER_SIZE  ((int)sizeof(RealController))",
     "#define REALCONTROLLER_SIZE  ((int)sizeof(RealController) + 4)"),
    ("size-aidriver", CMH,
     "#define AIDRIVER_SIZE        ((int)sizeof(AIDriver))",
     "#define AIDRIVER_SIZE        ((int)sizeof(AIDriver) + 4)"),
    ("size-trafficdriver", CMH,
     "#define TRAFFICDRIVER_SIZE   ((int)sizeof(TrafficDriver))",
     "#define TRAFFICDRIVER_SIZE   ((int)sizeof(TrafficDriver) + 4)"),
    ("size-copdriver", CMH, "#define COPDRIVER_SIZE        76",
     "#define COPDRIVER_SIZE        80"),
    ("pool-not-16", CMH, "#define CAR_MEMORY_POOL 16",
     "#define CAR_MEMORY_POOL 0"),

    # ---- the null controller and its driver
    ("nc-size", CCC,
     "    ctrl = (NullController *)bMalloc((int)sizeof(NullController),",
     "    ctrl = (NullController *)bMalloc((int)sizeof(NullController) + 4,"),
    ("nc-name", CCC, '"NullController", 0, CAR_MEMORY_POOL);',
     '"NullControl", 0, CAR_MEMORY_POOL);'),
    ("nc-no-base-ctor", CCC, "    carcontroller_init(&ctrl->Base, c);" + NL,
     ""),
    ("nc-no-vptr", CCC,
     "    ctrl->Base._vtable = NULLCONTROLLER_VTABLE;" + NL, ""),
    ("nd-size", CCC, 'bMalloc((int)sizeof(NullDriver), "NullDriver", 0,',
     'bMalloc((int)sizeof(NullDriver) + 4, "NullDriver", 0,'),
    ("nd-no-base-ctor", CCC, "    cardriver_init(&drv->Base);" + NL, ""),
    ("nd-vptr-before-ctor", CCC, moved(
        "    drv->Base._vtable = NULLDRIVER_VTABLE;",
        "    cardriver_init(&drv->Base);", False)),
    ("nc-no-driver", CCC, "    ctrl->Base.Driver = &drv->Base;" + NL, ""),
    ("nd-no-vptr", CCC, "    drv->Base._vtable = NULLDRIVER_VTABLE;" + NL, ""),

    # ---- SetMovementMode
    ("move-no-old-dtor", CMC,
     "    if (old != NULL) {" + NL
     + "        const VtEntry *e = vt_slot(old->_vtable, CARMOVER_VT_DTOR);",
     "    if (0 && old != NULL) {" + NL
     + "        const VtEntry *e = vt_slot(old->_vtable, CARMOVER_VT_DTOR);"),
    ("move-dtor-flags-1", CMC, MOVE_DTOR + "3);", MOVE_DTOR + "1);"),
    ("move-mode-after-arm", CMC, moved(
        "    c->TheMovementMode = mode;",
        "    carcollisionbody_setup_physics_pointers(c->pDynamicCollisionBody);",
        False)),
    ("move-mode-after-setup", CMC, moved(
        "    c->TheMovementMode = mode;",
        "    carcollisionbody_setup_physics_pointers(c->pDynamicCollisionBody);",
        True)),
    ("move-null-physicsmode-1", CMC,
     "        c->pCarMover = &m->Mover;" + NL
     + "        c->pDynamicCollisionBody->Dynamic.PhysicsMode = 0;",
     "        c->pCarMover = &m->Mover;" + NL
     + "        c->pDynamicCollisionBody->Dynamic.PhysicsMode = 1;"),
    ("move-pc-physicsmode-0", CMC,
     "        pc->FrictionBoost = c->FrictionBoost;" + NL
     + "        c->pDynamicCollisionBody->Dynamic.PhysicsMode = 1;",
     "        pc->FrictionBoost = c->FrictionBoost;" + NL
     + "        c->pDynamicCollisionBody->Dynamic.PhysicsMode = 0;"),
    ("move-mm-physicsmode-0", CMC,
     "        c->pCarMover = &mm->Mover;" + NL
     + "        c->pDynamicCollisionBody->Dynamic.PhysicsMode = 1;",
     "        c->pCarMover = &mm->Mover;" + NL
     + "        c->pDynamicCollisionBody->Dynamic.PhysicsMode = 0;"),
    ("move-traffic-physicsmode-1", CMC,
     '"TrafficCar", c);' + NL
     + "        c->pDynamicCollisionBody->Dynamic.PhysicsMode = 0;",
     '"TrafficCar", c);' + NL
     + "        c->pDynamicCollisionBody->Dynamic.PhysicsMode = 1;"),
    ("move-belt-physicsmode-kept", CMC,
     '"BeltMover", c);' + NL
     + "        c->pDynamicCollisionBody->Dynamic.PhysicsMode = 0;" + NL,
     '"BeltMover", c);' + NL),
    ("move-pc-no-friction", CMC,
     "        pc->FrictionBoost = c->FrictionBoost;" + NL, ""),
    ("move-pc-driver-null", CMC,
     "        pc = physicscar_init(pc, c->pCarTypeInfo, c->pCarDriver, c);",
     "        pc = physicscar_init(pc, c->pCarTypeInfo, NULL, c);"),
    ("move-mm-driver-null", CMC,
     "        mm = mellowmover_init(mm, c, c->pCarTypeInfo, c->pCarDriver,",
     "        mm = mellowmover_init(mm, c, c->pCarTypeInfo, NULL,"),
    ("move-pc-name", CMC, '"PhysicsCar", 0,', '"PhysicsCa", 0,'),
    ("move-nm-state-null", CMC, "        m->pState = &c->State;",
     "        m->pState = NULL;"),
    ("move-nm-no-vptr", CMC,
     "        m->Mover._vtable = NULLMOVER_VTABLE;" + NL + "        m->pState",
     "        m->pState"),
    ("move-no-setup", CMC,
     "    carcollisionbody_setup_physics_pointers(c->pDynamicCollisionBody);"
     + NL, ""),
    ("move-tail-no-driver", CMC,
     "    c->pCarMover->Driver = c->pCarDriver;" + NL + "}" + NL + NL
     + "void car_set_to_physics_mode",
     "}" + NL + NL + "void car_set_to_physics_mode"),
    ("move-delivery-seam-cop", CMC,
     "new_mover(gDeliveryMoverCtorFn, DELIVERYMOVER_SIZE,",
     "new_mover(gCopMoverCtorFn, DELIVERYMOVER_SIZE,"),
    ("move-cop-belt-cases", CMC, [
        ("    case COP_MOVEMENT:", "    case 99:", 1),
        ("    case BELT_MOVEMENT:", "    case COP_MOVEMENT:", 1),
        ("    case 99:", "    case BELT_MOVEMENT:", 1)]),
    ("move-cop-name", CMC, '"CopMover",', '"CopMove",'),

    # ---- SetToPhysicsMode
    ("stpm-no-return", CMC,
     "        ((SetToPhysicsModeFn)e->fn)(vt_this(ctrl, e), other);" + NL
     + "        return;",
     "        ((SetToPhysicsModeFn)e->fn)(vt_this(ctrl, e), other);"),
    ("stpm-other-dropped", CMC, "(vt_this(ctrl, e), other);",
     "(vt_this(ctrl, e), NULL);"),
    ("stpm-controller-ignored", CMC,
     "    if (ctrl != NULL) {" + NL
     + "        const VtEntry *e = vt_slot(ctrl->_vtable,",
     "    if (0 && ctrl != NULL) {" + NL
     + "        const VtEntry *e = vt_slot(ctrl->_vtable,"),
    ("stpm-no-fallback", CMC, "    carcontroller_physics_or_mellow(c);",
     "    (void)0;"),
    ("stpm-fallback-other", CMC, "    carcontroller_physics_or_mellow(c);",
     "    carcontroller_physics_or_mellow(other);"),
    ("stpm-controller-slot", CCH,
     "#define CARCONTROLLER_VT_SET_TO_PHYSICS_MODE      88",
     "#define CARCONTROLLER_VT_SET_TO_PHYSICS_MODE      80"),

    # ---- SetFrictionBoost
    ("friction-no-car-store", CMC, "    c->FrictionBoost = f;" + NL, ""),
    ("friction-mover-not-set", CMC,
     "        ((PhysicsCar *)c->pCarMover)->FrictionBoost = f;",
     "        (void)0;"),
    ("friction-mellow-too", CMC,
     "    if (c->TheMovementMode == PHYSICS_MOVEMENT)" + NL
     + "        ((PhysicsCar *)",
     "    if (c->TheMovementMode == PHYSICS_MOVEMENT"
     + " || c->TheMovementMode == MELLOW_MOVEMENT)" + NL
     + "        ((PhysicsCar *)"),

    # ---- CarController
    ("cc-init-no-car", CCC,
     "    c->pCar = car;" + NL + "    c->_vtable = CARCONTROLLER_VTABLE;",
     "    c->_vtable = CARCONTROLLER_VTABLE;"),
    ("cc-init-no-vptr", CCC,
     "    c->pCar = car;" + NL + "    c->_vtable = CARCONTROLLER_VTABLE;",
     "    c->pCar = car;"),
    ("cc-dtor-no-vptr", CCC,
     "int32_t flags)" + NL + "{" + NL + "    c->_vtable = CARCONTROLLER_VTABLE;"
     + NL,
     "int32_t flags)" + NL + "{" + NL),
    ("cc-dtor-always-delete", CCC, "    if (flags & 1)" + NL + "        bFree(c);",
     "    bFree(c);"),
    ("cc-dtor-never-delete", CCC, "    if (flags & 1)" + NL + "        bFree(c);",
     "    (void)flags;"),
    ("cc-snapshot-dropped", CCC,
     "    ((CarDriverDoSnapshotFn)e->fn)(vt_this(d, e), snap);",
     "    (void)e; (void)snap;"),
    ("cc-snapshot-no-arg", CCC, "(vt_this(d, e), snap);",
     "(vt_this(d, e), NULL);"),
    ("cc-stpm-physics-not-skipped", CCC, CC_SKIP,
     "    if (car->TheMovementMode == MELLOW_MOVEMENT)" + NL
     + "        return;"),
    ("cc-stpm-mellow-not-skipped", CCC, CC_SKIP,
     "    if (car->TheMovementMode == PHYSICS_MOVEMENT)" + NL
     + "        return;"),
    ("cc-stpm-goes-physics", CCC,
     "    car_set_movement_mode(car, car->pPlayer != NULL ? PHYSICS_MOVEMENT"
     + NL + "                                                    : "
     "MELLOW_MOVEMENT);",
     "    car_set_movement_mode(car, PHYSICS_MOVEMENT);"),
    ("cc-stpm-other-car", CCC,
     "    carcontroller_physics_or_mellow(c->pCar);",
     "    carcontroller_physics_or_mellow(car);"),
    ("cc-force-boost-no-check", CCC,
     "    if (c->pCar != NULL)" + NL + "        c->pCar->State.BoostFactor = f;",
     "    c->pCar->State.BoostFactor = f;"),
    ("cc-release-boost-zero", CCC,
     "        c->pCar->State.BoostFactor = 1.0f;",
     "        c->pCar->State.BoostFactor = 0.0f;"),
    ("cc-release-no-check", CCC,
     "    if (c->pCar != NULL)" + NL
     + "        c->pCar->State.BoostFactor = 1.0f;",
     "    c->pCar->State.BoostFactor = 1.0f;"),
    ("cc-get-driver-null", CCC, "    return c->Driver;", "    return NULL;"),
    ("cc-vt-boost-swap", CCC, swap(
        "    E(carcontroller_force_boost),                   //  96  0x001b6108",
        "    E(carcontroller_release_boost),                 // 104  0x001b6128")),

    # ---- NullController
    ("nc-dtor-driver-flags-1", CCC,
     "        ((CarDriverDtorFn)e->fn)(vt_this(d, e), 3);",
     "        ((CarDriverDtorFn)e->fn)(vt_this(d, e), 1);"),
    ("nc-dtor-no-null-check", CCC, "    if (d != NULL) {", "    if (1) {"),
    ("nc-dtor-no-driver", CCC, "    if (d != NULL) {", "    if (0 && d != NULL) {"),
    ("nc-dtor-no-base", CCC, "    carcontroller_destroy(&c->Base, flags);",
     "    (void)flags;"),
    ("nc-route-not-null", CCC,
     "nullcontroller_get_current_route(NullController *c, int find)" + NL
     + "{" + NL + "    (void)c;" + NL + "    (void)find;" + NL
     + "    return NULL;",
     "nullcontroller_get_current_route(NullController *c, int find)" + NL
     + "{" + NL + "    (void)c;" + NL + "    (void)find;" + NL
     + "    return (TrackRoute *)c;"),
    ("nc-point-not-null", CCC,
     "                                                       int find)" + NL
     + "{" + NL + "    (void)c;" + NL + "    (void)find;" + NL
     + "    return NULL;",
     "                                                       int find)" + NL
     + "{" + NL + "    (void)c;" + NL + "    (void)find;" + NL
     + "    return (TrackRoutePoint *)c;"),
    ("nc-oob-one", CCC, "    return 0.0f;                        // mtc1 zero,$f0",
     "    return 1.0f;                        // mtc1 zero,$f0"),
    ("nc-vt-route-point-swap", CCC, swap(
        "    E(nullcontroller_get_current_route),            //  48  0x00134a88",
        "    E(nullcontroller_get_current_route_point),      //  56  0x00134a80")),
    ("nc-vt-dtor-base", CCC,
     "    E(nullcontroller_destroy),                      //   8  0x00134aa0",
     "    E(carcontroller_destroy),                       //   8  0x00134aa0"),
    ("nc-vt-value", CCH, "#define NULLCONTROLLER_VTABLE    0x00292350u",
     "#define NULLCONTROLLER_VTABLE    0x00292358u"),

    # ---- CarCollisionBody
    # carcollisionbody_init clears both too, and comes first in the file,
    # so the set-up's are named by the test after them.
    ("ccb-setup-keeps-system", CBC,
     "    d->pSystem = NULL;" + NL + "    d->pBody = NULL;" + NL
     + "    if (d->PhysicsMode == 0)",
     "    d->pBody = NULL;" + NL + "    if (d->PhysicsMode == 0)"),
    ("ccb-setup-keeps-body", CBC,
     "    d->pBody = NULL;" + NL + "    if (d->PhysicsMode == 0)",
     "    if (d->PhysicsMode == 0)"),
    ("ccb-setup-mode-ignored", CBC,
     "    if (d->PhysicsMode == 0)" + NL + "        return;" + NL, ""),
    ("ccb-setup-mode-positive", CBC, "    if (d->PhysicsMode == 0)",
     "    if (d->PhysicsMode <= 0)"),
    ("ccb-setup-mellow-missing", CBC, SETUP_MODES,
     "    if (car->TheMovementMode != PHYSICS_MOVEMENT)"),
    ("ccb-setup-physics-missing", CBC, SETUP_MODES,
     "    if (car->TheMovementMode != MELLOW_MOVEMENT)"),
    ("ccb-setup-pc-body-is-system", CBC, "        d->pBody = pc->pBody;",
     "        d->pBody = &pc->Vehicle;"),
    ("ccb-setup-mm-system-is-body", CBC, "        d->pSystem = &mm->Vehicle;",
     "        d->pSystem = mm->pBody;"),
    ("ccb-stpm-type-ignored", CBC,
     "    if (other != NULL && other->Type == 0)", "    if (other != NULL)"),
    ("ccb-stpm-type-inverted", CBC, "other->Type == 0)", "other->Type != 0)"),
    ("ccb-stpm-no-setup", CBC,
     "    car_set_to_physics_mode(b->pCar, them);" + NL
     + "    carcollisionbody_setup_physics_pointers(b);",
     "    car_set_to_physics_mode(b->pCar, them);"),
    ("ccb-stpm-self", CBC, "    car_set_to_physics_mode(b->pCar, them);",
     "    car_set_to_physics_mode(b->pCar, b->pCar);"),

    # ---- NullDriver and the two driver tables
    ("nd-dtor-no-base", CDC,
     "    d->Base._vtable = NULLDRIVER_VTABLE;" + NL
     + "    cardriver_destroy(&d->Base, flags);",
     "    d->Base._vtable = NULLDRIVER_VTABLE;" + NL + "    (void)flags;"),
    ("nd-number", CDC, "    return NULLDRIVER_DRIVER_NUMBER;",
     "    return NULLDRIVER_DRIVER_NUMBER + 1;"),
    ("nd-set-target-copies", CDC,
     "    // drops it." + NL + "    (void)d; (void)t;",
     "    // drops it." + NL + "    cardriver_set_target(&d->Base, t);"),
    ("nd-vt-set-target-base", CDC,
     "    E(nulldriver_set_target),               //  64  0x00134cb0",
     "    E(cardriver_set_target),                //  64  0x00134cb0"),
    ("nd-vt-dtor-base", CDC,
     "    E(nulldriver_destroy),                  //   8  0x00134cc8",
     "    E(cardriver_destroy),                   //   8  0x00134cc8"),
    ("nd-vt-number-honk-swap", CDC, swap(
        "    E(nulldriver_get_driver_number),        //  80  0x00134ca0",
        "    E(cardriver_start_honk_horn),           //  88  0x00134d40")),
    ("cd-vt-memory-swap", CDC, swap(
        "    E(cardriver_zero_steering_memory),      // 120  0x00134d18",
        "    E(cardriver_clear_steering_memory),     // 128  0x00134d10")),
    ("cd-vt-drive-not-pure", CDC,
     "    { 0, 0, NULL },                         //  16  Drive",
     "    E(nulldriver_drive),                    //  16  Drive"),
    ("nd-vt-value", CDH, "#define NULLDRIVER_VTABLE 0x00292400u",
     "#define NULLDRIVER_VTABLE 0x00292408u"),

    # ---- ResetCore
    ("rc-no-null-mode", CRC,
     "    car_set_movement_mode(c, eNO_MOVEMENT);" + NL
     + "    carstate_reset_car(st);",
     "    carstate_reset_car(st);"),
    ("rc-mode-not-restored", CRC,
     "    car_set_movement_mode(c, mode);" + NL + "    if (c->pPlayer",
     "    car_set_movement_mode(c, eNO_MOVEMENT);" + NL + "    if (c->pPlayer"),
    ("rc-no-reset-car", CRC, "    carstate_reset_car(st);" + NL, ""),
    ("rc-no-tpc", CRC,
     "    trackpath_coord_update_position(&c->TheTrackPathCoordinate," + NL
     + "                                    (const bVector2 *)pos);" + NL
     + "    st->Angle = angle;",
     "    st->Angle = angle;"),
    ("rc-angle-zero", CRC, "    st->Angle = angle;", "    st->Angle = 0;"),
    ("rc-steer-kept", CRC, "    st->SteeringAngle = 0;" + NL, ""),
    ("rc-position-three-lanes", CRC, "    st->Position = *pos;",
     "    st->Position.x = pos->x;" + NL + "    st->Position.y = pos->y;" + NL
     + "    st->Position.z = pos->z;"),
    ("rc-no-clear-bbox", CRC,
     "    topology_clear_interest_bbox(&c->TheTopologyCoordinate);" + NL, ""),
    ("rc-no-forward-speed", CRC,
     "    st->ForwardSpeed = speed;" + NL + "    car_put_flat_on_track(c);" + NL
     + NL + "    dir.pad",
     "    car_put_flat_on_track(c);" + NL + NL + "    dir.pad"),
    ("rc-no-flat", CRC,
     "    car_put_flat_on_track(c);" + NL + NL + "    dir.pad",
     NL + "    dir.pad"),
    ("rc-bias-zero", CRC, "#define CAR_RESET_SPEED_BIAS 0.1f",
     "#define CAR_RESET_SPEED_BIAS 0.0f"),
    ("rc-bias-sub", CRC, "speed + CAR_RESET_SPEED_BIAS",
     "speed - CAR_RESET_SPEED_BIAS"),
    ("rc-normalize-row1", CRC, "&st->BodyMatrix.v0,", "&st->BodyMatrix.v1,"),
    ("rc-magnitude-speed", CRC,
     "    st->VelocityMagnitude = sqrtf((dir.x * dir.x + dir.y * dir.y)" + NL
     + "                                  + dir.z * dir.z);",
     "    st->VelocityMagnitude = speed + CAR_RESET_SPEED_BIAS;"),
    ("rc-magnitude-order", CRC,
     "sqrtf((dir.x * dir.x + dir.y * dir.y)" + NL
     + "                                  + dir.z * dir.z)",
     "sqrtf(dir.x * dir.x + (dir.y * dir.y" + NL
     + "                                  + dir.z * dir.z))"),
    ("rc-velocity-kept", CRC, "    st->Velocity = dir;" + NL, ""),
    ("rc-matrix-valid-kept", CRC, "    st->MatrixValid = 0;" + NL, ""),
    ("rc-wheel-radius-0", CRC, "cti->Wheels[i].Radius", "cti->Wheels[0].Radius"),
    ("rc-wheel-radius-3", CRC, "cti->Wheels[i].Radius", "cti->Wheels[3].Radius"),
    ("rc-wheels-three", CRC, "    for (i = 0; i < 4; i++)" + NL
     + "        st->WheelAngularVelocity[i]",
     "    for (i = 0; i < 3; i++)" + NL + "        st->WheelAngularVelocity[i]"),
    ("rc-wheel-speed-times", CRC, "st->ForwardSpeed / cti->Wheels[i].Radius",
     "st->ForwardSpeed * cti->Wheels[i].Radius"),
    ("rc-no-wheel-matrices", CRC,
     "    carstate_calculate_wheel_matrices(st);" + NL + NL + "    drv",
     NL + "    drv"),
    ("rc-no-low-gear", CRC,
     "    ((CarResetVoidFn)e->fn)(vt_this(drv, e));" + NL, ""),
    ("rc-low-gear-slot", CRC, "CARDRIVER_VT_SET_LOW_GEAR",
     "CARDRIVER_VT_ADD_JOY_HANDLERS"),
    ("rc-low-gear-after-mode", CRC,
     "    drv = c->pCarDriver;" + NL
     + "    e = vt_slot(drv->_vtable, CARDRIVER_VT_SET_LOW_GEAR);" + NL
     + "    ((CarResetVoidFn)e->fn)(vt_this(drv, e));" + NL + NL
     + "    car_set_movement_mode(c, mode);" + NL,
     "    car_set_movement_mode(c, mode);" + NL
     + "    drv = c->pCarDriver;" + NL
     + "    e = vt_slot(drv->_vtable, CARDRIVER_VT_SET_LOW_GEAR);" + NL
     + "    ((CarResetVoidFn)e->fn)(vt_this(drv, e));" + NL + NL),
    ("rc-no-invalidate", CRC,
     "    if (c->pPlayer != NULL && pReplayManager != NULL)" + NL
     + "        ReplayManager_InvalidateInterestingEvents(pReplayManager);" + NL,
     ""),
    ("rc-invalidate-always", CRC,
     "c->pPlayer != NULL && pReplayManager != NULL",
     "pReplayManager != NULL"),
    ("rc-no-manager-test", CRC,
     "c->pPlayer != NULL && pReplayManager != NULL", "c->pPlayer != NULL"),

    # ---- ResetToPosition
    ("rp-no-core", CRC,
     "    car_reset_core(c, pos, speed, angle);" + NL + "    trackpath",
     "    trackpath"),
    ("rp-no-tpc", CRC,
     "    car_reset_core(c, pos, speed, angle);" + NL
     + "    trackpath_coord_update_position(&c->TheTrackPathCoordinate," + NL
     + "                                    (const bVector2 *)&c->State.Position);"
     + NL,
     "    car_reset_core(c, pos, speed, angle);" + NL),
    ("rp-no-find", CRC,
     "    controller_call(c, CARCONTROLLER_VT_FIND_WHERE_I_AM);" + NL, ""),
    ("rp-no-just-reset", CRC,
     "    controller_call(c, CARCONTROLLER_VT_JUST_RESET);" + NL
     + "    car_stop_blinking(c);",
     "    car_stop_blinking(c);"),
    ("rp-find-reset-swap", CRC, swap(
        "    controller_call(c, CARCONTROLLER_VT_FIND_WHERE_I_AM);",
        "    controller_call(c, CARCONTROLLER_VT_JUST_RESET);")),
    ("rp-no-stop-blink", CRC, "    car_stop_blinking(c);" + NL, ""),
    ("rp-start-blink", CRC, "    car_stop_blinking(c);",
     "    car_start_blinking(c, 2.0f);"),

    # ---- ResetToRoutePoint
    ("rr-no-route-test", CRC,
     "    if (route == NULL || point == NULL)", "    if (point == NULL)"),
    ("rr-no-point-test", CRC,
     "    if (route == NULL || point == NULL)", "    if (route == NULL)"),
    ("rr-z-length", CRC, "    pos.z = point->Elevation;",
     "    pos.z = point->Length;"),
    ("rr-y-from-x", CRC, "    pos.y = point->Position.y;",
     "    pos.y = point->Position.x;"),
    ("rr-dir-unscaled", CRC,
     "bATan(point->Direction.x * direction," + NL
     + "                  point->Direction.y * direction)",
     "bATan(point->Direction.x," + NL + "                  point->Direction.y)"),
    ("rr-atan-swap", CRC,
     "bATan(point->Direction.x * direction," + NL
     + "                  point->Direction.y * direction)",
     "bATan(point->Direction.y * direction," + NL
     + "                  point->Direction.x * direction)"),
    ("rr-no-tpc", CRC,
     "    car_reset_core(c, &pos, speed, (uint16_t)angle);" + NL
     + "    trackpath_coord_update_position(&c->TheTrackPathCoordinate," + NL
     + "                                    (const bVector2 *)&c->State.Position);"
     + NL,
     "    car_reset_core(c, &pos, speed, (uint16_t)angle);" + NL),
    ("rr-route-slot", CRC, "CARCONTROLLER_VT_SET_CURRENT_ROUTE",
     "CARCONTROLLER_VT_FIND_WHERE_I_AM"),
    ("rr-no-point-arg", CRC, "(vt_this(ctrl, e), route, point);",
     "(vt_this(ctrl, e), route, NULL);"),
    ("rr-no-just-reset", CRC,
     "    controller_call(c, CARCONTROLLER_VT_JUST_RESET);" + NL + NL
     + "    if (blink)",
     NL + "    if (blink)"),
    ("rr-find-too", CRC,
     "    controller_call(c, CARCONTROLLER_VT_JUST_RESET);" + NL + NL
     + "    if (blink)",
     "    controller_call(c, CARCONTROLLER_VT_FIND_WHERE_I_AM);" + NL
     + "    controller_call(c, CARCONTROLLER_VT_JUST_RESET);" + NL + NL
     + "    if (blink)"),
    ("rr-blink-always", CRC,
     "    if (blink)" + NL + "        car_start_blinking(c, 2.0f);",
     "    car_start_blinking(c, 2.0f);"),
    ("rr-blink-never", CRC,
     "    if (blink)" + NL + "        car_start_blinking(c, 2.0f);",
     "    (void)blink;"),
    ("rr-blink-duration", CRC, "        car_start_blinking(c, 2.0f);",
     "        car_start_blinking(c, 1.0f);"),
    ("rr-else-stop", CRC,
     "    if (blink)" + NL + "        car_start_blinking(c, 2.0f);",
     "    if (blink)" + NL + "        car_start_blinking(c, 2.0f);" + NL
     + "    else" + NL + "        car_stop_blinking(c);"),

    # ---- DebugSetPosition
    ("dp-no-null-mode", CRC,
     "    car_set_movement_mode(c, eNO_MOVEMENT);" + NL
     + "    st->Position.x = pos->x;",
     "    st->Position.x = pos->x;"),
    ("dp-mode-not-restored", CRC,
     "    st->Velocity.z = 0.0f;" + NL + "    car_set_movement_mode(c, mode);",
     "    st->Velocity.z = 0.0f;" + NL
     + "    car_set_movement_mode(c, eNO_MOVEMENT);"),
    ("dp-x-kept", CRC, "    st->Position.x = pos->x;" + NL, ""),
    ("dp-z-too", CRC, "    st->Position.y = pos->y;" + NL,
     "    st->Position.y = pos->y;" + NL + "    st->Position.z = pos->z;" + NL),
    ("dp-no-tpc", CRC,
     "    trackpath_coord_update_position(&c->TheTrackPathCoordinate," + NL
     + "                                    (const bVector2 *)pos);" + NL
     + "    st->Angle = (uint16_t)",
     "    st->Angle = (uint16_t)"),
    ("dp-angle-absolute", CRC,
     "    st->Angle = (uint16_t)(angle + (uint32_t)bATan(tpc->PathDirection.x,"
     + NL + "                                                   "
     "tpc->PathDirection.y));",
     "    st->Angle = angle;"),
    ("dp-angle-sub", CRC, "angle + (uint32_t)bATan", "angle - (uint32_t)bATan"),
    ("dp-atan-swap", CRC,
     "bATan(tpc->PathDirection.x," + NL
     + "                                                   tpc->PathDirection.y)",
     "bATan(tpc->PathDirection.y," + NL
     + "                                                   tpc->PathDirection.x)"),
    ("dp-no-flat", CRC,
     "    car_put_flat_on_track(c);" + NL + "    st->ForwardSpeed = speed;",
     "    st->ForwardSpeed = speed;"),
    ("dp-no-speed", CRC,
     "    st->ForwardSpeed = speed;" + NL + "    st->Velocity.x",
     "    st->Velocity.x"),
    ("dp-cos-sin-swap", CRC,
     "    st->Velocity.x = speed * bCosBam(st->Angle);" + NL
     + "    st->Velocity.y = speed * bSinBam(st->Angle);",
     "    st->Velocity.x = speed * bSinBam(st->Angle);" + NL
     + "    st->Velocity.y = speed * bCosBam(st->Angle);"),
    ("dp-relative-trig", CRC, "speed * bCosBam(st->Angle)",
     "speed * bCosBam(angle)"),
    ("dp-velocity-z-kept", CRC, "    st->Velocity.z = 0.0f;" + NL, ""),

    # ---- RegisterInterestingEvent
    ("ev-capture-ignored", RPC,
     "    if (!rm->CapturingFlag)" + NL + "        return;" + NL, ""),
    ("ev-capture-inverted", RPC, "    if (!rm->CapturingFlag)",
     "    if (rm->CapturingFlag)"),
    ("ev-name-prefix", RPC, 'strcmp(s->Name, "INSTANT_REPLAY") == 0',
     'strncmp(s->Name, "INSTANT_REPLAY", 14) == 0'),
    ("ev-name-short", RPC, 'strcmp(s->Name, "INSTANT_REPLAY") == 0',
     'strncmp(s->Name, "INSTANT_REPLAY", 13) == 0'),
    ("ev-every-snapshot", RPC,
     '        if (strcmp(s->Name, "INSTANT_REPLAY") == 0)' + NL, ""),
    ("ev-subtract", RPC, "s->TotalInterestingValue + value",
     "s->TotalInterestingValue - value"),
    ("ev-set", RPC,
     "s->TotalInterestingValue = s->TotalInterestingValue + value;",
     "s->TotalInterestingValue = value;"),
    ("ev-first-only", RPC,
     "            s->TotalInterestingValue = s->TotalInterestingValue + value;",
     "            { s->TotalInterestingValue = s->TotalInterestingValue + value;"
     " break; }"),
    ("ev-skip-first", RPC, "for (s = p32_ptr(rm->ReplaySnapshotList[0]);",
     "for (s = p32_ptr(((ReplaySnapshot *)p32_ptr("
     "rm->ReplaySnapshotList[0]))->pNext);"),
    ("ev-free-list", RPC, [
        ("const void *head = rm->ReplaySnapshotList;",
         "const void *head = rm->FreeReplaySnapshotList;", 1),
        ("p32_ptr(rm->ReplaySnapshotList[0])",
         "p32_ptr(rm->FreeReplaySnapshotList[0])", 1)]),
    ("ev-invalidate-value", RPC, "-99.0f", "-98.0f"),
    # ---- the step: Move
    ("mv-no-catchup", CVC,
     "    car_calculate_new_catchup_multipliers(c);" + NL
     + "    m = c->pCarMover;", "    m = c->pCarMover;"),
    ("mv-catchup-late", CVC, moved(
        "    car_calculate_new_catchup_multipliers(c);",
        "    r = ((CarMoverMoveFn)e->fn)(vt_this(m, e), dt);", True)),
    ("mv-slot-24", CVC, "vt_slot(m->_vtable, CARMOVER_VT_MOVE)",
     "vt_slot(m->_vtable, 24)"),
    ("mv-dt-zero", CVC, "(vt_this(m, e), dt);", "(vt_this(m, e), 0.0f);"),
    ("mv-ret-dt", CVC, "    return r;" + NL + "}", "    return dt;" + NL + "}"),
    ("mv-ret-reset-dt", CVC,
     "        c->ResetMe = 0;" + NL + "        return r;",
     "        c->ResetMe = 0;" + NL + "        return dt;"),
    ("mv-no-update-position", CVC,
     "    car_update_position(c, &c->State.Position);" + NL, ""),
    ("mv-update-geometry", CVC,
     "    car_update_position(c, &c->State.Position);",
     "    car_update_position(c, &c->State.GeometryPosition);"),
    ("mv-no-change-gear", CVC,
     "    car_change_gear(c, c->State.CurrentGear);" + NL, ""),
    ("mv-gear-before-move", CVC, moved(
        "    car_change_gear(c, c->State.CurrentGear);",
        "    car_calculate_new_catchup_multipliers(c);", True)),
    ("mv-reset-ignored", CVC, "    if (c->ResetMe) {",
     "    if (0 && c->ResetMe) {"),
    ("mv-reset-kept", CVC, "        c->ResetMe = 0;" + NL, ""),
    ("mv-reset-falls-through", CVC,
     "        c->ResetMe = 0;" + NL + "        return r;" + NL,
     "        c->ResetMe = 0;" + NL),
    ("mv-reset-speed", CVC, "#define CAR_RESET_ME_SPEED 15.0f",
     "#define CAR_RESET_ME_SPEED 14.0f"),
    ("mv-reset-no-blink", CVC, "CAR_RESET_ME_SPEED, 1,",
     "CAR_RESET_ME_SPEED, 0,"),
    ("mv-reset-backwards", CVC,
     "CAR_RESET_ME_SPEED, 1," + NL + "                                 1.0f);",
     "CAR_RESET_ME_SPEED, 1," + NL + "                                 -1.0f);"),
    ("mv-reset-point-first", CVC, swap(
        "        route = car_get_route(c, 1);",
        "        point = car_get_route_point(c, 1);")),
    ("mv-pen-zero-ok", CVC, " || pen == 0 || ", " || "),
    ("mv-pen-max-ok", CVC, " || pen == 0x7fffffffu)", ")"),
    ("mv-pen-max-off", CVC, "pen == 0x7fffffffu", "pen == 0x7ffffffeu"),
    ("mv-not-blinking-ok", CVC, "    if (!car_is_blinking(c) || pen == 0",
     "    if (pen == 0"),
    ("mv-window-le", CVC,
     "          < (float)(int32_t)(now - (uint32_t)c->BlinkTimer)",
     "          <= (float)(int32_t)(now - (uint32_t)c->BlinkTimer)"),
    ("mv-window-whole", CVC,
     "    if (!(c->BlinkDuration - CAR_BLINK_OVERLAP_TIME",
     "    if (!(c->BlinkDuration"),
    ("mv-window-unsigned", CVC,
     "(float)(int32_t)(now - (uint32_t)c->BlinkTimer)",
     "(float)(now - (uint32_t)c->BlinkTimer)"),
    ("mv-window-ignored", CVC,
     "    if (!(c->BlinkDuration - CAR_BLINK_OVERLAP_TIME",
     "    if (0 && !(c->BlinkDuration - CAR_BLINK_OVERLAP_TIME"),
    ("mv-s-le", CVC, "    if (!(s < CAR_BLINK_OVERLAP_TIME)",
     "    if (!(s <= CAR_BLINK_OVERLAP_TIME)"),
    ("mv-s-no-floor", CVC, " || !(0.0f <= s))", ")"),
    ("mv-s-floor-strict", CVC, "!(0.0f <= s)", "!(0.0f < s)"),
    ("mv-s-unsigned", CVC, "s = (float)(int32_t)(now - pen)",
     "s = (float)(now - pen)"),
    ("mv-s-from-blink", CVC, "s = (float)(int32_t)(now - pen)",
     "s = (float)(int32_t)(now - (uint32_t)c->BlinkTimer)"),
    ("mv-tick", CVC, "#define CAR_MOVE_TICK_SECONDS 0.000250000012f",
     "#define CAR_MOVE_TICK_SECONDS 0.00026f"),
    ("mv-overlap", CVC, "#define CAR_BLINK_OVERLAP_TIME 0.5f",
     "#define CAR_BLINK_OVERLAP_TIME 0.625f"),
    ("mv-stretch-second", CVC, "    timer_set_time(&t, CAR_BLINK_OVERLAP_TIME);",
     "    timer_set_time(&t, 1.0f);"),
    ("mv-stretch-set", CVC,
     "    c->BlinkTimer = (int32_t)((uint32_t)c->BlinkTimer + t.PackedTime);",
     "    c->BlinkTimer = (int32_t)t.PackedTime;"),
    ("mv-stretch-back", CVC, "(uint32_t)c->BlinkTimer + t.PackedTime",
     "(uint32_t)c->BlinkTimer - t.PackedTime"),
    ("mv-stretch-duration", CVC,
     "    c->BlinkTimer = (int32_t)((uint32_t)c->BlinkTimer + t.PackedTime);",
     "    c->BlinkDuration += CAR_BLINK_OVERLAP_TIME;"),
    ("mv-now-late", CVC, "    now = (uint32_t)WorldTimer;",
     "    now = (uint32_t)WorldTimer + 1;"),

    # ---- the step: ChangeGear
    ("cg-no-same-test", CVC,
     "    if (gear == old)" + NL + "        return;" + NL, ""),
    ("cg-neutral-2", CVC, "    if (old == 1) {", "    if (old == 2) {"),
    ("cg-neutral-new", CVC, "    if (old == 1) {", "    if (gear == 1) {"),
    ("cg-no-neutral", CVC, "    if (old == 1) {", "    if (0) {"),
    ("cg-neutral-no-store", CVC,
     "    if (old == 1) {" + NL + "        c->DispGear = gear;" + NL,
     "    if (old == 1) {" + NL),
    ("cg-no-driver-test", CVC, "    if (d == NULL) {", "    if (0) {"),
    ("cg-no-driver-no-store", CVC,
     "    if (d == NULL) {" + NL + "        c->DispGear = gear;" + NL,
     "    if (d == NULL) {" + NL),
    ("cg-end-on-new", CVC,
     "    if (old == 0)" + NL + "        animated_driver_call(gAnimatedDriverEndDrivingBackwardsFn",
     "    if (gear == 0)" + NL + "        animated_driver_call(gAnimatedDriverEndDrivingBackwardsFn"),
    ("cg-end-always", CVC,
     "    if (old == 0)" + NL + "        animated_driver_call(gAnimatedDriverEndDrivingBackwardsFn",
     "        animated_driver_call(gAnimatedDriverEndDrivingBackwardsFn"),
    ("cg-back-on-old", CVC,
     "    if (gear == 0)" + NL + "        animated_driver_call(gAnimatedDriverBeginDrivingBackwardsFn",
     "    if (old == 0)" + NL + "        animated_driver_call(gAnimatedDriverBeginDrivingBackwardsFn"),
    ("cg-back-always", CVC,
     "    if (gear == 0)" + NL + "        animated_driver_call(gAnimatedDriverBeginDrivingBackwardsFn",
     "        animated_driver_call(gAnimatedDriverBeginDrivingBackwardsFn"),
    ("cg-no-begin", CVC,
     "    animated_driver_call(gAnimatedDriverBeginGearChangeFn, c->pAnimatedDriver,"
     + NL + '                         "BeginGearChange");' + NL, ""),
    ("cg-end-back-swap", CVC, [
        ("gAnimatedDriverBeginDrivingBackwardsFn," + NL,
         "gAnimatedDriverEndDrivingBackwardsFn," + NL, 1),
        ("gAnimatedDriverEndDrivingBackwardsFn, d,",
         "gAnimatedDriverBeginDrivingBackwardsFn, d,", 1)]),
    ("cg-no-final-store", CVC,
     "    c->DispGear = gear;" + NL + "}", "}"),
    ("cg-store-old", CVC, "    c->DispGear = gear;" + NL + "}",
     "    c->DispGear = old;" + NL + "}"),

    # ---- the step: the catchup
    ("cu-no-player-test", CVC, "    if (c->pPlayer == NULL || RaceParametersBoost",
     "    if (RaceParametersBoost"),
    ("cu-boost-ignored", CVC, "RaceParametersBoost == 0", "0"),
    ("cu-boost-positive", CVC, "RaceParametersBoost == 0",
     "RaceParametersBoost <= 0"),
    ("cu-players-ignored", CVC, "PlayerNumPlayers != 2", "0"),
    ("cu-players-under", CVC, "PlayerNumPlayers != 2",
     "PlayerNumPlayers < 2"),
    ("cu-other-self", CVC, "race_get_racing_car(pCurrentRace, op->MyCar)",
     "race_get_racing_car(pCurrentRace, c)"),
    ("cu-pick-inverted", CVC, "c->pPlayer->PlayerNumber == 0 ? 1 : 0]",
     "c->pPlayer->PlayerNumber == 0 ? 0 : 1]"),
    ("cu-pick-by-one", CVC, "c->pPlayer->PlayerNumber == 0 ? 1 : 0]",
     "c->pPlayer->PlayerNumber == 1 ? 0 : 1]"),
    ("cu-factored", CVC,
     "    lead = me->CurrentLapNumberExact * len" + NL
     + "           - other->CurrentLapNumberExact * len;",
     "    lead = (me->CurrentLapNumberExact" + NL
     + "            - other->CurrentLapNumberExact) * len;"),
    ("cu-behind", CVC,
     "    lead = me->CurrentLapNumberExact * len" + NL
     + "           - other->CurrentLapNumberExact * len;",
     "    lead = other->CurrentLapNumberExact * len" + NL
     + "           - me->CurrentLapNumberExact * len;"),
    ("cu-laps", CVC,
     "    lead = me->CurrentLapNumberExact * len" + NL
     + "           - other->CurrentLapNumberExact * len;",
     "    lead = me->CurrentLapNumberExact" + NL
     + "           - other->CurrentLapNumberExact;"),
    ("cu-three-knees", CVC, "TwoPlayerCatchup, 4);", "TwoPlayerCatchup, 3);"),
    ("cu-wrong-table", CVC, "TheDifficultyInfo.TwoPlayerCatchup, 4",
     "TheDifficultyInfo.AIDistanceBoostHiSkill, 4"),
    ("cu-into-draft", CVC, "    c->State.BoostFactor = graph_get_value",
     "    c->DraftFactor = graph_get_value"),
    ("rc-car-itself", RCC, "    return c->pRacingCar;",
     "    return (struct RacingCar *)(void *)c;"),

    # ---- the step: UpdatePosition
    ("up-always", CVC, "    if (obj == NULL)" + NL + "        return;" + NL
     + "    if (gEsp", "    if (gEsp"),
    ("up-inverted", CVC, "    if (obj == NULL)" + NL + "        return;" + NL
     + "    if (gEsp", "    if (obj != NULL)" + NL + "        return;" + NL
     + "    if (gEsp"),
    ("up-no-pos", CVC, "    gEspSetObjectPositionFn(obj, pos);",
     "    gEspSetObjectPositionFn(obj, NULL);"),

    # ---- the step: Timer. The difficulty table's loader and unloader
    # are difficulty_check's, on the retail image.
    ("tm-scale", TMC, "seconds * 4000.0f", "seconds * 4096.0f"),
    ("tm-plain-cast", TMC, "(uint32_t)ee_trunc_w(seconds * 4000.0f)",
     "(uint32_t)(seconds * 4000.0f)"),

    # ---- slice nine: carrace.c, and the body's GetDistanceAndSpeed
    ("dcb-speed-kept", CBC, "    *speed = 0.0f;" + NL, ""),
    ("dcb-returns-other", CBC, "    return *speed;", "    return 1.0f;"),
    ("fix-bits-kept", CRR, "    c->BlownTireBits = 0;" + NL, ""),
    ("fix-num-kept", CRR, "    c->NumBlownTires = 0;" + NL
     + "    c->fBlownTireControllerRumbleTimer = 0.0f;",
     "    c->fBlownTireControllerRumbleTimer = 0.0f;"),
    ("fix-timer-kept", CRR,
     "    c->fBlownTireControllerRumbleTimer = 0.0f;" + NL, ""),
    ("fix-any-mode", CRR, "    if (mode != REAL_CONTROL)" + NL
     + "        return;" + NL, ""),
    ("fix-inverted", CRR, "    if (mode != REAL_CONTROL)",
     "    if (mode == REAL_CONTROL)"),
    ("fix-ebrake-on", CRR, "c->pCarDriver, 0);", "c->pCarDriver, 1);"),
    ("blow-num-kept", CRR, "    c->NumBlownTires = 0;" + NL
     + "    c->fBlownTireControllerRumbleTimer = CAR_",
     "    c->fBlownTireControllerRumbleTimer = CAR_"),
    ("blow-timer", CRR, "#define CAR_BLOWN_TIRE_RUMBLE_TIME 7.0f",
     "#define CAR_BLOWN_TIRE_RUMBLE_TIME 6.0f"),
    ("blow-timer-kept", CRR,
     "    c->fBlownTireControllerRumbleTimer = CAR_BLOWN_TIRE_RUMBLE_TIME;"
     + NL, ""),
    ("blow-bits-replaced", CRR,
     "(uint8_t)(c->BlownTireBits | tires);", "(uint8_t)tires;"),
    ("blow-three-wheels", CRR, "for (i = 0; i < 4; i++)",
     "for (i = 0; i < 3; i++)"),
    ("blow-five-wheels", CRR, "for (i = 0; i < 4; i++)",
     "for (i = 0; i < 5; i++)"),
    ("blow-count-new-only", CRR, "        c->NumBlownTires++;" + NL
     + "        if (((tires >> i) & 1) == 0)" + NL + "            continue;"
     + NL, "        if (((tires >> i) & 1) == 0)" + NL
     + "            continue;" + NL + "        c->NumBlownTires++;" + NL),
    ("blow-effect-every-blown", CRR, "        if (((tires >> i) & 1) == 0)"
     + NL + "            continue;" + NL, ""),
    ("blow-bit-order", CRR, "(((int8_t)c->BlownTireBits >> i) & 1)",
     "(((int8_t)c->BlownTireBits >> (3 - i)) & 1)"),
    ("blow-fx", CRR, "CARFX_BLOWN_TIRE, 1.0f,",
     "CARFX_DRIVE_ON_FLAT_TIRE, 1.0f,"),
    ("blow-scale", CRR, "CARFX_BLOWN_TIRE, 1.0f,",
     "CARFX_BLOWN_TIRE, 0.5f,"),
    # The comment above the function spells the same sum; these start at
    # the call's argument, after it.
    ("blow-where-base", CRR, "0x50000 + i * 0x10000, NULL);",
     "0x40000 + i * 0x10000, NULL);"),
    ("blow-where-step", CRR, "0x50000 + i * 0x10000, NULL);",
     "0x50000 + i, NULL);"),
    ("blow-sound-untested", CRR,
     "    if (c->pBaseCarSound != NULL && gBase", "    if (gBase"),
    ("blow-no-sound", CRR,
     "        gBaseCarSoundTriggerTireBlowOutFn(c->pBaseCarSound);" + NL,
     "        ;" + NL),
    ("later-no-beacop", CRR, "RaceParametersBeACop != 0 && ", ""),
    ("later-maxcops-ge", CRR, "RaceParametersMaxCops > 0",
     "RaceParametersMaxCops >= 0"),
    ("later-maxcops-unsigned", CRR, "RaceParametersMaxCops > 0",
     "(uint32_t)RaceParametersMaxCops > 0"),
    ("later-no-type", CRR, NL
     + "        && c->MyDriver->TheDriverType == DRIVER_TYPE_AI_RACER", ""),
    ("later-type", CRR, "== DRIVER_TYPE_AI_RACER", "== DRIVER_TYPE_COP"),
    ("later-pursued-inverted", CRR,
     "        if (gCopManagerIsBeingPursuedFn(pCopManager, c))",
     "        if (!gCopManagerIsBeingPursuedFn(pCopManager, c))"),
    ("later-pursued-ignored", CRR,
     "        if (gCopManagerIsBeingPursuedFn(pCopManager, c))" + NL
     + "            return;" + NL,
     "        (void)gCopManagerIsBeingPursuedFn(pCopManager, c);" + NL),
    ("later-no-manager", CRR, "gCopManagerIsBeingPursuedFn(pCopManager, c)",
     "gCopManagerIsBeingPursuedFn(NULL, c)"),
    ("later-resetme-2", CRR, "    c->ResetMe = 1;", "    c->ResetMe = 2;"),
    ("line-ai-only", CRR, "mode != AI_CONTROL && mode != TRAFFIC_CONTROL",
     "mode != AI_CONTROL"),
    ("line-traffic-only", CRR,
     "mode != AI_CONTROL && mode != TRAFFIC_CONTROL",
     "mode != TRAFFIC_CONTROL"),
    ("line-cop-too", CRR, "mode != AI_CONTROL && mode != TRAFFIC_CONTROL",
     "mode != AI_CONTROL && mode != TRAFFIC_CONTROL"
     + " && mode != COP_CONTROL"),
    ("line-other-one", CRR, "        return 0.0f;", "        return 1.0f;"),
    ("line-driver", CRR,
     "gAICarControllerGetCurrentDrivingLineSpeedFn(c->pCarController);",
     "gAICarControllerGetCurrentDrivingLineSpeedFn("
     "(CarController *)(void *)c->pCarDriver);"),
    ("dme-mode", CRR, "    car_set_movement_mode(c, DELIVERY_MOVEMENT);",
     "    car_set_movement_mode(c, COP_MOVEMENT);"),
    ("dme-no-mode", CRR,
     "    car_set_movement_mode(c, DELIVERY_MOVEMENT);" + NL, ""),
    ("dme-mover-before", CRR,
     "    car_set_movement_mode(c, DELIVERY_MOVEMENT);" + NL,
     "    CarMover *m0 = c->pCarMover;" + NL
     + "    car_set_movement_mode(c, DELIVERY_MOVEMENT);" + NL
     + "    c->pCarMover = m0;" + NL),
    ("dme-speed-time", CRR, "pos, angle, speed, time);",
     "pos, angle, time, speed);"),
    ("dme-angle-0", CRR, "pos, angle, speed, time);",
     "pos, 0, speed, time);"),
    ("dme-pos-null", CRR, "(c->pCarMover, pos, angle,",
     "(c->pCarMover, NULL, angle,"),
    # ---- slice eleven: FinishMovement
    # -- the accelerations, the odometer
    ("fm-dt-le", CFM, "    if (0.0f < dt) {", "    if (0.0f <= dt) {"),
    ("fm-dt-nonzero", CFM, "    if (0.0f < dt) {", "    if (dt != 0.0f) {"),
    ("fm-plain-div", CFM, "float inv = ee_div(1.0f, dt);",
     "float inv = 1.0f / dt;"),
    ("fm-acc-times-dt", CFM,
     "st->Acceleration.x = (st->Velocity.x - c->vOldVel.x) * inv;",
     "st->Acceleration.x = (st->Velocity.x - c->vOldVel.x) * dt;"),
    ("fm-acc-z-old-y", CFM, "(st->Velocity.z - c->vOldVel.z) * inv;",
     "(st->Velocity.z - c->vOldVel.y) * inv;"),
    ("fm-acc-no-pad", CFM, "        st->Acceleration.pad = (st->Velocity.pad"
     " - c->vOldVel.pad) * inv;" + NL, ""),
    ("fm-ang-from-vel", CFM, "(st->AngularVelocity.x - c->vOldAngVel.x)",
     "(st->Velocity.x - c->vOldAngVel.x)"),
    ("fm-ang-old-vel", CFM, "(st->AngularVelocity.y - c->vOldAngVel.y)",
     "(st->AngularVelocity.y - c->vOldVel.y)"),
    ("fm-ang-no-pad", CFM, "        st->AngularAcceleration.pad =" + NL
     + "            (st->AngularVelocity.pad - c->vOldAngVel.pad) * inv;"
     + NL, ""),
    ("fm-odo-zero-le", CFM, "if (!(speed < 0.0f) && !(1000.0f < speed))",
     "if (!(speed <= 0.0f) && !(1000.0f < speed))"),
    ("fm-odo-1000-le", CFM, "if (!(speed < 0.0f) && !(1000.0f < speed))",
     "if (!(speed < 0.0f) && !(1000.0f <= speed))"),
    ("fm-odo-nan-skipped", CFM,
     "if (!(speed < 0.0f) && !(1000.0f < speed))",
     "if (0.0f <= speed && speed <= 1000.0f)"),
    ("fm-odo-no-dt", CFM, "st->Odometer = st->Odometer + speed * dt;",
     "st->Odometer = st->Odometer + speed;"),
    ("fm-odo-forward-speed", CFM, "    speed = st->VelocityMagnitude;" + NL
     + "    if (!(speed < 0.0f)", "    speed = st->ForwardSpeed;" + NL
     + "    if (!(speed < 0.0f)"),
    # -- the track, the topology, the lights
    ("fm-no-update-position", CFM, "    trackpath_coord_update_position(tpc, "
     "(const bVector2 *)&st->Position);" + NL, ""),
    ("fm-topo-phase", CFM, "if (((WorldLoopCounter + 7) & 31) == 0",
     "if (((WorldLoopCounter + 6) & 31) == 0"),
    ("fm-topo-mask-15", CFM, "if (((WorldLoopCounter + 7) & 31) == 0",
     "if (((WorldLoopCounter + 7) & 15) == 0"),
    ("fm-topo-any-mode", CFM, "if (((WorldLoopCounter + 7) & 31) == 0 "
     "&& c->TheMovementMode != 0", "if (((WorldLoopCounter + 7) & 31) == 0"),
    ("fm-topo-one-probe", CFM, "        if (!topology_has_topology("
     "&c->TheTopologyCoordinate, &q))", "        if (q.x == q.x)"),
    ("fm-topo-probe-y", CFM, "        q.x = st->Position.x + 1.0f;" + NL
     + "        q.y = st->Position.y;", "        q.x = st->Position.x;" + NL
     + "        q.y = st->Position.y + 1.0f;"),
    ("fm-topo-reset-2", CFM, "&q))" + NL + "            c->ResetMe = 1;",
     "&q))" + NL + "            c->ResetMe = 2;"),
    ("fm-lost-le", CFM, "    if (CAR_LOST_DISTANCE < track_offset(tpc)) {",
     "    if (CAR_LOST_DISTANCE <= track_offset(tpc)) {"),
    ("fm-lost-no-boring", CFM, "        if (!BoringAIForCameraTuningOn)" + NL
     + "            c->ResetMe = 1;", "        c->ResetMe = 1;"),
    ("fm-research-le", CFM, "} else if (CAR_RESEARCH_DISTANCE < track_offset",
     "} else if (CAR_RESEARCH_DISTANCE <= track_offset"),
    ("fm-research-no-else", CFM, "    } else if (CAR_RESEARCH_DISTANCE",
     "    }" + NL + "    if (CAR_RESEARCH_DISTANCE"),
    ("fm-research-unsigned", CFM, "&& WorldLoopCounter % 60 == 0",
     "&& (uint32_t)WorldLoopCounter % 60 == 0"),
    ("fm-research-any-mode", CFM, "&& WorldLoopCounter % 60 == 0 && "
     "c->TheMovementMode != 0) {", "&& WorldLoopCounter % 60 == 0) {"),
    ("fm-research-keeps-point", CFM,
     "        trackpath_coord_reset_position(tpc,",
     "        trackpath_coord_update_position(tpc,"),
    ("fm-offset-squared", CFM, "    return sqrtf(dx * dx + dy * dy);",
     "    return dx * dx + dy * dy;"),
    ("fm-no-lights", CFM, "    car_update_headlights_and_horn(c);" + NL, ""),
    # -- the player: the zone, the phase, CarInAir
    ("fm-clear-jump-cam-only", CFM,
     "        || p->nZoneCurrent == PLAYER_ZONE_AFTER_JUMP) {",
     "        || p->nZoneCurrent == PLAYER_ZONE_JUMP_CAM) {"),
    ("fm-clear-no-wheel", CFM, "        if (wheels > 0)" + NL
     + "            clear_zone(p, 1);", "        if (wheels >= 0)" + NL
     + "            clear_zone(p, 1);"),
    ("fm-clear-silent", CFM, "            clear_zone(p, 1);",
     "            clear_zone(p, 0);"),
    ("fm-player-phase", CFM, "if (((WorldLoopCounter + 3) & 7) != 0)",
     "if (((WorldLoopCounter + 4) & 7) != 0)"),
    ("fm-player-mask-3", CFM, "if (((WorldLoopCounter + 3) & 7) != 0)",
     "if (((WorldLoopCounter + 3) & 3) != 0)"),
    ("fm-air-40-le", CFM, "    if (40.0f < speed && wheels < 4",
     "    if (40.0f <= speed && wheels < 4"),
    ("fm-air-four-wheels", CFM, "    if (40.0f < speed && wheels < 4",
     "    if (40.0f < speed && wheels <= 4"),
    ("fm-air-yaw-le", CFM,
     "fabsf(carstate_get_yaw(st)) < CAR_AIR_STRAIGHT_YAW)",
     "fabsf(carstate_get_yaw(st)) <= CAR_AIR_STRAIGHT_YAW)"),
    ("fm-air-signed-yaw", CFM,
     "fabsf(carstate_get_yaw(st)) < CAR_AIR_STRAIGHT_YAW)",
     "carstate_get_yaw(st) < CAR_AIR_STRAIGHT_YAW)"),
    ("fm-air-value", CFM, 'interesting(2.0f, "CarInAir");',
     'interesting(1.0f, "CarInAir");'),
    ("fm-air-name", CFM, 'interesting(2.0f, "CarInAir");',
     'interesting(2.0f, "CarSlidingSideways");'),
    # -- the jump cam
    ("fm-jc-ignores-disable", CFM,
     "    if (!g_DisableAutoReplay && zone != PLAYER_ZONE_JUMP_CAM",
     "    if (zone != PLAYER_ZONE_JUMP_CAM"),
    ("fm-jc-from-after-zone", CFM,
     "        && zone != PLAYER_ZONE_AFTER_JUMP && wheels == 0",
     "        && wheels == 0"),
    ("fm-jc-wheels-le", CFM, "&& wheels == 0" + NL, "&& wheels <= 0" + NL),
    ("fm-jc-wrong-way", CFM,
     "        && c->pPlayer->bWrongWay == 0 && 30.0f < speed) {",
     "        && 30.0f < speed) {"),
    ("fm-jc-30-le", CFM, "bWrongWay == 0 && 30.0f < speed) {",
     "bWrongWay == 0 && 30.0f <= speed) {"),
    ("fm-jc-t-from-2", CFM, "        float t = 3.0f, h;",
     "        float t = 2.0f, h;"),
    ("fm-jc-tick", CFM, "        now = (float)WorldTimer * CAR_FINISH_TICK;",
     "        now = (float)WorldTimer * 0.001f;"),
    ("fm-jc-short-le", CFM, "        if (t < CAR_SHORT_JUMP)",
     "        if (t <= CAR_SHORT_JUMP)"),
    ("fm-jc-short-3", CFM, "c->AirTimeSwitch = now + 5.0f;",
     "c->AirTimeSwitch = now + 3.0f;"),
    ("fm-jc-whole-jump", CFM, "c->AirTimeSwitch = t * 0.5f + now;",
     "c->AirTimeSwitch = t + now;"),
    ("fm-jc-h-le", CFM, "        if (1.5f < h && 0.5f < t",
     "        if (1.5f <= h && 0.5f < t"),
    ("fm-jc-t-le", CFM, "        if (1.5f < h && 0.5f < t",
     "        if (1.5f < h && 0.5f <= t"),
    ("fm-jc-always-available", CFM,
     "&& 0.5f < t && is_jump_cam_available(p)", "&& 0.5f < t"),
    ("fm-jc-forced", CFM, "request_zone(p, PLAYER_ZONE_JUMP_CAM, 0, 1, 1))",
     "request_zone(p, PLAYER_ZONE_JUMP_CAM, 1, 1, 1))"),
    ("fm-jc-clean-up-on-yes", CFM,
     "            && !request_zone(p, PLAYER_ZONE_JUMP_CAM",
     "            && request_zone(p, PLAYER_ZONE_JUMP_CAM"),
    ("fm-jc-zone-not-reread", CFM, "            clean_up_jump_cam(p);" + NL
     + "        zone = p->nZoneCurrent;" + NL,
     "            clean_up_jump_cam(p);" + NL),
    # -- in the jump cam's zone
    ("fm-eye-not-falling", CFM, "        if (st->Velocity.z < 0.0f && ",
     "        if (st->Velocity.z <= 0.0f && "),
    ("fm-eye-le", CFM, "p->EyeVerts[2].z < st->Position.z)",
     "p->EyeVerts[2].z <= st->Position.z)"),
    ("fm-eye-any-height", CFM, "        if (st->Velocity.z < 0.0f && "
     "p->EyeVerts[2].z < st->Position.z)",
     "        if (st->Velocity.z < 0.0f)"),
    ("fm-eye-wrong-vert", CFM, "            p->EyeVerts[2].z = st->Position.z;",
     "            p->EyeVerts[1].z = st->Position.z;"),
    ("fm-switch-le", CFM, "        if (c->AirTimeSwitch < (float)WorldTimer",
     "        if (c->AirTimeSwitch <= (float)WorldTimer"),
    ("fm-switch-sound", CFM, "            clear_zone(p, 0);",
     "            clear_zone(p, 1);"),
    ("fm-switch-no-clear", CFM, "            clear_zone(p, 0);" + NL, ""),
    ("fm-switch-args", CFM,
     "request_zone(p, PLAYER_ZONE_AFTER_JUMP, 0, 0, 1);",
     "request_zone(p, PLAYER_ZONE_AFTER_JUMP, 0, 1, 1);"),
    # -- CloseCars
    ("fm-close-40-le", CFM, "    if (40.0f < speed) {" + NL
     + "        World *w", "    if (40.0f <= speed) {" + NL
     + "        World *w"),
    ("fm-close-dist-le", CFM, "dz * dz) < 40.0f)", "dz * dz) <= 40.0f)"),
    ("fm-close-flat", CFM, "sqrtf((dx * dx + dy * dy) + dz * dz)",
     "sqrtf(dx * dx + dy * dy)"),
    ("fm-close-skip-first", CFM,
     "        for (i = 0; i < w->CopCarPos - w->AICarPos; i++) {",
     "        for (i = 1; i < w->CopCarPos - w->AICarPos; i++) {"),
    ("fm-close-with-cop", CFM, "i < w->CopCarPos - w->AICarPos; i++) {",
     "i <= w->CopCarPos - w->AICarPos; i++) {"),
    ("fm-close-from-zero", CFM, "w->CarTable[w->AICarPos + i];",
     "w->CarTable[i];"),
    ("fm-close-whole", CFM, 'interesting((float)n * 0.5f, "CloseCars");',
     'interesting((float)n, "CloseCars");'),
    # -- sliding, the collision, the replay
    ("fm-slide-30-le", CFM, "    if (30.0f < speed) {" + NL
     + "        Collision *col;", "    if (30.0f <= speed) {" + NL
     + "        Collision *col;"),
    ("fm-slide-le", CFM, "if (CAR_SLIDING_YAW < fabsf(carstate_get_yaw(st)))",
     "if (CAR_SLIDING_YAW <= fabsf(carstate_get_yaw(st)))"),
    ("fm-slide-signed", CFM,
     "if (CAR_SLIDING_YAW < fabsf(carstate_get_yaw(st)))",
     "if (CAR_SLIDING_YAW < carstate_get_yaw(st))"),
    ("fm-slide-value", CFM, 'interesting(1.0f, "CarSlidingSideways");',
     'interesting(2.0f, "CarSlidingSideways");'),
    ("fm-col-second", CFM, "&c->pDynamicCollisionBody->Dynamic.Body, 0);",
     "&c->pDynamicCollisionBody->Dynamic.Body, 1);"),
    ("fm-col-any-player", CFM,
     "if (col != NULL && collision_is_player_involved(col)",
     "if (col != NULL"),
    ("fm-col-half-le", CFM, "* CAR_FINISH_TICK < 0.5f) {",
     "* CAR_FINISH_TICK <= 0.5f) {"),
    ("fm-col-unsigned", CFM, "&& (float)(int32_t)((uint32_t)WorldTimer",
     "&& (float)((uint32_t)WorldTimer"),
    ("fm-col-cars-40-le", CFM,
     "collision_is_two_car_collision(col) && 40.0f < speed",
     "collision_is_two_car_collision(col) && 40.0f <= speed"),
    ("fm-col-cars-value", CFM, 'interesting(3.0f, "CarCollision");',
     'interesting(5.0f, "CarCollision");'),
    ("fm-col-no-colliding-cars", CFM,
     "                collision_get_colliding_cars(col, &a, &b);",
     "                (void)a; (void)b;"),
    ("fm-col-smoke-no-else", CFM,
     "            } else if (collision_is_smokeable_involved(col)",
     "            }" + NL + "            if (collision_is_smokeable_involved(col)"),
    ("fm-col-smoke-no-speed", CFM,
     "collision_is_smokeable_involved(col)" + NL
     + "                       && 30.0f < speed) {",
     "collision_is_smokeable_involved(col)) {"),
    ("fm-col-smoke-value", CFM, 'interesting(5.0f, "SmokeableCollision");',
     'interesting(3.0f, "SmokeableCollision");'),
    ("fm-col-smoke-is-cars", CFM,
     "} else if (collision_is_smokeable_involved(col)",
     "} else if (collision_is_two_car_collision(col)"),
    ("fm-replay-untested", CFM, "    if (pReplayManager != NULL)" + NL
     + "        ReplayManager_RegisterInterestingEvent",
     "    ReplayManager_RegisterInterestingEvent"),
]

EQUIVALENT = {
    # -- the step --------------------------------------------------------
    "mv-s-unsigned":
        "A penetration stamped after WorldTimer is a negative signed "
        "difference, which fails 0 <= s. Read unsigned it is at least "
        "2^31 ticks, over half a million seconds, which fails s < 0.5 "
        "instead. Either way the blink is left alone, and for a "
        "difference under 2^31 the two reads are the same number.",
    "tm-plain-cast":
        "Move's only call is Timer::SetTime(0.5): 2000.0, which a cast "
        "and cvt.w.s truncate alike. They part only past 2^31 ticks.",
    # -- the resets ----------------------------------------------------
    "rc-steer-kept":
        "ResetCore's SteeringAngle = 0 follows ResetCar, whose own wheel "
        "setup has already zeroed it, and the one call between them -- "
        "the track path's UpdatePosition -- writes only the coordinate. "
        "The store puts back the zero that is there.",
    "rc-matrix-valid-kept":
        "ResetCar ends by clearing MatrixValid. The only thing that sets "
        "it is GetTransformMatrix, and nothing ResetCore runs before its "
        "own clear -- UpdatePosition, ClearInterestBBox, PutFlatOnTrack "
        "and the elevation it asks for, bNormalize -- asks for the "
        "transform, so the flag is still 0 when ResetCore clears it.",
    "rc-no-wheel-matrices":
        "CalculateWheelMatrices reads WheelAngle, SteeringAngle, "
        "WheelSuspensionHeight and the type's wheel positions, and "
        "nothing else. ResetCar zeroes the first three and builds the "
        "matrices from them; between that and ResetCore's call only "
        "Angle, Position, ForwardSpeed, the body matrix, Velocity and "
        "the wheels' angular velocities change. The second build writes "
        "the same bytes over the first.",
    # -- FinishMovement ---------------------------------------------------
    "fm-air-yaw-le":
        "GetYaw is 0 below a ForwardSpeed of 5, and otherwise a BAM "
        "difference, one of 65536, times BAM_TO_RAD and folded past pi. "
        "No difference gives exactly 3.14/32 (0.098125f) either way "
        "round: the nearest are 1023 and 1024, and 64512 and 64513. The "
        "< and <= only part on that value.",
    "fm-slide-le":
        "As fm-air-yaw-le: no BAM difference gives exactly 3.14/8 "
        "(0.3925f); the nearest are 4093 and 4094, and 61442 and 61443.",
    "fm-air-name":
        "RegisterInterestingEvent ignores the description: it adds the "
        "value to every snapshot named INSTANT_REPLAY while capturing, "
        "and the name is read nowhere else.",
    "fm-col-no-colliding-cars":
        "The image asks for the colliding cars and swaps the two when the "
        "second is the player's own, then reads neither. GetCollidingCars "
        "only reads the witness, so dropping the call leaves nothing to "
        "see.",
    "fm-col-smoke-no-else":
        "The first branch is taken only when both of the witness's bodies "
        "are CAR_COLLISION_BODY, and then neither is smokeable, so the "
        "smokeable test after it, run unconditionally, still fails.",
    "fm-col-smoke-no-speed":
        "The collision is only looked at inside `30 < speed`, and speed "
        "is a local that nothing in between changes, so the second test "
        "always passes. The image makes it anyway (the listing's third "
        "left-out thing).",
}


def mutate_pass(only=None):
    cti = cti_record()
    base = model(cti)
    caught = 0
    survived = []
    missing = []
    equivalent = []
    todo = [m for m in MUTATIONS if only is None or m[0] in only]
    if only is not None:
        unknown = sorted(set(only) - {m[0] for m in MUTATIONS})
        if unknown:
            sys.exit("no such mutation: " + " ".join(unknown))

    with tempfile.TemporaryDirectory() as tmp:
        exe = build_harness(tmp, cti)
        out = Path(tmp) / "base.txt"
        run_harness(exe, out)
        if diff(base, out.read_text().splitlines(), quiet=True):
            print("base already differs -- fix that before mutating")
            return 1

    for m in todo:
        name, rel = m[0], m[1]
        edits = m[2] if len(m) == 3 else [(m[2], m[3], 1)]
        path = ROOT / rel
        text = path.read_text(encoding="utf-8", newline="")
        crlf = "\r\n" in text
        new = text
        ok = True
        for before, after, count in edits:
            probe = before.replace(NL, "\r\n") if crlf else before
            repl = after.replace(NL, "\r\n") if crlf else after
            if new.count(probe) < count:
                ok = False
                break
            new = new.replace(probe, repl, count)
        if not ok:
            missing.append(name)
            print("  %-44s PATTERN NOT FOUND" % name)
            continue
        try:
            hostbuild.write_source(path, new)
            with tempfile.TemporaryDirectory() as tmp:
                try:
                    exe = build_harness(tmp, cti)
                except SystemExit:
                    print("  %-44s did not compile (caught)" % name)
                    caught += 1
                    continue
                out = Path(tmp) / "m.txt"
                if run_harness(exe, out) != 0:
                    print("  %-44s crashed the harness (caught)" % name)
                    caught += 1
                    continue
                n = diff(base, out.read_text().splitlines(), quiet=True)
                if n:
                    print("  %-44s caught, %d lines" % (name, n))
                    caught += 1
                elif name in EQUIVALENT:
                    print("  %-44s survived, equivalent by construction" % name)
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

    real = [m for m in todo if m[0] not in missing]
    holes = [s for s in survived if s not in EQUIVALENT]
    # An entry whose mutant was caught is a wrong reason, not a spare one.
    # --only leaves the others unrun, so only the ones that ran are judged.
    ran = {m[0] for m in todo}
    stale = [n for n in EQUIVALENT
             if n not in equivalent and n not in missing
             and (n in ran or only is None)]
    if missing:
        print("%d PATTERN NOT FOUND -- the tally above is over %d of %d"
              % (len(missing), len(real), len(todo)))
    print("%d mutations, %d caught, %d equivalent, %d unexplained"
          % (len(real), caught, len(equivalent), len(holes)))
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

    probs = layout_problems()
    for p in probs:
        print("layout: " + p)
    if probs:
        sys.exit(1)

    if args.mutate:
        sys.exit(mutate_pass(args.only.split(",") if args.only else None))

    cti = cti_record()
    lines = model(cti)
    with tempfile.TemporaryDirectory() as tmp:
        exe = build_harness(tmp, cti)
        out = Path(tmp) / "harness.txt"
        run_harness(exe, out)
        harness = out.read_text().splitlines()

    if args.dump:
        d = Path(args.dump)
        d.parent.mkdir(parents=True, exist_ok=True)
        d.with_suffix(".model").write_text(NL.join(lines) + NL)
        d.with_suffix(".harness").write_text(NL.join(harness) + NL)

    n = diff(lines, harness)
    print("%d transitions, %d resets, %d lines, %d masked, %d differ"
          % (len(MOVE_WALK) + len(CTRL_WALK) - 2,
             len(RESETS) + len(ROUTE_RESETS), len(harness),
             sum(1 for x in lines if x.endswith(" *")), n))
    sys.exit(1 if n else 0)


if __name__ == "__main__":
    main()
