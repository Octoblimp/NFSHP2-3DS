#!/usr/bin/env python3
"""Cross-check 3DS Files/source/realdriver.c -- RealDriver, the human's
driver -- against the image itself, run in mipsemu.

The model is the image: every RealDriver method but DoSnapshot runs as
shipped, and so do everything it calls that the port has too -- the seven
Tables and their constructor, Table::GetValue and InverseLookup,
CarState::GetYaw and bATan, Car::GetRoute and GetRoutePoint, CarDriver's
constructor and destructor, the DriveTarget they reach, and the vtable
dispatch for the three calls RealDriver makes through its own table. The
harness runs the same op script on the port and prints the same lines.

**The stand-ins.** The pad layer's five calls (AddJoyHandler,
RemoveJoyHandler, IsJoystickPluggedIn, IsJoystickTypeWheel and
DoesJoystickHaveStiffThrottle) are joystick_check's to verify; here each is
stubbed by symbol in the model and defined in the harness, logs what it was
handed, and answers what the script says. The same goes for the fourteen
seams, which are other tasks' classes: the replay's event log, the render's
radial blur, the route editor, Player, tCopManager, Car::ResetToRoutePoint
and BaseCarSound.

**The seam mask.** The image calls a seam unconditionally; the port skips
one that is NULL, and a NULL query answers "not allowed" or a forward-facing
1.0. So the script carries a mask. A set bit installs the seam in the harness
and lets the model's stub log; a clear bit leaves the harness's pointer NULL
and makes the model's stub silent, answering what the port's NULL case
assumes. Every mask the script uses therefore checks both the call and the
port's NULL handling against the image.

**Unset fields are poison in the model.** The Car, CarTypeInfo and Player
the model hands the image are filled with 0x55 before the script sets the
fields RealDriver is meant to read, image offset by image offset; the
harness's are zeroed and set by name. A field the image reads that the port
does not (or the other way about) then shows as a difference rather than
agreeing on zero.

**Labels, not pointers.** Every pointer printed is a name: the car, the
player, the cop manager, the replay manager, the sound, the route and point,
the two drivers, the position and velocity vectors, the target.

Scenarios: the tunables and tables as built, and the vtable slot by slot;
GetValue and InverseLookup over every table; the constructor over two fills;
the small methods; the handlers' registration; every pedal handler over its
own events and others, then a fuzz; the gearbox in every mode; the reset,
the horn and the nitro over their guards; DoThrottleBrakeReverse and DoBrake
over a grid; DoSteering over random states and held-stick sequences; Drive
over random states and nitro transitions; every vtable slot through the
table; a fuzz of everything interleaved; and the destructor.

    python tools/realdriver_check.py
    python tools/realdriver_check.py --mutate
    python tools/realdriver_check.py --dump out/realdriver
"""
import argparse
import os
import random
import struct
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

HARNESS = "tools/src/realdriver_test.c"
RDC = "3DS Files/source/realdriver.c"
RDH = "3DS Files/source/realdriver.h"
TBC = "3DS Files/source/table.c"
SOURCES = [HARNESS, RDC, TBC,
           "3DS Files/source/cardriver.c",
           "3DS Files/source/drivetarget.c",
           "3DS Files/source/car.c",
           "3DS Files/source/carstate.c",
           "3DS Files/source/trackroute.c",
           "3DS Files/source/trackpath.c",
           "3DS Files/source/quickspline.c",
           "3DS Files/source/bchunk.c",
           "3DS Files/source/world.c",
           "3DS Files/source/graph.c",
           "3DS Files/source/race.c",
           "3DS Files/source/copmanager.c",
           "3DS Files/source/replay.c",
           "3DS Files/source/bmem.c",
           "3DS Files/source/vtable.c",
           "3DS Files/source/emath.c",
           "3DS Files/source/bmatrix.c",
           "3DS Files/source/bvector.c",
           "3DS Files/source/bmath.c",
           "3DS Files/source/bmathtab.c"]

HARNESS_TIMEOUT = 300

# ================================================================ the image

GP = 0x00328bf0

# The fixed objects, above the emulator's heap and below its stack.
DRV = [0x01E00000, 0x01E00400]      # two RealDrivers, 640 bytes each
CAR = 0x01E01000                    # Car, 0x1000 reserved
CTI = 0x01E02000                    # CarTypeInfo
PLAYER = 0x01E03000
CTRL = 0x01E03100                   # a CarController: vptr at 8
CTRL_VT = 0x01E03200                # its table
TGT = 0x01E03400                    # a DriveTarget, 528 bytes
COP = 0x01E04000                    # labels only, never read
RM = 0x01E04100
SND = 0x01E04200
ROUTE = 0x01E04300
POINT = 0x01E04400
FAKE_FN = 0x01E20000                # the controller's two getters

STATE = CAR + 64
POS = STATE + 32
VEL = STATE + 48
FILL = 0x55
DRV_SIZE = 640
TGT_SIZE = 528

VT_RD = 0x00292A70
VT_CD = 0x002924A8
CTRL_GET_ROUTE = 48
CTRL_GET_POINT = 56

# The .sdata tunables, by name or, for the two the symbol table lost, by
# address; the order is the transcript's.
GLOBS = [
    ("WorldTimer", "WorldTimer"),
    ("WorldTimeElapsed", "WorldTimeElapsed"),
    ("WorldLoopCounter", "WorldLoopCounter"),
    ("RaceParametersBeACop", 0x00312790),
    ("RollingResetSpeed", "RollingResetSpeed"),
    ("PowerSlideYawCoef", "PowerSlideYawCoef"),
    ("SteeringSpeed", 0x003231D8),
    ("SteeringReturnFactor", 0x003231DC),
    ("CounterSteerFadeStart", "CounterSteerFadeStart"),
    ("CounterSteerFadeEnd", "CounterSteerFadeEnd"),
    ("MaxSpeedForReverse", "MaxSpeedForReverse"),
    ("MinSpeedForThrottle", "MinSpeedForThrottle"),
    ("MinSpeedForThrottleWhenReversing", "MinSpeedForThrottleWhenReversing"),
    ("BrakingSpeed", "BrakingSpeed"),
    ("UnBrakingSpeed", "UnBrakingSpeed"),
    ("NitrousActiveTime", "NitrousActiveTime"),
    ("NitrousRechargeTime", "NitrousRechargeTime"),
]
G = {name: i for i, (name, _) in enumerate(GLOBS)}
# The first four are the world's, set by the script before anything reads
# them; the rest are RealDriver's and Car's, printed as built.
STATIC_GLOBS = [n for n, _ in GLOBS][4:]

TABLES = ["SteeringWheelRangeTable", "SteeringRangeTable",
          "SteeringSpeedTable", "SteeringCurveTable", "SteeringInputTable",
          "YawCoeffTable", "BrakingCurve"]

# The fields the script sets, at their image addresses. Width 2 and 1 are
# the int16 DriverNumber and uint16 Angle, and the int8 CopLights.
CARF = [
    ("DriverNumber", CAR + 10, 2),
    ("TheMovementMode", CAR + 36, 4),
    ("Position.x", POS, 4), ("Position.y", POS + 4, 4),
    ("Position.z", POS + 8, 4),
    ("Velocity.x", VEL, 4), ("Velocity.y", VEL + 4, 4),
    ("Velocity.z", VEL + 8, 4),
    ("BodyMatrix.v0.x", STATE + 80, 4), ("BodyMatrix.v0.y", STATE + 84, 4),
    ("Angle", STATE + 868, 2),
    ("ForwardSpeed", STATE + 892, 4),
    ("VelocityMagnitude", STATE + 896, 4),
    ("CurrentGear", STATE + 900, 4),
    ("Throttle", STATE + 904, 4),
    ("PathDirection.x", CAR + 1840 + 24, 4),
    ("PathDirection.y", CAR + 1840 + 28, 4),
    ("CopLights", CAR + 1880, 1),
    ("TheSirenMode", CAR + 1924, 4),
    ("CarClass", CTI + 236, 4),
    ("NumGears", CTI + 624 + 24, 4),
    ("Control.Steering", CTI + 768, 4),
    ("UsageType", CTI + 1336, 4),
    ("PlayerNumber", PLAYER + 16, 4),
]
C = {name: i for i, (name, _, _) in enumerate(CARF)}

# RealDriver's fields the script may set directly, at image offsets.
DRVF = [
    ("Steering", 528, 2), ("DesiredGear", 544, 4), ("SportGear", 548, 4),
    ("Port", 564, 4), ("HandlersAdded", 568, 4), ("StartLineState", 572, 4),
    ("StopRightNow", 576, 4), ("ForcedEBrakeStop", 580, 4),
    ("bPowerSlide", 584, 4), ("ManualTransmission", 588, 4),
    ("SteeringInput", 596, 4), ("ThrottleInput", 604, 4),
    ("BrakeInput", 612, 4), ("EBrakeInput", 628, 4),
    ("LastNitroRequest", 632, 4), ("Reversing", 636, 4),
    ("JoySteeringDigital", 592, 1), ("JoySteeringAnalog", 593, 1),
    ("JoyThrottleDigital", 600, 1), ("JoyThrottleAnalog", 601, 1),
    ("JoyThrottleAnalogAlternate", 602, 1), ("JoyBrakeDigital", 608, 1),
    ("JoyBrakeAnalog", 609, 1), ("JoyBrakeAnalogAlternate", 610, 1),
    ("JoyReverseDigital", 616, 1), ("JoyReverseAnalog", 617, 1),
    ("JoyEBrakeDigital", 624, 1), ("JoyEBrakeAnalog", 625, 1),
    ("NitroFlag", 552, 4), ("Throttle", 532, 4), ("Brake", 536, 4),
    ("EBrake", 540, 4), ("_vtable", 556, 4),
]
D = {name: i for i, (name, _, _) in enumerate(DRVF)}

# ---- the ops -----------------------------------------------------------------

(OP_TAG, OP_FILL, OP_INIT, OP_DUMP, OP_CARF, OP_DRVF, OP_GLOB, OP_PTR,
 OP_ANSWER, OP_MASK, OP_CALL, OP_HANDLER, OP_VT, OP_TABLE, OP_INV,
 OP_STATIC, OP_TARGET) = range(17)

(F_DESTROY, F_DRIVE, F_ADD, F_REMOVE, F_DISABLE_SL, F_ENABLE_SL, F_SET_MANUAL,
 F_SET_LOW_GEAR, F_FORCE_EBRAKE, F_RESET_JOY, F_DO_STEERING, F_DTBR,
 F_DO_BRAKE, F_NITRO_WAS, F_NITRO_ACTIVE, F_NITRO_AVAIL, F_START_HONK,
 F_STOP_HONK, F_GET_PORT, F_GET_DRIVER_NUMBER, F_SET_DESIRED_SPEED,
 F_SET_PREDICTED_TARGET, F_SET_STOP, F_SET_PORT, F_GET_CAR) = range(25)

FN_SYM = {
    F_DESTROY: "_$_10RealDriver",
    F_DRIVE: "Drive__10RealDriverf",
    F_ADD: "AddJoyHandlers__10RealDriver",
    F_REMOVE: "RemoveJoyHandlers__10RealDriver",
    F_DISABLE_SL: "DisableStartLineState__10RealDriver",
    F_ENABLE_SL: "EnableStartLineState__10RealDriver",
    F_SET_MANUAL: "SetManualTransmission__10RealDriveri",
    F_SET_LOW_GEAR: "SetLowGear__10RealDriver",
    F_FORCE_EBRAKE: "ForceEBrakeStop__10RealDriveri",
    F_RESET_JOY: "ResetJoyValues__10RealDriver",
    F_DO_STEERING: "DoSteering__10RealDriverf12JoystickPort",
    F_DTBR: "DoThrottleBrakeReverse__10RealDriverf",
    F_DO_BRAKE: "DoBrake__10RealDriverf",
    F_NITRO_WAS: "NitroWasActive__10RealDriver",
    F_NITRO_ACTIVE: "NitroActive__10RealDriver",
    F_NITRO_AVAIL: "NitroAvailable__10RealDriver",
    F_START_HONK: "StartHonkHorn__10RealDriver",
    F_STOP_HONK: "StopHonkHorn__10RealDriver",
    F_GET_PORT: "GetPort__10RealDriver",
    F_GET_DRIVER_NUMBER: "GetDriverNumber__10RealDriver",
    F_SET_DESIRED_SPEED: "SetDesiredSpeed__10RealDriverffb",
    F_SET_PREDICTED_TARGET: "SetPredictedTarget__10RealDriverP11DriveTarget",
    F_SET_STOP: "SetStopRightNow__10RealDriveri",
    F_SET_PORT: "SetJoystickPort__10RealDriver12JoystickPort",
    F_GET_CAR: "GetCar__10RealDriver",
}

HANDLERS = ["Steer", "Throttle", "Reverse", "Brake", "EBrake", "ShiftUp",
            "ShiftDown", "ResetCar", "HonkHorn", "NitroBoost"]
H = {n: i for i, n in enumerate(HANDLERS)}
HSUFFIX = "__10RealDriver12JoystickPort8JoyEventUcPv"
HNAME = ["steer", "throttle", "reverse", "brake", "ebrake", "shiftup",
         "shiftdown", "reset", "honk", "nitro"]

EV = dict(STEER=110, STEER_ANALOG=111, THROTTLE=112, THROTTLE_ANALOG=113,
          THROTTLE_ANALOG_ALTERNATE=114, BRAKE=115, BRAKE_ANALOG=116,
          BRAKE_ANALOG_ALTERNATE=117, REVERSE=118, REVERSE_ANALOG=119,
          EBRAKE=120, EBRAKE_ANALOG=121, SHIFTUP=122, SHIFTDOWN=123,
          RESET_CAR=124, HONK_HORN=125, NITRO_BOOST=126)

# Pointers the script can clear: the car's player and sound, and the two
# managers.
P_PLAYER, P_COP, P_SOUND, P_REPLAY = range(4)
# Answers the stand-ins give.
A_PLUGGED, A_WHEEL, A_STIFF, A_ALLOWED, A_DIRECTION = range(5)

# The seams, in mask order, and each one's symbol in the image.
SEAMS = [
    ("route-point", "MaybeAddTrackRoutePoint__FPC8bVector2PC8bVector3fii"),
    ("cancel-tuning", "CancelTuningDrivingLines__Fv"),
    ("blur-on", "RadialBlurOn__Fi"),
    ("blur-off", "RadialBlurOff__Fi"),
    ("blur-alpha", "RadialBlurAlpha__Fiff"),
    ("replay-event", "RegisterInterestingEvent__13ReplayManagerfPCc"),
    ("reroute", "RerouteJoyEvent__6Player12JoystickPort8JoyEventUc"),
    ("allowed-reset", "IsAllowedToReset__6Player"),
    ("selected-reset", "PlayerSelectedReset__6Player"),
    ("reset-direction", "GetResetDirection__11tCopManager"),
    ("siren-toggle", "BeACopToggleSirenAndLights__11tCopManager"),
    ("reset-to-point",
     "ResetToRoutePoint__3CarP10TrackRouteP15TrackRoutePointfbf"),
    ("honk-start", "StartHonkHorn__12BaseCarSound"),
    ("honk-stop", "StopHonkHorn__12BaseCarSound"),
]
S = {n: i for i, (n, _) in enumerate(SEAMS)}
ALL_SEAMS = (1 << len(SEAMS)) - 1

# The port's function for each image symbol a table slot holds.
FNMAP = {
    "_$_10RealDriver": "realdriver_destroy",
    "Drive__10RealDriverf": "realdriver_drive",
    # DoSnapshot waits on ReplaySnapshot; the port's slot is NULL.
    "DoSnapshot__10RealDriverP14ReplaySnapshot": "null",
    "AddJoyHandlers__10RealDriver": "realdriver_add_joy_handlers",
    "RemoveJoyHandlers__10RealDriver": "realdriver_remove_joy_handlers",
    "SetLowGear__10RealDriver": "realdriver_set_low_gear",
    "SetDesiredSpeed__10RealDriverffb": "realdriver_set_desired_speed",
    "SetTarget__9CarDriverP11DriveTarget": "cardriver_set_target",
    "SetSteerToPoint__9CarDriverP8bVector2": "cardriver_set_steer_to_point",
    "GetDriverNumber__10RealDriver": "realdriver_get_driver_number",
    "StartHonkHorn__10RealDriver": "realdriver_start_honk_horn",
    "StopHonkHorn__10RealDriver": "realdriver_stop_honk_horn",
    "IsHonking__9CarDriver": "cardriver_is_honking",
    "MaxSpeedToTarget__9CarDriverP11DriveTarget":
        "cardriver_max_speed_to_target",
    "ZeroSteeringMemory__9CarDriver": "cardriver_zero_steering_memory",
    "ClearSteeringMemory__9CarDriver": "cardriver_clear_steering_memory",
    "GetDesiredSpeed__9CarDriver": "cardriver_get_desired_speed",
    "GetDesiredTimeToSpeed__9CarDriver":
        "cardriver_get_desired_time_to_speed",
    "SetPhysicsMode__9CarDriveri": "cardriver_set_physics_mode",
    "GetSteerToPoint__9CarDriver": "cardriver_get_steer_to_point",
}

# Every slot the script calls through the table, and how. 24 is DoSnapshot.
VT_SLOTS = [8, 16, 32, 40, 48, 56, 64, 72, 80, 88, 96, 104, 112, 120, 128,
            136, 144, 152, 160]


ARGS = {OP_TAG: 1, OP_FILL: 2, OP_INIT: 1, OP_DUMP: 1, OP_CARF: 2,
        OP_DRVF: 3, OP_GLOB: 2, OP_PTR: 2, OP_ANSWER: 2, OP_MASK: 1,
        OP_CALL: 5, OP_HANDLER: 5, OP_VT: 5, OP_TABLE: 2, OP_INV: 2,
        OP_STATIC: 0, OP_TARGET: 1}


def fb(x):
    """A Python float's single-precision bits."""
    return struct.unpack("<I", struct.pack("<f", x))[0]


def bf(b):
    return struct.unpack("<f", struct.pack("<I", b & M32))[0]


def fnv(data):
    h = 0x811C9DC5
    for b in data:
        h = ((h ^ b) * 0x01000193) & M32
    return h


def target_bytes(seed):
    return bytes((seed + 13 * i + (i >> 5)) & 0xFF for i in range(TGT_SIZE))


class Script(object):
    def __init__(self):
        self.ops = []
        self.tags = []

    def op(self, code, *args):
        assert len(args) == ARGS[code], (code, args)
        self.ops.append((code,) + tuple(int(a) for a in args))

    def tag(self, s):
        self.tags.append(s)
        self.op(OP_TAG, len(self.tags) - 1)

    def encode(self):
        out = [len(self.tags)]
        for s in self.tags:
            b = s.encode("latin-1")
            out.append(len(b))
            out.extend(b)
        flat = []
        for o in self.ops:
            flat.extend(o)
        out.append(len(flat))
        out.extend(flat)
        return struct.pack("<%di" % len(out), *[s32(v & M32) for v in out])

    # ---- sugar -----------------------------------------------------------

    def carf(self, name, v):
        n, _, w = CARF[C[name]]
        self.op(OP_CARF, C[name], fb(v) if isinstance(v, float) else v)

    def drvf(self, slot, name, v):
        self.op(OP_DRVF, slot, D[name], fb(v) if isinstance(v, float) else v)

    def glob(self, name, v):
        self.op(OP_GLOB, G[name], fb(v) if isinstance(v, float) else v)

    def call(self, fn, slot=0, a=0, b=0, c=0, dump=True):
        self.op(OP_CALL, fn, slot,
                *[fb(x) if isinstance(x, float) else x for x in (a, b, c)])
        if dump:
            self.op(OP_DUMP, slot)

    def handler(self, h, ev, value, slot=0, port=0, dump=True):
        self.op(OP_HANDLER, slot, H[h] if isinstance(h, str) else h, port, ev,
                value & 0xFF)
        if dump:
            self.op(OP_DUMP, slot)

    def vt(self, slot, vslot, a=0, f1=0.0, f2=0.0, dump=True):
        self.op(OP_VT, slot, vslot, a, fb(f1), fb(f2))
        if dump:
            self.op(OP_DUMP, slot)


# ================================================================ the script

PEDAL_VALUES = [0, 1, 2, 3, 63, 64, 65, 66, 127, 128, 129, 191, 192, 237, 238,
                239, 240, 253, 254, 255]


def rfloat(rnd, lo, hi, specials=()):
    if specials and rnd.random() < 0.25:
        return float(rnd.choice(specials))
    return rnd.uniform(lo, hi)


def setup(sc):
    """Every field the script sets, to a sane car at rest."""
    for name, v in [("DriverNumber", 3), ("TheMovementMode", 0),
                    ("Position.x", 10.5), ("Position.y", -20.25),
                    ("Position.z", 3.75), ("Velocity.x", 0.0),
                    ("Velocity.y", 0.0), ("Velocity.z", 0.0),
                    ("BodyMatrix.v0.x", 1.0), ("BodyMatrix.v0.y", 0.0),
                    ("Angle", 0), ("ForwardSpeed", 0.0),
                    ("VelocityMagnitude", 0.0), ("CurrentGear", 1),
                    ("Throttle", 0.0), ("PathDirection.x", 1.0),
                    ("PathDirection.y", 0.0), ("CopLights", 0),
                    ("TheSirenMode", 0), ("CarClass", 2), ("NumGears", 5),
                    ("Control.Steering", 1.0), ("UsageType", 0),
                    ("PlayerNumber", 1)]:
        sc.carf(name, v)
    sc.glob("WorldTimer", 100000)
    sc.glob("WorldTimeElapsed", 1.0 / 60.0)
    sc.glob("WorldLoopCounter", 100000)
    sc.glob("RaceParametersBeACop", 0)
    for p in (P_PLAYER, P_COP, P_SOUND, P_REPLAY):
        sc.op(OP_PTR, p, 1)
    sc.op(OP_ANSWER, A_PLUGGED, 1)
    sc.op(OP_ANSWER, A_WHEEL, 0)
    sc.op(OP_ANSWER, A_STIFF, 0)
    sc.op(OP_ANSWER, A_ALLOWED, 1)
    sc.op(OP_ANSWER, A_DIRECTION, fb(-1.0))
    sc.op(OP_MASK, ALL_SEAMS)


def fresh(sc, slot=0, fill=0xA5):
    sc.op(OP_FILL, slot, fill)
    sc.op(OP_INIT, slot)


def scenario_tables(sc, rnd):
    sc.tag("tables")
    ranges = [(0, 160), (0, 160), (0, 160), (0, 1), (0, 256), (0, 1), (0, 1)]
    values = [
        [45, 15, 11, 9, 8, 7, 6],
        [45, 13, 8, 5.5, 4.2, 3.6, 3.1, 2.9],
        [1, 0.92, 0.78, 0.64, 0.54, 0.48, 0.42, 0.38, 0.34],
        [0, 0.1, 0.24, 0.53, 0.79, 1],
        [1, 0.4, 0.2, 0.1, 0, -0.1, -0.2, -0.4, -1],
        [0.8, 0.9, 0.92, 0.95, 1],
        [0, 0.2, 0.4, 0.6, 0.8, 1],
    ]
    special = [0.0, -0.0, 1e-30, -1e-30, 1e30, -1e30, float("inf"),
               float("-inf")]
    for t, (lo, hi) in enumerate(ranges):
        xs = [lo + (hi - lo) * k / 64.0 for k in range(-8, 73)]
        xs += special + [rnd.uniform(lo - 1, hi + 1) for _ in range(40)]
        for x in xs:
            sc.op(OP_TABLE, t, fb(x))
        vs = []
        for v in values[t]:
            vs += [v, v + 1e-6, v - 1e-6, v + 2e-6, v - 2e-6, v + 5e-7,
                   v - 5e-7]
        lo_v, hi_v = min(values[t]), max(values[t])
        span = hi_v - lo_v
        vs += [lo_v + span * k / 50.0 for k in range(-5, 56)]
        vs += special + [rnd.uniform(lo_v - 1, hi_v + 1) for _ in range(40)]
        for v in vs:
            sc.op(OP_INV, t, fb(v))
        # Just above and below each entry by one ulp.
        for v in values[t]:
            b = fb(v)
            for d in (-2, -1, 1, 2):
                sc.op(OP_INV, t, (b + d) & M32)


def scenario_ctor(sc):
    sc.tag("ctor")
    fresh(sc, 0, 0xA5)
    sc.op(OP_DUMP, 0)
    fresh(sc, 1, 0x5A)
    sc.op(OP_DUMP, 1)
    # A second construction over a live driver changes nothing it has not
    # already set.
    sc.drvf(0, "SportGear", 7)
    sc.drvf(0, "bPowerSlide", 1)
    sc.op(OP_INIT, 0)
    sc.op(OP_DUMP, 0)


def scenario_small(sc):
    sc.tag("small")
    fresh(sc)
    sc.carf("CurrentGear", 4)
    for m in (-1, 0, 1, 2, 3, 7, 1, 0):
        sc.drvf(0, "DesiredGear", 9)
        sc.call(F_SET_MANUAL, 0, m)
        sc.call(F_SET_LOW_GEAR)
        sc.call(F_DISABLE_SL)
        sc.call(F_ENABLE_SL)
    for on in (0, 1, 5, -1):
        sc.call(F_FORCE_EBRAKE, 0, on)
        sc.call(F_SET_STOP, 0, on)
    for p in (0, 1, -1, 7):
        sc.call(F_SET_PORT, 0, p)
        sc.call(F_GET_PORT)
    for n in (3, -1, 32767, -32768, 0, 12):
        sc.carf("DriverNumber", n & 0xFFFF)
        sc.call(F_GET_DRIVER_NUMBER)
    sc.call(F_GET_CAR)
    sc.call(F_SET_DESIRED_SPEED, 0, 12.5, -3.0, 1)
    for seed in (0, 77, 200):
        sc.op(OP_TARGET, seed)
        sc.call(F_SET_PREDICTED_TARGET)
    # Every joy value scribbled, then reset.
    for i, (name, _, w) in enumerate(DRVF):
        if name.startswith("Joy"):
            sc.drvf(0, name, 200 + i)
        elif name.endswith("Input"):
            sc.drvf(0, name, 0.75 + i)
    sc.op(OP_DUMP, 0)
    sc.call(F_RESET_JOY)


def scenario_registration(sc):
    sc.tag("registration")
    fresh(sc)
    for port in (0, 1, -1):
        sc.call(F_SET_PORT, 0, port)
        sc.call(F_ADD)
        sc.call(F_ADD)
        sc.call(F_REMOVE)
        sc.call(F_REMOVE)
    # The horn is let go on removal: through the table, with and without
    # the sound, the seam, and on a cop.
    sc.call(F_SET_PORT, 0, 0)
    for usage, snd, mask in ((0, 1, ALL_SEAMS), (1, 1, ALL_SEAMS),
                             (0, 0, ALL_SEAMS), (0, 1, 0),
                             (2, 1, 1 << S["honk-stop"])):
        sc.carf("UsageType", usage)
        sc.op(OP_PTR, P_SOUND, snd)
        sc.op(OP_MASK, mask)
        sc.call(F_ADD, dump=False)
        sc.call(F_REMOVE)
    sc.carf("UsageType", 0)
    sc.op(OP_PTR, P_SOUND, 1)
    sc.op(OP_MASK, ALL_SEAMS)
    # HandlersAdded as a word: any nonzero is added.
    for v in (2, -1, 0x100):
        sc.drvf(0, "HandlersAdded", v)
        sc.call(F_ADD)
        sc.call(F_REMOVE)


def scenario_pedals(sc, rnd):
    sc.tag("pedals")
    fresh(sc)
    own = {
        "Steer": [110, 111],
        "Throttle": [112, 113, 114],
        "Reverse": [118, 119],
        "Brake": [115, 116, 117],
        "EBrake": [120, 121],
    }
    for h, evs in own.items():
        stiffs = (0, 1) if h in ("Throttle", "Reverse") else (0,)
        for stiff in stiffs:
            sc.op(OP_ANSWER, A_STIFF, stiff)
            for ev in evs + [109, 127, 0]:
                for v in PEDAL_VALUES:
                    sc.handler(h, ev, v)
            sc.call(F_RESET_JOY, dump=False)
    sc.op(OP_ANSWER, A_STIFF, 0)

    sc.tag("pedals: fuzz")
    for port in (0, 1):
        sc.call(F_SET_PORT, 0, port, dump=False)
        for _ in range(1500):
            h = rnd.choice(["Steer", "Throttle", "Reverse", "Brake",
                            "EBrake"])
            if rnd.random() < 0.1:
                ev = rnd.choice([0, 109, 127, 200, rnd.randrange(110, 127)])
            else:
                ev = rnd.choice(own[h])
            if rnd.random() < 0.5:
                v = rnd.choice(PEDAL_VALUES)
            else:
                v = rnd.randrange(256)
            if rnd.random() < 0.1:
                sc.op(OP_ANSWER, A_STIFF, rnd.randrange(2))
            sc.handler(h, ev, v, port=rnd.choice((0, 1, -1)))
    sc.op(OP_ANSWER, A_STIFF, 0)


def scenario_gearbox(sc):
    sc.tag("gearbox")
    fresh(sc)
    sc.carf("CurrentGear", 3)
    for mt in (0, 1, 2, 3):
        for dg in (-2, -1, 0, 1, 2, 5, 6, 7):
            for mm in (0, 4, 3):
                for h in ("ShiftUp", "ShiftDown"):
                    for v in (0, 1, 255):
                        players = (1, 0) if mt in (0, 3) else (1,)
                        for pl in players:
                            sc.op(OP_PTR, P_PLAYER, pl)
                            sc.carf("TheMovementMode", mm)
                            sc.drvf(0, "ManualTransmission", mt)
                            sc.drvf(0, "DesiredGear", dg)
                            sc.drvf(0, "SportGear", 4)
                            sc.handler(h, EV[h.upper()], v, port=1)
    sc.op(OP_PTR, P_PLAYER, 1)
    sc.carf("TheMovementMode", 0)
    # The manual box's top gear follows NumGears.
    sc.drvf(0, "ManualTransmission", 1)
    for ng in (3, 4, 6):
        sc.carf("NumGears", ng)
        for dg in range(-1, ng + 4):
            sc.drvf(0, "DesiredGear", dg)
            sc.handler("ShiftUp", 122, 1)
    sc.carf("NumGears", 5)
    # The sport shift from a gear it has not taken yet, and from its own.
    sc.drvf(0, "ManualTransmission", 2)
    for cg in (-1, 0, 1, 4, 7):
        sc.carf("CurrentGear", cg)
        sc.drvf(0, "DesiredGear", -1)
        sc.handler("ShiftUp", 122, 1)
        sc.handler("ShiftUp", 122, 1)
        sc.handler("ShiftDown", 123, 1)
    # An automatic box without the seam.
    sc.drvf(0, "ManualTransmission", 0)
    sc.op(OP_MASK, ALL_SEAMS & ~(1 << S["reroute"]))
    sc.handler("ShiftUp", 122, 1)
    sc.handler("ShiftDown", 123, 1)
    sc.op(OP_MASK, ALL_SEAMS)


def scenario_reset(sc, rnd):
    sc.tag("reset")
    fresh(sc)
    sc.call(F_DISABLE_SL)
    # The guards, one at a time.
    sc.drvf(0, "StartLineState", 1)
    sc.handler("ResetCar", 124, 1)
    sc.drvf(0, "StartLineState", 0)
    sc.handler("ResetCar", 124, 0)
    sc.op(OP_PTR, P_PLAYER, 0)
    sc.handler("ResetCar", 124, 1)
    sc.op(OP_PTR, P_PLAYER, 1)
    sc.op(OP_ANSWER, A_ALLOWED, 0)
    sc.handler("ResetCar", 124, 1)
    sc.op(OP_ANSWER, A_ALLOWED, 1)
    sc.handler("ResetCar", 124, 1)
    sc.handler("ResetCar", 124, 255)

    sc.tag("reset: speeds")
    speeds = [-5.0, -0.0, 0.0, 3.0, 14.9, 15.0, 15.1, 40.0, 1e-30]
    frames = [(1.0, 0.0, 1.0, 0.0), (0.6, 0.8, 0.8, 0.6),
              (1.0, 0.0, -1.0, 0.0), (0.0, 1.0, 1.0, 0.0),
              (-0.0, 0.0, 1.0, 0.0), (0.6, -0.8, 0.6, 0.8),
              (0.8, 0.6, 0.8, 0.6), (-0.6, -0.8, -0.6, -0.8)]
    for fs in speeds:
        for bx, by, px, py in frames:
            sc.carf("ForwardSpeed", fs)
            sc.carf("BodyMatrix.v0.x", bx)
            sc.carf("BodyMatrix.v0.y", by)
            sc.carf("PathDirection.x", px)
            sc.carf("PathDirection.y", py)
            sc.handler("ResetCar", 124, 1)
    sc.glob("RollingResetSpeed", 7.5)
    for fs in (5.0, 7.5, 9.0):
        sc.carf("ForwardSpeed", fs)
        sc.handler("ResetCar", 124, 1)
    # A tie at the cap, where only the sign of a zero tells `min.s` from
    # a `<=`: -0.0 kept against a +0.0 cap, and the other way about.
    sc.carf("BodyMatrix.v0.x", 1.0)
    sc.carf("BodyMatrix.v0.y", 0.0)
    sc.carf("PathDirection.x", 1.0)
    sc.carf("PathDirection.y", 0.0)
    for rrs in (0.0, -0.0):
        sc.glob("RollingResetSpeed", rrs)
        for fs in (0.0, -0.0, 3.0):
            sc.carf("ForwardSpeed", fs)
            sc.handler("ResetCar", 124, 1)
    sc.glob("RollingResetSpeed", 15.0)

    sc.tag("reset: cops")
    for usage in (0, 1, 2):
        for cop in (1, 0):
            for direction in (-1.0, 0.5):
                sc.carf("UsageType", usage)
                sc.op(OP_PTR, P_COP, cop)
                sc.op(OP_ANSWER, A_DIRECTION, fb(direction))
                sc.handler("ResetCar", 124, 1)
    sc.carf("UsageType", 0)
    sc.op(OP_PTR, P_COP, 1)

    sc.tag("reset: masks")
    for bits in range(16):
        m = ALL_SEAMS
        for k, name in enumerate(("allowed-reset", "reset-direction",
                                  "reset-to-point", "selected-reset")):
            if bits & (1 << k):
                m &= ~(1 << S[name])
        m &= ~((bits >> 3 & 1) << S["blur-off"])
        sc.op(OP_MASK, m)
        sc.carf("UsageType", 1)
        sc.handler("ResetCar", 124, 1)
    sc.op(OP_MASK, ALL_SEAMS)
    sc.carf("UsageType", 0)

    sc.tag("reset: fuzz")
    for _ in range(400):
        sc.carf("ForwardSpeed", rfloat(rnd, -20, 60, speeds))
        a = rnd.uniform(-3.2, 3.2)
        b = rnd.uniform(-3.2, 3.2)
        import math
        sc.carf("BodyMatrix.v0.x", math.cos(a))
        sc.carf("BodyMatrix.v0.y", math.sin(a))
        sc.carf("PathDirection.x", math.cos(b))
        sc.carf("PathDirection.y", math.sin(b))
        sc.carf("UsageType", rnd.choice((0, 1)))
        sc.handler("ResetCar", 124, 1, port=rnd.choice((0, 1)))


def scenario_horn(sc):
    sc.tag("horn")
    fresh(sc)
    for usage in (0, 1, 2):
        for beacop in (0, 1):
            for cl in (0, 1, -1, 5, -128):
                for snd in (1, 0):
                    for mask in (ALL_SEAMS, 0,
                                 ALL_SEAMS & ~(1 << S["siren-toggle"])):
                        for v in (1, 0):
                            sc.carf("UsageType", usage)
                            sc.glob("RaceParametersBeACop", beacop)
                            sc.carf("CopLights", cl & 0xFF)
                            sc.carf("TheSirenMode", 3)
                            sc.op(OP_PTR, P_SOUND, snd)
                            sc.op(OP_MASK, mask)
                            sc.handler("HonkHorn", 125, v)
    sc.op(OP_MASK, ALL_SEAMS)
    sc.op(OP_PTR, P_SOUND, 1)
    sc.glob("RaceParametersBeACop", 0)
    for usage in (0, 1, 2):
        sc.carf("UsageType", usage)
        sc.call(F_START_HONK)
        sc.call(F_STOP_HONK)
    sc.carf("UsageType", 0)
    # The cop manager's pointer is passed as it is, NULL or not.
    sc.carf("UsageType", 1)
    sc.glob("RaceParametersBeACop", 1)
    sc.op(OP_PTR, P_COP, 0)
    sc.handler("HonkHorn", 125, 1)
    sc.op(OP_PTR, P_COP, 1)
    sc.glob("RaceParametersBeACop", 0)
    sc.carf("UsageType", 0)


def scenario_nitro(sc):
    sc.tag("nitro")
    fresh(sc)
    w = 100000
    sc.glob("WorldTimer", w)
    lnrs = [0, 0x7FFFFFFF, w, w - 1, w - 15999, w - 16000, w - 16001,
            w - 16066, w - 16067, w + 1, w + 100, w - 266, w - 267, 1,
            -1, 0x7FFFFFFE, -0x80000000]
    for usage in (0, 1):
        for beacop in (0, 1):
            for v in (0, 1):
                for lnr in lnrs:
                    sc.carf("UsageType", usage)
                    sc.glob("RaceParametersBeACop", beacop)
                    sc.drvf(0, "LastNitroRequest", lnr)
                    sc.drvf(0, "NitroFlag", 0)
                    sc.handler("NitroBoost", 126, v)

    sc.tag("nitro: queries")
    elapsed = [1.0 / 60.0, 0.0, 0.25, 4.0, 5.0, -0.5]
    for el in elapsed:
        sc.glob("WorldTimeElapsed", el)
        for lnr in lnrs:
            sc.drvf(0, "LastNitroRequest", lnr)
            for fn in (F_NITRO_WAS, F_NITRO_ACTIVE, F_NITRO_AVAIL):
                sc.call(fn, dump=False)
    sc.glob("WorldTimeElapsed", 1.0 / 60.0)
    # The wrap: a request just before the timer turns over.
    sc.glob("WorldTimer", -0x7FFFFFF0)
    for lnr in (0x7FFFFFF0, 0x7FFFFF00, -0x7FFFFFF8, 0x7FFFC180):
        sc.drvf(0, "LastNitroRequest", lnr)
        for fn in (F_NITRO_WAS, F_NITRO_ACTIVE, F_NITRO_AVAIL):
            sc.call(fn, dump=False)
    sc.glob("WorldTimer", w)
    # The two times, moved.
    for nat, nrt in ((2.0, 0.0), (4.0, 3.0), (0.0, 0.0), (4.0, -1.0)):
        sc.glob("NitrousActiveTime", nat)
        sc.glob("NitrousRechargeTime", nrt)
        for lnr in (w - 8000, w - 16000, w - 28000, w - 28001, w - 4,
                    w + 4):
            sc.drvf(0, "LastNitroRequest", lnr)
            for fn in (F_NITRO_WAS, F_NITRO_ACTIVE, F_NITRO_AVAIL):
                sc.call(fn, dump=False)
            sc.carf("UsageType", 1)
            sc.glob("RaceParametersBeACop", 1)
            sc.handler("NitroBoost", 126, 1)
    sc.glob("NitrousActiveTime", 4.0)
    sc.glob("NitrousRechargeTime", 0.0)
    # The tick's scale. At 4 s a threshold falls between the same two
    # ticks for any scale within a part in 16000, so it is pinned where it
    # does not: a 1000 s nitro, and a frame time that lands between two
    # ticks' ages.
    sc.glob("NitrousActiveTime", 1000.0)
    for lnr in (w - 3999900, w - 3999999, w - 4000000, w - 3999800):
        sc.drvf(0, "LastNitroRequest", lnr)
        for fn in (F_NITRO_WAS, F_NITRO_ACTIVE, F_NITRO_AVAIL):
            sc.call(fn, dump=False)
    sc.glob("NitrousActiveTime", 4.0)
    for el in (3.9998, 3.99985, 3.99970):
        sc.glob("WorldTimeElapsed", el)
        for lnr in (w - 15999, w - 15998):
            sc.drvf(0, "LastNitroRequest", lnr)
            sc.call(F_NITRO_WAS, dump=False)
    sc.glob("WorldTimeElapsed", 1.0 / 60.0)
    sc.carf("UsageType", 0)
    sc.glob("RaceParametersBeACop", 0)


def scenario_dtbr(sc, rnd):
    sc.tag("throttle, brake, reverse")
    fresh(sc)
    sc.call(F_DISABLE_SL)
    inputs = [0.0, 0.1, 0.2, 0.5, 0.6, 0.6000001, 0.7, 1.0, 0.45, 0.25]
    speeds = [-40.0, -30.0, -30.000002, -29.999998, -2.0000002, -2.0,
              -1.9999998, 0.0, -0.0, 0.5, 0.50000006, 0.49999997, 10.0]
    vms = [10.0, 10.000001, 50.0, 0.0]
    for _ in range(3000):
        sc.drvf(0, "ForcedEBrakeStop", rnd.choice((0, 0, 0, 1)))
        sc.drvf(0, "EBrakeInput", rnd.choice(inputs))
        sc.drvf(0, "ThrottleInput", rnd.choice(inputs))
        sc.drvf(0, "BrakeInput", rnd.choice(inputs))
        sc.drvf(0, "Reversing", rnd.choice((0, 1, 2)))
        sc.drvf(0, "DesiredGear", rnd.choice((0, -1, 3, -2)))
        sc.drvf(0, "ManualTransmission", rnd.choice((0, 1)))
        sc.carf("ForwardSpeed", rnd.choice(speeds))
        sc.carf("VelocityMagnitude", rnd.choice(vms))
        sc.glob("WorldLoopCounter", rnd.choice((7, 15, 8, 100000, -1, 1023,
                                                0x7FFFFFFF)))
        if rnd.random() < 0.1:
            sc.op(OP_MASK, rnd.choice((0, ALL_SEAMS)))
        if rnd.random() < 0.05:
            sc.op(OP_PTR, P_REPLAY, rnd.randrange(2))
        sc.call(F_DTBR, 0, rnd.choice((1.0 / 60.0, 0.0, 1.0)))
    sc.op(OP_MASK, ALL_SEAMS)
    sc.op(OP_PTR, P_REPLAY, 1)

    sc.tag("throttle, brake, reverse: tunables")
    for name, v in (("MaxSpeedForReverse", 3.0), ("MinSpeedForThrottle", -5.0),
                    ("MinSpeedForThrottleWhenReversing", -0.5),
                    ("BrakingSpeed", 0.1), ("UnBrakingSpeed", 1.0)):
        sc.glob(name, v)
        for _ in range(60):
            sc.drvf(0, "ThrottleInput", rnd.choice(inputs))
            sc.drvf(0, "BrakeInput", rnd.choice(inputs))
            sc.drvf(0, "Reversing", rnd.choice((0, 1)))
            sc.carf("ForwardSpeed", rnd.uniform(-35, 5))
            sc.call(F_DTBR, 0, 1.0 / 60.0)
    for name, v in (("MaxSpeedForReverse", 0.5), ("MinSpeedForThrottle", -30.0),
                    ("MinSpeedForThrottleWhenReversing", -2.0),
                    ("BrakingSpeed", 0.6), ("UnBrakingSpeed", 6.0)):
        sc.glob(name, v)

    sc.tag("brake")
    for _ in range(400):
        sc.drvf(0, "EBrakeInput", rnd.choice(inputs))
        sc.drvf(0, "BrakeInput", rnd.choice(inputs))
        sc.carf("VelocityMagnitude", rnd.choice(vms))
        sc.glob("WorldLoopCounter", rnd.choice((7, 15, 8, 100000, -1)))
        sc.call(F_DO_BRAKE, 0, 1.0 / 60.0)
    sc.glob("WorldLoopCounter", 100000)


def random_motion(sc, rnd):
    """A random heading, velocity and forward speed."""
    import math
    spd = rnd.choice((0.0, rnd.uniform(0, 5), rnd.uniform(0, 70),
                      rnd.uniform(12, 16), 13.410818, 13.410817))
    head = rnd.uniform(-math.pi, math.pi)
    sc.carf("Velocity.x", spd * math.cos(head))
    sc.carf("Velocity.y", spd * math.sin(head))
    sc.carf("Velocity.z", rnd.choice((0.0, rnd.uniform(-2, 2))))
    sc.carf("Angle", rnd.randrange(65536))
    sc.carf("ForwardSpeed", rnd.choice((spd, -spd, rnd.uniform(-10, 170),
                                        4.9999, 5.0, 160.0, 200.0)))


def scenario_steering(sc, rnd):
    sc.tag("steering")
    fresh(sc)
    inputs = [0.0, -0.0, 1.0, -1.0, 0.5, -0.5, 0.0078125, -0.984375]
    for _ in range(4000):
        random_motion(sc, rnd)
        sc.drvf(0, "Steering", rnd.choice((0, 0x8000, 0xFFFF, 1,
                                           rnd.randrange(65536),
                                           rnd.randrange(1200),
                                           65536 - rnd.randrange(1200))))
        sc.drvf(0, "SteeringInput", rfloat(rnd, -1, 1, inputs))
        sc.drvf(0, "bPowerSlide", rnd.choice((0, 1)))
        sc.carf("Control.Steering", rnd.choice((1.0, 0.5, 2.25, 1.3, 0.8)))
        sc.op(OP_ANSWER, A_WHEEL, rnd.choice((0, 0, 1)))
        sc.call(F_DO_STEERING, 0, rnd.choice((1.0 / 60.0, 1.0 / 30.0, 0.0,
                                              0.1, 1.0, 0.004)),
                rnd.choice((0, 1, -1)))
    sc.op(OP_ANSWER, A_WHEEL, 0)

    sc.tag("steering: held")
    for _ in range(30):
        random_motion(sc, rnd)
        sc.drvf(0, "Steering", 0)
        sc.drvf(0, "bPowerSlide", 0)
        wheel = rnd.choice((0, 1))
        sc.op(OP_ANSWER, A_WHEEL, wheel)
        target = rfloat(rnd, -1, 1, inputs)
        for k in range(40):
            if k == 20:
                target = rfloat(rnd, -1, 1, inputs)
            sc.drvf(0, "SteeringInput", target)
            sc.call(F_DO_STEERING, 0, 1.0 / 60.0, 0)
    sc.op(OP_ANSWER, A_WHEEL, 0)

    sc.tag("steering: tunables")
    for name, v in (("SteeringSpeed", 4.0), ("SteeringReturnFactor", 5.0),
                    ("CounterSteerFadeStart", 2.0),
                    ("CounterSteerFadeEnd", 1.0), ("PowerSlideYawCoef", 0.5)):
        sc.glob(name, v)
        for _ in range(80):
            random_motion(sc, rnd)
            sc.drvf(0, "Steering", rnd.randrange(65536))
            sc.drvf(0, "SteeringInput", rfloat(rnd, -1, 1, inputs))
            sc.drvf(0, "bPowerSlide", rnd.choice((0, 1)))
            sc.call(F_DO_STEERING, 0, 1.0 / 60.0, 0)
    for name, v in (("SteeringSpeed", 9.0), ("SteeringReturnFactor", 2.0),
                    ("CounterSteerFadeStart", 13.410818),
                    ("CounterSteerFadeEnd", 17.88109)):
        sc.glob(name, v)
    sc.carf("Control.Steering", 1.0)


def scenario_drive(sc, rnd):
    sc.tag("drive")
    fresh(sc)
    sc.call(F_SET_PORT, 0, 0, dump=False)
    sc.call(F_ADD, dump=False)
    for _ in range(1500):
        random_motion(sc, rnd)
        sc.op(OP_ANSWER, A_PLUGGED, rnd.choice((1, 1, 1, 0)))
        sc.drvf(0, "StopRightNow", rnd.choice((0, 0, 1)))
        sc.drvf(0, "StartLineState", rnd.choice((0, 0, 1)))
        sc.drvf(0, "ThrottleInput", rnd.choice((0.0, 0.5, 1.0)))
        sc.drvf(0, "BrakeInput", rnd.choice((0.0, 0.3, 1.0)))
        sc.drvf(0, "SteeringInput", rfloat(rnd, -1, 1, (0.0, 1.0, -1.0)))
        sc.drvf(0, "LastNitroRequest",
                rnd.choice((0, 100000, 100000 - 16000, 100000 - 15990,
                            100000 - 16070, 100000 - 30)))
        sc.op(OP_PTR, P_PLAYER, rnd.choice((1, 1, 0)))
        if rnd.random() < 0.1:
            sc.op(OP_MASK, rnd.choice((0, ALL_SEAMS,
                                       rnd.randrange(ALL_SEAMS + 1))))
        sc.call(F_DRIVE, 0, rnd.choice((1.0 / 60.0, 1.0 / 30.0)))
    sc.op(OP_MASK, ALL_SEAMS)
    sc.op(OP_PTR, P_PLAYER, 1)
    sc.op(OP_ANSWER, A_PLUGGED, 1)

    sc.tag("drive: a nitro")
    sc.drvf(0, "StartLineState", 0)
    sc.drvf(0, "StopRightNow", 0)
    sc.drvf(0, "LastNitroRequest", 0)
    sc.carf("UsageType", 1)
    sc.glob("RaceParametersBeACop", 1)
    t = 100000
    for frame in range(300):
        t += 67
        sc.glob("WorldTimer", t)
        if frame in (10, 150, 200, 280):
            sc.handler("NitroBoost", 126, 1, dump=False)
        sc.call(F_DRIVE, 0, 1.0 / 60.0)
    sc.glob("WorldTimer", 100000)
    sc.carf("UsageType", 0)
    sc.glob("RaceParametersBeACop", 0)

    # The e-brake's replay event is the one thing DoThrottleBrakeReverse
    # logs, and the wheel query the one thing DoSteering does, so these
    # frames are what pin the two calls' order.
    sc.tag("drive: the e-brake")
    sc.drvf(0, "LastNitroRequest", 0)
    sc.carf("VelocityMagnitude", 20.0)
    sc.carf("ForwardSpeed", 20.0)
    for wlc in (6, 7, 15):
        for eb in (0.0, 1.0):
            for forced in (0, 1):
                sc.glob("WorldLoopCounter", wlc)
                sc.drvf(0, "EBrakeInput", eb)
                sc.drvf(0, "ForcedEBrakeStop", forced)
                sc.call(F_DRIVE, 0, 1.0 / 60.0)
    sc.glob("WorldLoopCounter", 100000)
    sc.drvf(0, "EBrakeInput", 0.0)
    sc.drvf(0, "ForcedEBrakeStop", 0)
    sc.call(F_REMOVE)


def scenario_vtable(sc):
    sc.tag("vtable")
    fresh(sc)
    sc.op(OP_TARGET, 91)
    for vs in VT_SLOTS:
        if vs == 8:
            continue
        sc.vt(0, vs, 3, 1.0 / 60.0, 2.5)
    sc.carf("UsageType", 1)
    sc.vt(0, 88)
    sc.vt(0, 96)
    sc.carf("UsageType", 0)
    sc.drvf(0, "ManualTransmission", 1)
    sc.vt(0, 48)
    fresh(sc, 1, 0x33)
    sc.call(F_ADD, slot=1)
    sc.vt(1, 8, 2)
    sc.vt(1, 8, 0)


def scenario_chaos(sc, rnd):
    sc.tag("chaos")
    fresh(sc, 0)
    fresh(sc, 1, 0x11)
    sc.call(F_SET_PORT, 1, 1, dump=False)
    for _ in range(2500):
        slot = rnd.choice((0, 0, 1))
        r = rnd.random()
        if r < 0.3:
            h = rnd.randrange(len(HANDLERS))
            ev = rnd.choice((rnd.randrange(110, 127), rnd.randrange(110, 127),
                             0, 127))
            v = rnd.choice(PEDAL_VALUES + [rnd.randrange(256)])
            sc.handler(h, ev, v, slot=slot, port=rnd.choice((0, 1)))
        elif r < 0.45:
            random_motion(sc, rnd)
            sc.call(F_DRIVE, slot, 1.0 / 60.0)
        elif r < 0.55:
            fn = rnd.choice((F_ADD, F_REMOVE, F_DISABLE_SL, F_ENABLE_SL,
                             F_SET_LOW_GEAR, F_RESET_JOY, F_START_HONK,
                             F_STOP_HONK, F_NITRO_WAS, F_NITRO_ACTIVE,
                             F_NITRO_AVAIL))
            sc.call(fn, slot)
        elif r < 0.62:
            sc.call(F_SET_MANUAL, slot, rnd.choice((0, 1, 2)))
        elif r < 0.7:
            sc.glob("WorldTimer", 100000 + rnd.randrange(-20000, 40000))
            sc.glob("WorldLoopCounter", rnd.randrange(1 << 20))
            sc.glob("RaceParametersBeACop", rnd.randrange(2))
            sc.carf("UsageType", rnd.choice((0, 1)))
        elif r < 0.78:
            sc.carf("CurrentGear", rnd.randrange(-1, 7))
            sc.carf("TheMovementMode", rnd.choice((0, 4)))
            sc.carf("CopLights", rnd.randrange(256))
        elif r < 0.84:
            sc.op(OP_MASK, rnd.randrange(ALL_SEAMS + 1))
            sc.op(OP_PTR, rnd.randrange(4), rnd.choice((0, 1, 1)))
        elif r < 0.9:
            sc.op(OP_ANSWER, rnd.randrange(4), rnd.randrange(2))
        else:
            sc.call(rnd.choice((F_DTBR, F_DO_BRAKE)), slot, 1.0 / 60.0)
    sc.op(OP_MASK, ALL_SEAMS)
    for p in range(4):
        sc.op(OP_PTR, p, 1)


def scenario_teardown(sc):
    sc.tag("teardown")
    for flags in (0, 2, 1, 3):
        for pl in (1, 0):
            fresh(sc, 0, 0x77)
            sc.op(OP_PTR, P_PLAYER, pl)
            sc.call(F_ADD, dump=False)
            sc.call(F_DESTROY, 0, flags)
            fresh(sc, 0, 0x78)
            sc.call(F_DESTROY, 0, flags)
    sc.op(OP_PTR, P_PLAYER, 1)


def script():
    rnd = random.Random(0x5EA1)
    sc = Script()
    sc.tag("static")
    sc.op(OP_STATIC)
    scenario_tables(sc, rnd)
    setup(sc)
    scenario_ctor(sc)
    scenario_small(sc)
    scenario_registration(sc)
    scenario_pedals(sc, rnd)
    scenario_gearbox(sc)
    scenario_reset(sc, rnd)
    scenario_horn(sc)
    scenario_nitro(sc)
    scenario_dtbr(sc, rnd)
    scenario_steering(sc, rnd)
    scenario_drive(sc, rnd)
    scenario_vtable(sc)
    scenario_chaos(sc, rnd)
    scenario_teardown(sc)
    return sc


# ================================================================ the model


class Model(object):
    def __init__(self, sc):
        self.sc = sc
        self.out = []
        e = self.e = Emu(ieee=True)
        e.stub_bware()
        self.mask = ALL_SEAMS
        self.ans = [1, 0, 0, 1, fb(-1.0)]
        self.glob_addr = [e.addr_of(a) for _, a in GLOBS]
        self.table_addr = [e.addr_of(t) for t in TABLES]
        self.fn = {k: e.addr_of(v) for k, v in FN_SYM.items()}
        self.hfn = [e.addr_of("JoyHandler_" + h + HSUFFIX) for h in HANDLERS]
        self.hname = {a: HNAME[i] for i, a in enumerate(self.hfn)}
        self.portname = {e.addr_of(k): v for k, v in FNMAP.items()}
        self.labels = {0: "null", CAR: "car", PLAYER: "pl", COP: "cop",
                       RM: "rm", SND: "snd", ROUTE: "route", POINT: "point",
                       DRV[0]: "d0", DRV[1]: "d1", POS: "pos", VEL: "vel",
                       CTRL: "ctl", TGT: "tgt", CTI: "cti"}
        # Poison, then the pointers the image follows.
        e.mem[CAR:CAR + 0x1000] = bytes([FILL]) * 0x1000
        e.mem[CTI:CTI + 0x600] = bytes([FILL]) * 0x600
        e.mem[PLAYER:PLAYER + 0x100] = bytes([FILL]) * 0x100
        e.mem[CTRL:CTRL + 0x100] = bytes([FILL]) * 0x100
        e.put32(CAR + 12, CTI)
        e.put32(CAR + 40, CTRL)
        e.put32(CTRL + 8, CTRL_VT)
        for slot, k in ((CTRL_GET_ROUTE, 0), (CTRL_GET_POINT, 1)):
            e.put32(CTRL_VT + slot, 0)                  # delta, index
            e.put32(CTRL_VT + slot + 4, FAKE_FN + 16 * k)
        self.stubs()
        e.call("_GLOBAL_$I$PowerSlideYawCoef")

    # ---- helpers ---------------------------------------------------------

    def emit(self, s):
        self.out.append(s)

    def label(self, a):
        return self.labels.get(a & M32, "?")

    def cstr(self, p):
        if p == 0:
            return "(null)"
        end = self.e.mem.index(b"\0", p)
        return self.e.mem[p:end].decode("latin-1")

    def on(self, name):
        return self.mask >> S[name] & 1

    def vtname(self, v):
        return {VT_RD: "rd", VT_CD: "cd"}.get(v, "%08x" % v)

    def stubs(self):
        e = self.e
        emit = self.emit
        lab = self.label

        def arg(i):
            return e.reg[4 + i] & M32

        def joy_add(em):
            emit("  joy add port %d ev %d fn %s obj %s"
                 % (s32(arg(0)), s32(arg(1)),
                    self.hname.get(arg(2), "?"), lab(arg(3))))

        def joy_remove(em):
            emit("  joy remove port %d ev %d" % (s32(arg(0)), s32(arg(1))))

        def answer(what, k):
            def f(em):
                emit("  joy %s %d -> %d" % (what, s32(arg(0)), self.ans[k]))
                return self.ans[k]
            return f

        e.stub("AddJoyHandler__F12JoystickPort8JoyEventPF12JoystickPort"
               "8JoyEventUcPv_vPv", joy_add)
        e.stub("RemoveJoyHandler__F12JoystickPort8JoyEvent", joy_remove)
        e.stub("IsJoystickPluggedIn__F12JoystickPort",
               answer("plugged", A_PLUGGED))
        e.stub("IsJoystickTypeWheel__F12JoystickPort",
               answer("wheel", A_WHEEL))
        e.stub("DoesJoystickHaveStiffThrottle__F12JoystickPort",
               answer("stiff", A_STIFF))

        def seam(name, fmt):
            def f(em):
                if self.on(name):
                    emit("  seam %s %s" % (name, fmt()))
            return f

        e.stub(SEAMS[S["route-point"]][1], seam(
            "route-point", lambda: "%s %s z %08x %d %d"
            % (lab(arg(0)), lab(arg(1)), e.fpr[12], s32(arg(2)),
               s32(arg(3)))))
        e.stub(SEAMS[S["cancel-tuning"]][1], seam("cancel-tuning",
                                                  lambda: "-"))
        e.stub(SEAMS[S["blur-on"]][1], seam(
            "blur-on", lambda: "%d" % s32(arg(0))))
        e.stub(SEAMS[S["blur-off"]][1], seam(
            "blur-off", lambda: "%d" % s32(arg(0))))
        e.stub(SEAMS[S["blur-alpha"]][1], seam(
            "blur-alpha", lambda: "%d %08x %08x"
            % (s32(arg(0)), e.fpr[12], e.fpr[13])))
        e.stub(SEAMS[S["replay-event"]][1], seam(
            "replay-event", lambda: "%s %08x %s"
            % (lab(arg(0)), e.fpr[12], self.cstr(arg(1)))))
        e.stub(SEAMS[S["reroute"]][1], seam(
            "reroute", lambda: "%s %d %d %d"
            % (lab(arg(0)), s32(arg(1)), s32(arg(2)), arg(3) & 0xFF)))
        e.stub(SEAMS[S["selected-reset"]][1], seam(
            "selected-reset", lambda: lab(arg(0))))
        e.stub(SEAMS[S["siren-toggle"]][1], seam(
            "siren-toggle", lambda: lab(arg(0))))
        e.stub(SEAMS[S["reset-to-point"]][1], seam(
            "reset-to-point", lambda: "%s %s %s %08x %d %08x"
            % (lab(arg(0)), lab(arg(1)), lab(arg(2)), e.fpr[12],
               arg(3) & 0xFF, e.fpr[13])))
        e.stub(SEAMS[S["honk-start"]][1], seam(
            "honk-start", lambda: lab(arg(0))))
        e.stub(SEAMS[S["honk-stop"]][1], seam(
            "honk-stop", lambda: lab(arg(0))))

        def allowed(em):
            if not self.on("allowed-reset"):
                return 0
            emit("  seam allowed-reset %s -> %d"
                 % (lab(arg(0)), self.ans[A_ALLOWED]))
            return self.ans[A_ALLOWED]

        def direction(em):
            if not self.on("reset-direction"):
                e.fpr[0] = fb(1.0)
                return None
            emit("  seam reset-direction %s -> %08x"
                 % (lab(arg(0)), self.ans[A_DIRECTION]))
            e.fpr[0] = self.ans[A_DIRECTION] & M32
            return None

        e.stub(SEAMS[S["allowed-reset"]][1], allowed)
        e.stub(SEAMS[S["reset-direction"]][1], direction)

        def getter(what, ret):
            def f(em):
                emit("  ctl %s %s" % (what, lab(arg(0))))
                return ret
            return f

        e.stub(FAKE_FN, getter("route", ROUTE))
        e.stub(FAKE_FN + 16, getter("point", POINT))

        def delete(em):
            emit("  free %s" % lab(arg(0)))

        e.stub("__builtin_delete", delete)

    # ---- the prints ------------------------------------------------------

    def dump(self, slot):
        e = self.e
        d = DRV[slot]
        u8, u16, u32 = e.u8, e.u16, e.u32
        self.emit(
            "d%d st %04x th %08x br %08x eb %08x dg %d sg %d ni %d vt %s "
            "car %s port %d ha %d sl %d stop %d feb %d ps %d mt %d js %d %d "
            "si %08x jt %d %d %d ti %08x jb %d %d %d bi %08x jr %d %d "
            "ri %08x je %d %d ei %08x lnr %d rev %d tgt %08x | cth %08x "
            "cl %d sm %d psyc %08x"
            % (slot, u16(d + 528), u32(d + 532), u32(d + 536), u32(d + 540),
               s32(u32(d + 544)), s32(u32(d + 548)), s32(u32(d + 552)),
               self.vtname(u32(d + 556)), self.label(u32(d + 560)),
               s32(u32(d + 564)), s32(u32(d + 568)), s32(u32(d + 572)),
               s32(u32(d + 576)), s32(u32(d + 580)), s32(u32(d + 584)),
               s32(u32(d + 588)), u8(d + 592), u8(d + 593), u32(d + 596),
               u8(d + 600), u8(d + 601), u8(d + 602), u32(d + 604),
               u8(d + 608), u8(d + 609), u8(d + 610), u32(d + 612),
               u8(d + 616), u8(d + 617), u32(d + 620), u8(d + 624),
               u8(d + 625), u32(d + 628), s32(u32(d + 632)),
               s32(u32(d + 636)), fnv(e.mem[d:d + TGT_SIZE]),
               u32(STATE + 904), (u8(CAR + 1880) ^ 0x80) - 0x80,
               s32(u32(CAR + 1924)), u32(self.glob_addr[G["PowerSlideYawCoef"]])))

    def static(self):
        e = self.e
        for name in STATIC_GLOBS:
            self.emit("glob %s %08x" % (name, e.u32(self.glob_addr[G[name]])))
        for i, a in enumerate(self.table_addr):
            n = s32(e.u32(a + 4))
            p = e.u32(a)
            data = " ".join("%08x" % e.u32(p + 4 * k) for k in range(n))
            self.emit("table %d n %d min %08x max %08x mul %08x data %s"
                      % (i, n, e.u32(a + 8), e.u32(a + 12), e.u32(a + 16),
                         data))
        for k in range(1, 21):
            ent = VT_RD + 8 * k
            delta = (e.u16(ent) ^ 0x8000) - 0x8000
            index = (e.u16(ent + 2) ^ 0x8000) - 0x8000
            fn = e.u32(ent + 4)
            self.emit("vt %d %d %d %s"
                      % (8 * k, delta, index, self.portname.get(fn, "?")))

    # ---- the run ---------------------------------------------------------

    def run(self):
        e = self.e
        sc = self.sc
        emit = self.emit
        for o in sc.ops:
            code, a = o[0], o[1:]
            if code == OP_TAG:
                emit("[%s]" % sc.tags[a[0]])
            elif code == OP_FILL:
                d = DRV[a[0]]
                e.mem[d:d + DRV_SIZE] = bytes([a[1] & 0xFF]) * DRV_SIZE
            elif code == OP_INIT:
                e.call(self.fn_init(), DRV[a[0]], CAR)
            elif code == OP_DUMP:
                self.dump(a[0])
            elif code == OP_CARF:
                _, addr, w = CARF[a[0]]
                self.poke(addr, w, a[1])
            elif code == OP_DRVF:
                _, off, w = DRVF[a[1]]
                self.poke(DRV[a[0]] + off, w, a[2])
            elif code == OP_GLOB:
                e.put32(self.glob_addr[a[0]], a[1])
            elif code == OP_PTR:
                which, on = a
                if which == P_PLAYER:
                    e.put32(CAR + 24, PLAYER if on else 0)
                elif which == P_COP:
                    e.put32(self.cop_addr(), COP if on else 0)
                elif which == P_SOUND:
                    e.put32(CAR + 1952, SND if on else 0)
                else:
                    e.put32(self.rm_addr(), RM if on else 0)
            elif code == OP_ANSWER:
                self.ans[a[0]] = a[1] & M32
            elif code == OP_MASK:
                self.mask = a[0]
            elif code == OP_CALL:
                self.call(*a)
            elif code == OP_HANDLER:
                slot, h, port, ev, v = a
                e.call(self.hfn[h], port, ev, v & 0xFF, DRV[slot])
            elif code == OP_VT:
                self.vcall(*a)
            elif code == OP_TABLE:
                e.fpr[12] = a[1] & M32
                e.call("GetValue__5Tablef", self.table_addr[a[0]])
                emit("tab %d get %08x -> %08x" % (a[0], a[1] & M32, e.fpr[0]))
            elif code == OP_INV:
                e.fpr[12] = a[1] & M32
                e.call("InverseLookup__5Tablef", self.table_addr[a[0]])
                emit("tab %d inv %08x -> %08x" % (a[0], a[1] & M32, e.fpr[0]))
            elif code == OP_STATIC:
                self.static()
            elif code == OP_TARGET:
                e.write(TGT, target_bytes(a[0]))
            else:
                raise ValueError("op %d" % code)
        return self.out

    def fn_init(self):
        return "__10RealDriverP3Car"

    def cop_addr(self):
        return self.e.addr_of("pCopManager")

    def rm_addr(self):
        return self.e.addr_of("pReplayManager")

    def poke(self, addr, w, v):
        e = self.e
        if w == 4:
            e.put32(addr, v)
        elif w == 2:
            struct.pack_into("<H", e.mem, addr, v & 0xFFFF)
        else:
            e.mem[addr] = v & 0xFF

    def call(self, fn, slot, a, b, c):
        e = self.e
        d = DRV[slot]
        sym = self.fn[fn]
        if fn in (F_DRIVE, F_DTBR, F_DO_BRAKE):
            e.fpr[12] = a & M32
            e.call(sym, d)
        elif fn == F_DO_STEERING:
            e.fpr[12] = a & M32
            e.call(sym, d, b)
        elif fn == F_SET_DESIRED_SPEED:
            e.fpr[12] = a & M32
            e.fpr[13] = b & M32
            e.call(sym, d, c)
        elif fn == F_SET_PREDICTED_TARGET:
            e.call(sym, d, TGT)
        elif fn in (F_DESTROY, F_SET_MANUAL, F_FORCE_EBRAKE, F_SET_STOP,
                    F_SET_PORT):
            e.call(sym, d, a)
        else:
            r = e.call(sym, d)
            if fn in (F_NITRO_WAS, F_NITRO_ACTIVE, F_NITRO_AVAIL, F_GET_PORT,
                      F_GET_DRIVER_NUMBER):
                self.emit("ret %d" % r)
            elif fn == F_GET_CAR:
                self.emit("ret %s" % self.label(r))

    def vcall(self, slot, vslot, a, f1, f2):
        e = self.e
        d = DRV[slot]
        ent = e.u32(d + 556) + vslot
        delta = (e.u16(ent) ^ 0x8000) - 0x8000
        fn = e.u32(ent + 4)
        this = (d + delta) & M32
        e.fpr[12] = f1 & M32
        e.fpr[13] = f2 & M32
        if vslot in (8, 152):
            r = e.call(fn, this, a)
        elif vslot == 56:
            r = e.call(fn, this, a)
        elif vslot in (64, 72, 112):
            r = e.call(fn, this, TGT)
        else:
            r = e.call(fn, this)
        if vslot in (80, 104):
            self.emit("vret %d" % r)
        elif vslot in (112, 136, 144):
            self.emit("vret %08x" % e.fpr[0])
        elif vslot == 160:
            self.emit("vret %s" % self.label(r))


def model(sc):
    return Model(sc).run()


# ================================================================ the build


def build_harness(tmp, name="realdriver_test"):
    return hostbuild.build(tmp, SOURCES, name=name)


def run_harness(exe, ops_path, out_path):
    try:
        with open(out_path, "w") as fh:
            r = subprocess.run([str(exe), str(ops_path)], stdout=fh,
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

MUTATIONS = [
    # -- the tables and tunables -------------------------------------------
    ("tab-wheel-n", RDC, "SteeringWheelRangeData, 10,", "SteeringWheelRangeData, 9,"),
    ("tab-range-max", RDC,
     "table_init(&SteeringRangeTable, SteeringRangeData, 10, 0.0f, 160.0f);",
     "table_init(&SteeringRangeTable, SteeringRangeData, 10, 0.0f, 150.0f);"),
    ("tab-curve-min", RDC,
     "table_init(&SteeringCurveTable, SteeringCurveData, 6, 0.0f, 1.0f);",
     "table_init(&SteeringCurveTable, SteeringCurveData, 6, 0.1f, 1.0f);"),
    ("tab-input-max", RDC, "SteeringInputCurve, 9, 0.0f, 256.0f",
     "SteeringInputCurve, 9, 0.0f, 255.0f"),
    ("tab-yaw-data", RDC, "0.8f, 0.9f, 0.92f, 0.95f, 1.0f,",
     "0.8f, 0.9f, 0.93f, 0.95f, 1.0f,"),
    ("tab-speed-data", RDC, "1.0f, 1.0f, 0.92f, 0.78f,",
     "1.0f, 1.0f, 0.91f, 0.78f,"),
    ("tab-braking-n", RDC, "BrakingCurveTable, 6,", "BrakingCurveTable, 5,"),
    ("glob-psyc", RDC, "= 0.95f;       // 0x003231b8", "= 0.9f;       // 0x003231b8"),
    ("glob-steer-speed", RDC, "= 9.0f;        // 0x003231d8",
     "= 9.5f;        // 0x003231d8"),
    ("glob-return", RDC, "= 2.0f;        // 0x003231dc",
     "= 2.5f;        // 0x003231dc"),
    ("glob-csfs", RDC, "= 13.410818f;", "= 13.41f;"),
    ("glob-nat", RDC, "= 4.0f;        // 0x00323208",
     "= 4.5f;        // 0x00323208"),

    # -- InverseLookup ------------------------------------------------------
    ("inv-eps", TBC, "1e-6f", "1e-5f", ),

    # -- the constructor and destructor -------------------------------------
    ("ctor-port", RDC, "d->Port             = -1;", "d->Port             = 0;"),
    ("ctor-start", RDC, "d->StartLineState     = 1;",
     "d->StartLineState     = 0;"),
    ("ctor-gear", RDC, "d->Base.DesiredGear   = RD_GEAR_AUTO;",
     "d->Base.DesiredGear   = 1;"),
    ("ctor-reset", RDC, "    realdriver_reset_joy_values(d);" + NL + NL
     + "    d->StartLineState", "    d->StartLineState"),
    ("ctor-mt", RDC, "d->ManualTransmission = RD_AUTOMATIC;",
     "d->ManualTransmission = RD_SPORT;"),
    ("fini-blur", RDC, "    if (pl != NULL)" + NL
     + "        radial_blur_off(pl->PlayerNumber);" + NL, ""),
    ("fini-remove", RDC, "        radial_blur_off(pl->PlayerNumber);" + NL + NL
     + "    realdriver_remove_joy_handlers(d);",
     "        radial_blur_off(pl->PlayerNumber);" + NL),
    ("destroy-flags", RDC, "cardriver_destroy(&d->Base, flags);",
     "cardriver_destroy(&d->Base, flags & 2);"),

    # -- registration -------------------------------------------------------
    ("add-guard", RDC, "    if (d->HandlersAdded)" + NL + "        return;" + NL
     + NL + "    // Port", "    // Port"),
    ("add-flag", RDC, "    d->HandlersAdded = 1;" + NL + "}",
     "    d->HandlersAdded = 0;" + NL + "}"),
    ("add-brake-fn", RDC,
     "AddJoyHandler(p, JOY_EVENT_BRAKE, realdriver_joy_brake, d);",
     "AddJoyHandler(p, JOY_EVENT_BRAKE, realdriver_joy_throttle, d);"),
    ("add-nitro", RDC,
     "    AddJoyHandler(p, JOY_EVENT_NITRO_BOOST, realdriver_joy_nitro_boost, d);"
     + NL, ""),
    ("remove-guard", RDC, "    if (!d->HandlersAdded)" + NL + "        return;"
     + NL, ""),
    ("remove-last", RDC, "ev <= JOY_EVENT_NITRO_BOOST;",
     "ev < JOY_EVENT_NITRO_BOOST;"),
    ("remove-horn", RDC, "    call_void_slot(d, CARDRIVER_VT_STOP_HONK_HORN);"
     + NL + NL + "    d->HandlersAdded = 0;", "    d->HandlersAdded = 0;"),

    # -- the small ones -----------------------------------------------------
    ("disable-lowgear", RDC, "    d->StartLineState = 0;" + NL
     + "    call_void_slot(d, CARDRIVER_VT_SET_LOW_GEAR);",
     "    d->StartLineState = 0;"),
    ("manual-gear", RDC, "d->Base.DesiredGear   = d->pCar->State.CurrentGear;",
     "d->Base.DesiredGear   = 1;"),
    ("manual-sport", RDC, "(m == 0) ? RD_AUTOMATIC : RD_SPORT;",
     "(m == 2) ? RD_SPORT : RD_AUTOMATIC;"),
    ("lowgear-2", RDC, "(d->ManualTransmission == RD_MANUAL) ? 2",
     "(d->ManualTransmission == RD_MANUAL) ? 1"),
    ("resetjoy-steer", RDC, "d->JoySteeringAnalog          = 128;",
     "d->JoySteeringAnalog          = 0;"),
    ("resetjoy-ebrake", RDC, "    d->EBrakeInput                = 0.0f;" + NL, ""),
    ("drivernum", RDC, "return d->pCar->DriverNumber;",
     "return (uint16_t)d->pCar->DriverNumber;"),

    # -- Drive ----------------------------------------------------------------
    ("drive-plugged", RDC, "    if (!IsJoystickPluggedIn(d->Port))" + NL
     + "        realdriver_reset_joy_values(d);" + NL, ""),
    ("drive-routepoint-z", RDC, "car->State.Position.z, 0,",
     "car->State.Velocity.z, 0,"),
    ("drive-order", RDC, "    realdriver_do_throttle_brake_reverse(d, dt);" + NL
     + "    realdriver_do_steering(d, dt, d->Port);",
     "    realdriver_do_steering(d, dt, d->Port);" + NL
     + "    realdriver_do_throttle_brake_reverse(d, dt);"),
    ("drive-stop-brake", RDC, "        d->BrakeInput    = 1.0f;",
     "        d->Base.Brake    = 1.0f;"),
    ("drive-startline", RDC, "    if (d->StartLineState)" + NL
     + "        d->Base.Brake = 1.0f;", "    if (d->StartLineState)" + NL
     + "        d->BrakeInput = 1.0f;"),
    ("drive-alpha", RDC, "gRadialBlurAlphaFn(pl->PlayerNumber, 0.0f, 0.8f);",
     "gRadialBlurAlphaFn(pl->PlayerNumber, 0.0f, 0.9f);"),
    ("drive-blur-off", RDC, "    if (!realdriver_nitro_active(d) && realdriver_nitro_was_active(d))",
     "    if (!realdriver_nitro_active(d))"),

    # -- DoSteering -----------------------------------------------------------
    ("steer-fold", RDC, "    if (180.0f <= cur)", "    if (180.0f < cur)"),
    ("steer-port", RDC, "    if (IsJoystickTypeWheel(port))" + NL
     + "        range = table_get_value(&SteeringWheelRangeTable,",
     "    if (IsJoystickTypeWheel(d->Port))" + NL
     + "        range = table_get_value(&SteeringWheelRangeTable,"),
    ("steer-slide-off", RDC, "        if (ay < 5.0f)", "        if (ay <= 5.0f)"),
    ("steer-slide-speed", RDC, "        else if (spd < CounterSteerFadeStart)",
     "        else if (spd <= CounterSteerFadeStart)"),
    ("steer-slide-on", RDC, "} else if (7.0f < ay && CounterSteerFadeStart <= spd) {",
     "} else if (7.0f <= ay && CounterSteerFadeStart <= spd) {"),
    ("steer-counter", RDC, "if (yawd * d->SteeringInput < 0.0f && (d->bPowerSlide || range < ay)) {",
     "if (yawd * d->SteeringInput < 0.0f && d->bPowerSlide) {"),
    ("steer-counter-sign", RDC, "if (yawd * d->SteeringInput < 0.0f &&",
     "if (yawd * d->SteeringInput <= 0.0f &&"),
    ("steer-wheel-coef", RDC, "            PowerSlideYawCoef = 1.0f;",
     "            PowerSlideYawCoef = 0.95f;"),
    ("steer-45", RDC, "if (PowerSlideYawCoef * 45.0f < range)" + NL
     + "            range = PowerSlideYawCoef * 45.0f;",
     "if (45.0f < range)" + NL + "            range = 45.0f;"),
    ("steer-inv-sign", RDC, "cur = (r < 0.0f) ? -inv : inv;",
     "cur = (r <= 0.0f) ? -inv : inv;"),
    ("steer-return-pos", RDC, "        if (d->SteeringInput < cur)" + NL
     + "            rate *= SteeringReturnFactor;",
     "        if (d->SteeringInput > cur)" + NL
     + "            rate *= SteeringReturnFactor;"),
    ("steer-return-neg", RDC, "        if (cur < d->SteeringInput)" + NL
     + "            rate *= SteeringReturnFactor;", "        if (0)" + NL
     + "            rate *= SteeringReturnFactor;"),
    ("steer-dt", RDC, "    rate *= dt;" + NL, ""),
    ("steer-floor", RDC, "    if (rate < 0.173f)" + NL + "        rate = 0.173f;",
     "    if (rate < 0.17f)" + NL + "        rate = 0.17f;"),
    ("steer-clamp-neg", RDC, "    else if (delta < -rate)" + NL
     + "        delta = -rate;", ""),
    ("steer-out-sign", RDC, "    if (cur < 0.0f)" + NL + "        out = -out;",
     "    if (cur <= 0.0f)" + NL + "        out = -out;"),
    ("steer-ratio", RDC, "* car->pCarTypeInfo->Control.Steering" + NL,
     NL),
    ("steer-div", RDC, "* 65536.0f) / 360);", "* 65536.0f) >> 8);"),
    ("steer-yaw-abs", RDC, "    ay   = fabsf(yawd);", "    ay   = yawd;"),
    ("steer-speed-z", RDC, "spd = sqrtf((v->x * v->x + v->y * v->y) + v->z * v->z);",
     "spd = sqrtf(v->x * v->x + v->y * v->y);"),

    # -- the pedal handlers ---------------------------------------------------
    ("steer-h-255", RDC, "    if (v == 255) {", "    if (v == 254) {"),
    ("steer-h-center", RDC, "    if (v == 128)" + NL + "        v = d->JoySteeringAnalog;",
     "    if (v == 0)" + NL + "        v = d->JoySteeringAnalog;"),
    ("throttle-stiff", RDC, "? (uint32_t)value << 2" + NL, "? (uint32_t)value << 1" + NL),
    ("throttle-cap", RDC, "d->JoyThrottleAnalog = (v < 256) ? (uint8_t)v : 255;",
     "d->JoyThrottleAnalog = (uint8_t)v;"),
    ("throttle-107", RDC, "float f = (float)value * 1.07f;",
     "float f = (float)value * 1.0f;"),
    ("throttle-alt-cap", RDC, "        if (255.0f < f)" + NL + "            f = 255.0f;",
     ""),
    ("throttle-max", RDC, "        if (!(d->JoyThrottleAnalogAlternate < v))",
     "        if (d->JoyThrottleAnalogAlternate < v)"),
    ("reverse-stiff", RDC, "            v = (uint32_t)value << 2;" + NL
     + "        d->JoyReverseAnalog", "            v = value;" + NL
     + "        d->JoyReverseAnalog"),
    ("reverse-digital", RDC, "    v = d->JoyReverseDigital;" + NL
     + "    if (v == 0)" + NL + "        v = d->JoyReverseAnalog;",
     "    v = d->JoyReverseAnalog;"),
    ("brake-alt", RDC, "        d->JoyBrakeAnalogAlternate = value;",
     "        d->JoyBrakeAnalog = value;"),
    ("brake-max", RDC, "        if (!(d->JoyBrakeAnalogAlternate < v))",
     "        if (d->JoyBrakeAnalogAlternate < v)"),
    ("ebrake-wrap", RDC, "d->JoyEBrakeAnalog = (uint8_t)(value << 1);",
     "d->JoyEBrakeAnalog = (value < 128) ? (uint8_t)(value << 1) : 255;"),

    # -- DoThrottleBrakeReverse -----------------------------------------------
    ("dtbr-forced", RDC, "        d->Base.EBrake = 1.0f;" + NL + "        t = 0.0f;",
     "        d->Base.EBrake = 1.0f;" + NL + "        t = d->ThrottleInput;"),
    ("dtbr-06", RDC, "    if (0.6f < b)", "    if (BrakingSpeed <= b)"),
    ("dtbr-rev-clear", RDC, "    else if (MinSpeedForThrottleWhenReversing < fs)",
     "    else if (MinSpeedForThrottleWhenReversing <= fs)"),
    ("dtbr-fwd", RDC, "    if (MaxSpeedForReverse < fs) {",
     "    if (MaxSpeedForReverse <= fs) {"),
    ("dtbr-back", RDC, "    } else if (fs < MinSpeedForThrottle" + NL,
     "    } else if (fs <= MinSpeedForThrottle" + NL),
    ("dtbr-reversing", RDC,
     "               || (d->Reversing && fs < MinSpeedForThrottleWhenReversing)) {",
     "               || d->Reversing) {"),
    ("dtbr-double", RDC, "    rev = rev + rev;", "    rev = rev;"),
    ("dtbr-cap", RDC, "    if (1.0f < rev)" + NL + "        rev = 1.0f;", ""),
    ("dtbr-loop", RDC, "        && (((uint32_t)WorldLoopCounter + 1u) & 7u) == 0" + NL
     + "        && 10.0f < car->State.VelocityMagnitude)",
     "        && ((uint32_t)WorldLoopCounter & 7u) == 0" + NL
     + "        && 10.0f < car->State.VelocityMagnitude)"),
    ("dtbr-vm", RDC, "        && 10.0f < car->State.VelocityMagnitude)",
     "        && 10.0f <= car->State.VelocityMagnitude)"),
    ("dtbr-02", RDC, "    if (fwd + 0.2f < rev) {", "    if (fwd + 0.2f <= rev) {"),
    ("dtbr-lowgear", RDC, "        if (d->Base.DesiredGear == RD_GEAR_REVERSE)" + NL
     + "            call_void_slot(d, CARDRIVER_VT_SET_LOW_GEAR);", ""),
    ("dtbr-state", RDC, "    car->State.Throttle = d->Base.Throttle;" + NL, ""),
    ("brake-ebrake", RDC, "    if (0.5f < d->EBrakeInput" + NL,
     "    if (0.5f <= d->EBrakeInput" + NL),

    # -- the gearbox ----------------------------------------------------------
    ("up-reverse", RDC, "        if (g == RD_GEAR_REVERSE)" + NL + "            return;" + NL
     + "        if (g < d->pCar", "        if (g < d->pCar"),
    ("up-top", RDC, "DriveTrain.NumGears + 1)", "DriveTrain.NumGears)"),
    ("up-mellow", RDC, "        if (car->TheMovementMode == MELLOW_MOVEMENT)" + NL
     + "            return;" + NL + "        if (d->Base.DesiredGear == RD_GEAR_SPORT) {" + NL
     + "            g = d->Base.SportGear;" + NL + "        } else {" + NL
     + "            d->Base.DesiredGear = RD_GEAR_SPORT;" + NL
     + "            g = car->State.CurrentGear;" + NL + "        }" + NL
     + "        d->Base.SportGear = g + 1;",
     "        if (d->Base.DesiredGear == RD_GEAR_SPORT) {" + NL
     + "            g = d->Base.SportGear;" + NL + "        } else {" + NL
     + "            d->Base.DesiredGear = RD_GEAR_SPORT;" + NL
     + "            g = car->State.CurrentGear;" + NL + "        }" + NL
     + "        d->Base.SportGear = g + 1;"),
    ("down-floor", RDC, "        if (g < 2)" + NL, "        if (g < 1)" + NL),
    ("down-sport", RDC, "        d->Base.SportGear = g - 1;",
     "        d->Base.SportGear = g + 1;"),
    ("reroute-player", RDC, "    if (pl != NULL && gPlayerRerouteJoyEventFn != NULL)",
     "    if (gPlayerRerouteJoyEventFn != NULL && pl != NULL && 0)"),

    # -- the reset ------------------------------------------------------------
    ("reset-startline", RDC, "    if (d->StartLineState)" + NL + "        return;" + NL
     + "    if (value == 0)", "    if (value == 0)"),
    ("reset-neg-speed", RDC, "    speed = (speed < 0.0f) ? 0.0f : speed;" + NL, ""),
    ("reset-along", RDC, "    along = (along < 0.0f) ? 0.0f : along;" + NL, ""),
    ("reset-cap", RDC, "(speed < RollingResetSpeed) ? speed : RollingResetSpeed;",
     "(speed <= RollingResetSpeed) ? speed : RollingResetSpeed;"),
    ("reset-y", RDC, "          + car->State.BodyMatrix.v0.y" + NL,
     "          + car->State.BodyMatrix.v0.x" + NL),
    ("reset-cop", RDC, "car->pCarTypeInfo->UsageType == 1" + NL
     + "        && gCopManagerGetResetDirectionFn",
     "car->pCarTypeInfo->UsageType != 0" + NL
     + "        && gCopManagerGetResetDirectionFn"),
    ("reset-blur", RDC, "    direction = 1.0f;" + NL + "    radial_blur_off(pl->PlayerNumber);",
     "    direction = 1.0f;"),
    ("reset-flag", RDC, "gCarResetToRoutePointFn(d->pCar, route, point, speed, 1, direction);",
     "gCarResetToRoutePointFn(d->pCar, route, point, speed, 0, direction);"),
    ("reset-selected", RDC, "    if (gPlayerSelectedResetFn != NULL)" + NL
     + "        gPlayerSelectedResetFn(pl);" + NL, ""),

    # -- the horn -------------------------------------------------------------
    ("honk-stop", RDC, "    if (value == 0) {" + NL
     + "        call_void_slot(d, CARDRIVER_VT_STOP_HONK_HORN);",
     "    if (value == 0) {" + NL
     + "        call_void_slot(d, CARDRIVER_VT_START_HONK_HORN);"),
    ("honk-cancel", RDC, "    if (gCancelTuningDrivingLinesFn != NULL)" + NL
     + "        gCancelTuningDrivingLinesFn();" + NL, ""),
    ("honk-beacop", RDC, "    if (RaceParametersBeACop) {" + NL
     + "        if (gCopManagerBeACopToggleSirenAndLightsFn",
     "    if (!RaceParametersBeACop) {" + NL
     + "        if (gCopManagerBeACopToggleSirenAndLightsFn"),
    ("honk-siren", RDC, "        car->TheSirenMode = SIREN_MODE_01;",
     "        car->TheSirenMode = SIREN_MODE_02;"),
    ("honk-lights-off", RDC, "        car->CopLights    = 0;" + NL, ""),
    ("start-honk-cop", RDC, "    if (car->pCarTypeInfo->UsageType != 1 && car->pBaseCarSound != NULL" + NL
     + "        && gBaseCarSoundStartHonkHornFn",
     "    if (car->pBaseCarSound != NULL" + NL
     + "        && gBaseCarSoundStartHonkHornFn"),
    ("stop-honk-cop", RDC, "    if (car->pCarTypeInfo->UsageType != 1 && car->pBaseCarSound != NULL" + NL
     + "        && gBaseCarSoundStopHonkHornFn",
     "    if (car->pBaseCarSound != NULL" + NL
     + "        && gBaseCarSoundStopHonkHornFn"),

    # -- the nitro ------------------------------------------------------------
    ("nitro-cop", RDC, "    if (d->pCar->pCarTypeInfo->UsageType != 1)" + NL
     + "        return;" + NL + "    if (!RaceParametersBeACop)",
     "    if (!RaceParametersBeACop)"),
    ("nitro-avail", RDC, "    if (!realdriver_nitro_available(d))" + NL
     + "        return;" + NL, ""),
    ("nitro-flag", RDC, "    d->Base.NitroFlag   = 1;", "    d->Base.NitroFlag   = 2;"),
    ("nitro-valid-max", RDC, " && d->LastNitroRequest != 0x7fffffff;", ";"),
    ("nitro-age-scale", RDC, "* 0.00025f;", "* 0.00025001f;"),
    ("nitro-was-zero", RDC, "    return 0.0f <= f && f < NitrousActiveTime;",
     "    return 0.0f < f && f < NitrousActiveTime;"),
    ("nitro-was-elapsed", RDC, "float f = nitro_age(d) - WorldTimeElapsed;",
     "float f = nitro_age(d);"),
    ("nitro-active-le", RDC, "    return nitro_age(d) < NitrousActiveTime;",
     "    return nitro_age(d) <= NitrousActiveTime;"),
    ("nitro-avail-recharge", RDC,
     "return NitrousActiveTime + NitrousRechargeTime <= nitro_age(d);",
     "return NitrousActiveTime <= nitro_age(d);"),
    ("nitro-avail-invalid", RDC, "    if (!nitro_valid(d))" + NL + "        return 1;",
     "    if (!nitro_valid(d))" + NL + "        return 0;"),

    # -- the table ------------------------------------------------------------
    ("vt-lowgear", RDC, "    E(realdriver_set_low_gear),             //  48",
     "    E(cardriver_add_joy_handlers),          //  48"),
    ("vt-stophonk", RDC, "    E(realdriver_stop_honk_horn),           //  96",
     "    E(cardriver_stop_honk_horn),            //  96"),
]

EQUIVALENT = {
    # The yaw is a BAM difference times BAM_TO_RAD times 180/pi, so it
    # takes 65536 values, and none of them is 5.0 or 7.0: the nearest are
    # 4.9987793 / 5.0042725 (910 and 911) and 6.998291 / 7.003784 (1274
    # and 1275). A `<` and a `<=` against either never disagree.
    "steer-slide-off": "no yaw is exactly 5 degrees",
    "steer-slide-on": "no yaw is exactly 7 degrees",
    # r is 0 only when Steering is 0, and InverseLookup then answers the
    # table's first entry, 0.0 (its |value - first| < 1e-6 early-out), so
    # the arms differ in the sign of a zero. Neither side of the return
    # factor fires on a zero of either sign, and the addition that
    # follows turns both into the same value.
    "steer-inv-sign": "a signed zero, absorbed",
    # At cur == 0 the curve is clamped to MinArg 0.1, whose entry is 0.0,
    # so out is a zero of one sign or the other and cvt.w.s makes both 0.
    "steer-out-sign": "a signed zero, truncated",
}


def mutate_pass(only=None):
    sc = script()
    base = model(sc)
    caught = 0
    survived = []
    missing = []
    equivalent = []
    todo = [m for m in MUTATIONS if only is None or m[0] in only]
    if only is not None:
        unknown = sorted(set(only) - {m[0] for m in MUTATIONS})
        if unknown:
            sys.exit("no such mutation: " + " ".join(unknown))

    opsdir = tempfile.TemporaryDirectory()
    ops = Path(opsdir.name) / "ops.bin"
    ops.write_bytes(sc.encode())
    with tempfile.TemporaryDirectory() as tmp:
        exe = build_harness(tmp)
        out = Path(tmp) / "base.txt"
        run_harness(exe, ops, out)
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
                    exe = build_harness(tmp)
                except SystemExit:
                    print("  %-44s did not compile (caught)" % name)
                    caught += 1
                    continue
                out = Path(tmp) / "m.txt"
                if run_harness(exe, ops, out) != 0:
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
    opsdir.cleanup()

    real = [m for m in todo if m[0] not in missing]
    holes = [s for s in survived if s not in EQUIVALENT]
    if missing:
        print("%d PATTERN NOT FOUND -- the tally above is over %d of %d"
              % (len(missing), len(real), len(todo)))
    print("%d mutations, %d caught, %d equivalent, %d unexplained"
          % (len(real), caught, len(equivalent), len(holes)))
    return 1 if (holes or missing) else 0


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
        ops = Path(tmp) / "ops.bin"
        ops.write_bytes(sc.encode())
        out = Path(tmp) / "harness.txt"
        rc = run_harness(exe, ops, out)
        harness = out.read_text().splitlines()

    if args.dump:
        d = Path(args.dump)
        d.parent.mkdir(parents=True, exist_ok=True)
        d.with_suffix(".model").write_text(NL.join(lines) + NL)
        d.with_suffix(".harness").write_text(NL.join(harness) + NL)

    n = diff(lines, harness)
    print("%d ops, %d lines, %d differ" % (len(sc.ops), len(harness), n))
    sys.exit(1 if (n or rc) else 0)


if __name__ == "__main__":
    main()
