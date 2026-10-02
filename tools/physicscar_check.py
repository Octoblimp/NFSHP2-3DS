#!/usr/bin/env python3
"""Cross-check physicscar -- PhysicsCar.obj minus DoSnapshot -- against the
image itself, run in mipsemu.

    3DS Files/source/physicscar.{c,h}   the constructor and destructor, the
                                        two vtables and their deltas,
                                        Calibrate, ComputeAuxiliaries,
                                        BottomOut and the damping test,
                                        ResolveForces and IterateForces,
                                        UpdateCar, Move -- the pedals, the
                                        burn-out, the brakes, the sub-steps,
                                        the brake-stand and the dyno -- the
                                        small methods, and the static
                                        initialiser
    3DS Files/source/joystick.c         the pad-type table, two bytes
    3DS Files/source/cardamage.c        GetVisibleTotalDamage
    3DS Files/source/race.c             the race stage, first word of Race

Every other class in the car has a checker that models its arithmetic in
Python. PhysicsCar is the first that cannot sensibly be modelled that way:
its methods are orchestration -- which component is asked what, in which
order, with whose output -- and the arithmetic they drive is every other
checker's. A Python model of it would be a second port of the whole car,
and would agree with the first for the same reasons the first is wrong.

**So the oracle is the shipped code.** `mipsemu.Emu(ieee=True)` loads
NFSHP2.ELF and runs PhysicsCar's constructor, `PhysicsSystem::IntegrateEuler`
and `IntegrateRungeKutta` on the PhysicsVehicle base, UpdateCar and the rest
straight from the instruction stream -- every component method they reach,
the VU0 macro code in the matrix library, the soft-float doubles in
GetBrakeSettings -- on a Car and a CarDriver laid out in emulated memory.
The harness does the same on the port. Both then print every field of every
object the car owns, and the transcripts are compared line for line.

What the emulator does not run is stubbed, identically on both sides:

  * **The terrain.** GetElevation and GetRoadNoise are task 27's. Both
    sides answer with the same plane, normal, terrain id and noise, and log
    each call -- the topology it was asked about, the query point, and
    which object the terrain out-parameter points into.
  * **The allocator.** bOMalloc hands out zeroed blocks and bFree records
    which pool got what back; the harness reads its pools' free counts.
  * **The ticker.** Both count up 1000 per read, so ResolveTime,
    IterateTime and AuxTime are real numbers and the discarded read in
    ResolveForces is visible in them. bGetTickerDifference itself runs in
    the emulator.
  * **The skids.** Wheel::MaybeMakeSkids is the effects system's; both
    sides log the wheel and the dt it was called with.
  * **The race.** pCurrentRace is a zeroed block whose first word -- the
    only one GetRaceStage reads -- is the scenario's stage.
  * **The driver** is a RealDriver, 568 bytes, so Move can read its Port.
  * **The float model.** IEEE single, one rounding per operation: see
    mipsemu. The port runs on IEEE hardware, so that is the model it has to
    match; the EE's round-toward-zero is not what the handheld does. The
    one exception is division by zero (`eediv`). A driven pair standing
    still divides 0 by 0 on every frame a car sits in gear. The EE says
    FLT_MAX there and carries on; IEEE says NaN and the car is gone. The
    port spells those divides with eefpu.h's ee_div. The model runs every
    `div.s` by zero the EE's way and records where. The two share divides
    in DriveTrain::ApplyClutchTorque are the only ones the scenarios reach.

**The dump is generated from the port's headers.** Each struct the car owns
is parsed out of its header -- field, type, pointer-ness, and the PS2 offset
in the trailing comment -- and every offset is checked against the image's
mdebug record before anything runs. From that one parse come the harness's
dump functions, the model's reads at PS2 offsets, and a `_Static_assert`
that every field printed as raw bytes is the PS2's size on the host too.
Pointers print as what they point at -- `wheel2.Terrain+0`, `cti+704`,
`steer.AckermanMatrix+64` -- by field on each side's own layout, so a host
struct that is wider than the PS2's still labels the same.

**Uninitialised stack.** BottomOut's debug bounce builds two vectors whose
w lanes are never stored, and its stop-dead arm copies a stack quad of which
three words were written. The port zeroes them. The model zeroes BottomOut's
frame on entry, which is what the port's choice amounts to. Two components
the car drives do the same, and their ports made the same choice:
RigidBody::ComputeAuxiliaries clears the accumulators and builds gravity
from a quad whose w it never stores, and Aerodynamics' drag point has an
unstored w. Every one of those words reaches the accumulators' w lanes, so
the model zeroes each one on the instruction before it is read.
PhysicsSystem::IntegrateEuler advances all 32 words of RigidBody's state
from a derivative array whose last three the body never writes; the port
clears the array, and so does the model. Move's brake-stand zeroes P from
a stack quad with three words stored, and the model zeroes the fourth.

**Move starts from a framed car.** The Ackerman matrices are zero out of
the constructor, and the constructor frames the wheels from them, so a car
that is moving when it reaches its first Move has front wheels with no
frame. The game's cars come to Move from rest; these scenarios start at
speed, so run_move sets the steering and runs ComputeAuxiliaries once
before the first frame.

The CTI records come from extracted/GLOBAL/GLOBALB.BUN (chunk 0x34600):
the Corvette, the BMW M5 cop and the fire truck, the lightest, a middling
and the heaviest; and CORVETTEHP, the first record with HighPerformance
set, for Move's HP arms.

    python tools/physicscar_check.py
    python tools/physicscar_check.py --mutate
    python tools/physicscar_check.py --dump out/physicscar
"""
import argparse
import difflib
import os
import re
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hostbuild
import mipsemu
from mipsemu import Emu, M32, M64, f32, fbits_to, f_to_bits, s32

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "3DS Files" / "source"
NL = chr(10)

HARNESS = ROOT / "tools" / "src" / "physicscar_test.c"
BUNDLE = ROOT / "extracted" / "GLOBAL" / "GLOBALB.BUN"
MDEBUG = (ROOT / "docs" / "mdebug_structs.txt").read_text(errors="replace")

SOURCES_PORT = [
    "3DS Files/source/physicscar.c",
    "3DS Files/source/race.c",
    "3DS Files/source/cardamage.c",
    "3DS Files/source/joystick.c",
    "3DS Files/source/car.c",
    "3DS Files/source/world.c",
    "3DS Files/source/graph.c",
    "3DS Files/source/table.c",
    "3DS Files/source/aerodynamics.c",
    "3DS Files/source/physcomp.c",
    "3DS Files/source/bslotpool.c",
    "3DS Files/source/vtable.c",
    "3DS Files/source/physicssystem.c",
    "3DS Files/source/bmem.c",
    "3DS Files/source/bticker.c",
    "3DS Files/source/p32.c",
    "3DS Files/source/rigidbody.c",
    "3DS Files/source/wheel.c",
    "3DS Files/source/suspension.c",
    "3DS Files/source/engine.c",
    "3DS Files/source/drivetrain.c",
    "3DS Files/source/steering.c",
    "3DS Files/source/carstate.c",
    "3DS Files/source/emath.c",
    "3DS Files/source/bmatrix.c",
    "3DS Files/source/bvector.c",
    "3DS Files/source/bmath.c",
    "3DS Files/source/bmathtab.c",
]

PCC = "3DS Files/source/physicscar.c"
PCH = "3DS Files/source/physicscar.h"

HARNESS_TIMEOUT = 300
HARNESS_HUNG = -9

# ================================================================ the layout
#
# Which header holds which struct, and the mdebug name when it differs.

HEADERS = {
    "PhysicsCar": "physicscar.h",
    "CarMover": "physicscar.h",
    "PhysicsSystem": "physicssystem.h",
    "RigidBody": "rigidbody.h",
    "RigidBodyState": "rigidbody.h",
    "Wheel": "wheel.h",
    "SkidMaker": "wheel.h",
    "Suspension": "suspension.h",
    "Engine": "engine.h",
    "DriveTrain": "drivetrain.h",
    "Aerodynamics": "aerodynamics.h",
    "Steering": "steering.h",
    "TwoWheelAckermanSteering": "steering.h",
    "CarState": "carstate.h",
    "Table": "table.h",
}

# The pointer-bearing records a field can be: dumped field by field rather
# than as bytes, since their host layout is not the PS2's.
NESTED = {"CarMover", "PhysicsSystem", "SkidMaker", "Steering", "Table"}

# The dumped records, in the order the harness defines their functions.
DUMPED = ["Table", "SkidMaker", "Steering", "CarMover", "PhysicsSystem",
          "PhysicsCar", "RigidBody", "TwoWheelAckermanSteering", "Wheel",
          "Suspension", "Engine", "DriveTrain", "Aerodynamics", "CarState"]

# Fields the port names but mdebug does not: the two unnamed bases, the
# steering's base, and PhysicsComponent's links, which the port spells out
# in each class and the image inherits.
UNNAMED = {("PhysicsCar", "Mover"), ("PhysicsCar", "Vehicle"),
           ("TwoWheelAckermanSteering", "base")}
LINKS = {"pNext", "pPrev"}

# Fields retail added that the demo image does not have, kept where the
# demo has padding. Neither checked against mdebug nor dumped: the demo
# code these checkers run never writes them.
RETAIL_ONLY = {("CarState", "DistanceMoved")}

FIELD_RE = re.compile(
    r"^\s*(?:const\s+)?(?:struct\s+)?(\w+)\s*(\*?)\s*(?:const\s+)?(\w+)\s*"
    r"(?:\[(\w+)\])?\s*;\s*//\s*(\d+)")


class Field(object):
    def __init__(self, name, ctype, ptr, dim, off):
        self.name, self.ctype, self.ptr, self.dim, self.off = (
            name, ctype, ptr, dim, off)
        self.size = None
        if name.startswith("_pad"):
            self.kind = "pad"
        elif name.startswith(("_hole", "_tail", "_head")) or name in LINKS:
            self.kind = "skip"
        elif ptr:
            self.kind = "ptr"
        elif ctype in NESTED:
            self.kind = "nest"
        else:
            self.kind = "raw"


class Layout(object):
    def __init__(self, name, size, fields):
        self.name, self.size, self.fields = name, size, fields
        self.by = {f.name: f for f in fields}

    def off(self, name):
        return self.by[name].off


def mdebug_record(name):
    m = re.search(r"^struct/class %s \(size=(\d+) bytes\).*?(?=^struct/class )"
                  % re.escape(name), MDEBUG, re.S | re.M)
    assert m, name
    return int(m.group(1)), m.group(0)


def mdebug_fields(rec):
    """name -> (byte offset, bits), from both of the record's spellings."""
    out = {}
    for m in re.finditer(r"^\s+(\w+)\s+type#\d+\s+offset=(\d+)\s+bits=(\d+)",
                         rec, re.M):
        out[m.group(1)] = (int(m.group(2)) // 8, int(m.group(3)))
    for m in re.finditer(r"^\s+(\w+):[^\n]*\n\s+xs\w*:,(\d+),(\d+)", rec, re.M):
        out.setdefault(m.group(1), (int(m.group(2)) // 8, int(m.group(3))))
    # `Name:/<visibility><type>,offset,bits;` -- the raw stabs of a field
    # the decoder left undecoded -- and `vf<type>:<type>,offset`, the vptr.
    for m in re.finditer(r"^\s+(\w+):/[^,\n]*,(\d+),(\d+);", rec, re.M):
        out.setdefault(m.group(1), (int(m.group(2)) // 8, int(m.group(3))))
    m = re.search(r"^\s+vf\d+:\d+,(\d+)", rec, re.M)
    if m:
        out.setdefault("_vtable", (int(m.group(1)) // 8, 32))
    return out


def parse(name):
    text = (SRC / HEADERS[name]).read_text(encoding="utf-8")
    m = re.search(r"(?:typedef\s+)?struct\s+%s\s*\{(.*?)\n\}" % name, text, re.S)
    assert m, name
    fields = []
    for ln in m.group(1).splitlines():
        if ln.lstrip().startswith("#"):
            continue
        fm = FIELD_RE.match(ln)
        if not fm:
            continue
        ctype, star, fname, dim, off = fm.groups()
        d = None
        if dim is not None:
            d = int(dim) if dim.isdigit() else dim
        fields.append(Field(fname, ctype, bool(star), d, int(off)))
        if (name, fname) in RETAIL_ONLY:
            fields[-1].kind = "skip"
    size, rec = mdebug_record(name)
    for a, b in zip(fields, fields[1:] + [None]):
        a.size = (b.off if b else size) - a.off
    return Layout(name, size, fields)


def check_layout(lay):
    """Every named field at the offset and width mdebug gives it."""
    size, rec = mdebug_record(lay.name)
    md = mdebug_fields(rec)
    # A component's vptr and links are PhysicsComponent's, which is a bNode.
    if "pNext" in lay.by or "_head" in lay.by:
        md.setdefault("_vtable", mdebug_fields(
            mdebug_record("PhysicsComponent")[1])["_vtable"])
    problems = []
    for f in lay.fields:
        if f.kind == "pad" or (lay.name, f.name) in UNNAMED:
            continue
        if f.name in md:
            off, bits = md[f.name]
            if off != f.off or bits != 8 * f.size:
                problems.append("%s.%s at %d/%d bits, mdebug %d/%d"
                                % (lay.name, f.name, f.off, 8 * f.size,
                                   off, bits))
        elif f.kind != "skip":
            problems.append("%s.%s: no such field in mdebug"
                            % (lay.name, f.name))
    return problems


LAYOUT = {n: parse(n) for n in HEADERS}


def OFF(*path):
    """A PS2 offset through nested records: OFF('RigidBody', 'State', 'R')
    with the second name looked up in RigidBodyState."""
    t = path[0]
    total = 0
    for fname in path[1:]:
        f = LAYOUT[t].by[fname]
        total += f.off
        t = f.ctype
    return total


# ============================================================ the scenarios
#
# Inputs only. Both sides get the same bits: the generator writes this table
# into the harness, and the model reads it here.

def fb(v):
    return f_to_bits(f32(v))


# CORVETTE, BMWM5COP, FIRETRUCK, and CORVETTEHP -- the first record with
# HighPerformance set, which is what the body's and the engine's IsHP read.
CARS = [0, 33, 65, 1]

IDENT = [1, 0, 0, 0, 1, 0, 0, 0, 1]
YAW = [0.8, 0.6, 0, -0.6, 0.8, 0, 0, 0, 1]          # 36.87 degrees
TILT = [0.8, 0.5, 0.3125, -0.5, 0.8125, 0.25, -0.3125, -0.25, 0.875]

SCEN_FIELDS = [
    # name, C type, default
    ("car", "int", 0),
    ("pos", "f3", (0.0, 0.0, 0.4375)),
    ("mat", "f9", IDENT),
    ("vel", "f3", (0.0, 0.0, 0.0)),
    ("avel", "f3", (0.0, 0.0, 0.0)),
    ("wa", "f", 0.0),
    ("ww", "f", 0.0),
    ("rpm", "f", 1000.0),
    ("gear", "int", 1),
    ("fwd", "f", 0.0),
    ("touch", "int", 1),
    ("thr", "f", 0.0),
    ("brk", "f", 0.0),
    ("ebrk", "f", 0.0),
    ("steer", "int", 0),
    ("ctrl", "int", 0),
    ("draft", "f", 0.0),
    ("eng_thr", "f", 0.0),
    ("w_brake", "f", 0.0),
    ("w_ebrake", "f", 0.0),
    ("newcal", "int", 1),
    ("trigger", "int", 0),
    ("magic", "int", 0),
    ("testrpm", "f", 100.0),
    ("integ", "int", 0),
    ("steps", "int", 3),
    ("dt", "f", 1.0 / 60.0),
    ("thr_ovr", "f", 1.0),
    # Move's: run `steps` frames of it instead of Integrate + UpdateCar.
    ("move", "int", 0),
    ("stage", "int", 4),            # the race's; 4 is RACING
    ("dmode", "int", 0),            # CarState.DriverMode, 1 for HP
    ("boostf", "f", 1.0),           # CarState.BoostFactor
    ("joy", "int", 0),              # CurrentJoystickTypes[port]
    ("port", "int", 0),             # RealDriver.Port
    ("nitro", "int", 0),            # the driver's NitroFlag on frame 0
    ("dgear", "int", 1),
    ("sgear", "int", 0),
    ("blown", "int", 0),            # Car.BlownTireBits
    ("tbo", "f", 0.0),              # Car.fTractionBoostOverride
    ("dbo", "f", 0.0),              # Car.fDamageBoostOverride
    ("dmg", "int", -1),             # CompressedTotalDamage; -1, no CarDamage
    ("dmgon", "int", 0),            # TheRaceParameters.DamageEnabled
    ("wtimer", "int", 0),           # WorldTimer before frame 0
    ("wstep", "int", 67),           # and its advance per frame
    ("sdebug", "int", 0),           # SpeedDebugInfo
    ("sd_t", "f", 0.0),             # the dyno's three times, to start
    ("sd_qm", "f", 0.0),            # and its quarter-mile distance
    ("sd_disp", "f", 0.0),          # and its three display timers
    ("dbgprint", "int", 0),         # RigidBody- and DriveTrainDebugInfo
    ("thrpat", "int", -1),          # frame n has the throttle if bit n
    ("bstate", "int", 0),           # the burn-out, to start
    ("btime", "f", 0.0),
    ("ballow", "f", 0.0),
    ("btrac", "f", 0.0),
    ("blink", "int", 0),            # Car.BlinkTimer, for 2 seconds
    ("ycstamp", "int", 0),          # LastYawControlCollisionTime
    ("render", "int", 1),           # Car.RenderingEnabled
    ("dtype", "int", 0),            # the DriverInfo's TheDriverType
    ("seed", "int", 0x12345678),    # bDefaultSeed
    ("ebpat", "int", -1),           # frame n has the handbrake if bit n
    ("atq", "f4", (0.0, 0.0, 0.0, 0.0)),  # each wheel's AppliedTorque
    ("wterr", "i4", (-1, -1, -1, -1)),    # and its Terrain; -1 leaves it
    ("wlock", "int", 0),            # bit i locks wheel i's brake
    ("extreme", "f", 0.0),          # the CTI's MaxZMomentAccExtreme
    ("yawctl", "f", 0.0),           # and its YawControl
    ("mass", "f", 0.0),             # the body's RBI mass after the ctor
    ("reinit", "int", 0),           # InitializeStateFromCar once more
]


class Scen(object):
    def __init__(self, name, **kw):
        self.name = name
        for k, _, d in SCEN_FIELDS:
            setattr(self, k, kw.pop(k, d))
        assert not kw, kw


MOVE = dict(pos=(4.5, -2.25, 0.40625), mat=YAW, vel=(9.6, 7.2, 0.0),
            avel=(0.0, 0.0, 0.25), wa=0.5, ww=36.0, rpm=3200.0, gear=3,
            fwd=12.0, thr=0.625, eng_thr=0.75)


def mv(**kw):
    d = dict(MOVE)
    d.update(kw)
    return d


def mo(**kw):
    """Move's: the moving car, two frames of Move. The driver asks for the
    gear the car is in unless told otherwise -- a DesiredGear of NEUTRAL
    at speed shifts out of gear, and the image's gearbox divides by the
    neutral ratio of 0 on the way."""
    d = dict(MOVE, move=1, steps=2)
    d.update(kw)
    d.setdefault("dgear", d["gear"])
    return d


# The burn-out's: a player in HP mode on a pad, straight along x at 6 --
# 13.4 mph, under BurnOutMaxSpeed, and over the 5 below which GetYaw is 0
# -- with the throttle down and the rear pair over BurnOutTorqueValue. Only
# the first frame's AppliedTorque is the scenario's.
BURN = dict(MOVE, move=1, steps=1, car=3, dmode=1, ctrl=1, mat=IDENT,
            vel=(6.0, 0.0, 0.0), avel=(0.0, 0.0, 0.0), fwd=6.0, thr=1.0,
            atq=(0.0, 0.0, 2.0, 1.75))


def bo(**kw):
    d = dict(BURN)
    d.update(kw)
    d.setdefault("dgear", d["gear"])
    return d


Z3 = (0.0, 0.0, 0.0)
Z4 = (0.0, 0.0, 0.0, 0.0)
LULL = (0.5, 0.25, 0.75, -0.5)
STILL = dict(mat=IDENT, vel=Z3, avel=Z3, fwd=0.0, ww=0.0, rpm=1000.0)
STRAIGHT = dict(mat=IDENT, avel=Z3)

SCENARIOS = [
    Scen("c0-rest"),
    Scen("c0-move", **mv()),
    Scen("c33-brake", **mv(car=1, w_brake=0.5, brk=0.5, eng_thr=0.0)),
    Scen("c65-ebrake", **mv(car=2, vel=(6.4, 4.8, 0.0), fwd=8.0,
                            w_ebrake=1.0, ebrk=1.0, steer=0x0400)),
    Scen("c0-air", **mv(pos=(0.0, 0.0, 2.5), avel=(1.25, 0.5, 0.75),
                        vel=(10.0, 0.0, -1.0), touch=0)),
    Scen("c0-rk", **mv(integ=1, steps=2)),
    Scen("c33-magic", **mv(car=1, magic=1, steps=2)),
    Scen("c0-bounce", ctrl=1, trigger=1, steps=1),
    Scen("c0-bounce-ai", ctrl=0, trigger=1, steps=1),
    Scen("c0-oldcal", **mv(newcal=0, steps=1)),
    Scen("c0-testrpm", **mv(testrpm=2500.0, steps=1)),
    Scen("c65-tilted", car=2, mat=TILT, steps=2),
    Scen("c0-slow", vel=(0.5, 0.0, 0.0), steps=2),
    Scen("c33-sunk", car=1, pos=(1.0, 1.0, 0.0625), vel=(2.0, 0.0, -3.0),
         thr=0.5, steps=3),
    Scen("c1hp-move", **mv(car=3, steps=2)),
    Scen("c0-reinit", **mv(steps=1, reinit=1)),
    Scen("c0-throttle-override", **mv(thr_ovr=0.5, steps=1)),
    # Locked and gripping at once needs a wheel standing still under it:
    # GuessGroundForce leaves Slipping clear when the contact has no
    # velocity, and a lock left from the last frame stays. Rolling, a lock
    # always slips; and both wheels of a driven pair stopped and unlocked
    # split the clutch torque 0/0.
    Scen("c0-locked", **mv(mat=IDENT, vel=Z3, avel=Z3, fwd=0.0, ww=4.5,
                           thr=1.0, wlock=5, steps=2)),

    # -- Move --------------------------------------------------------------
    # The car's Angle is 0 until UpdateCar sets it, so the first frame's
    # yaw is the velocity's heading: -0.64 for MOVE's, 0 along x.
    Scen("mv-c0", **mo()),
    Scen("mv-c33-hp", **mo(car=1, dmode=1)),
    Scen("mv-c33-hp-spin", **mo(car=1, dmode=1, avel=(0.0, 0.0, -0.25),
                                steps=1)),
    Scen("mv-c0-extreme", **mo(dmode=1, extreme=12.5, steps=1)),
    Scen("mv-c65", **mo(car=2, steps=1)),
    Scen("mv-c1hp", **mo(car=3, dmode=1, ctrl=1, steps=3)),

    # The burn-out, started: which wheel, which state, what traction.
    Scen("bo-rear2", **bo(steps=2)),
    Scen("bo-rear3", **bo(atq=(0.0, 0.0, 1.75, 2.25))),
    Scen("bo-rear-tie", **bo(atq=(0.0, 0.0, 2.0, 2.0))),
    Scen("bo-front1", **bo(atq=(1.75, 2.5, 0.0, 0.0))),
    Scen("bo-front0", **bo(atq=(2.5, 1.75, 0.0, 0.0))),
    Scen("bo-front-tie", **bo(atq=(2.0, 2.0, 0.0, 0.0))),
    Scen("bo-rear-first", **bo(atq=(2.5, 2.5, 1.75, 0.0))),
    # One wheel of the pair over BurnOutTorqueValue and the other under.
    Scen("bo-rear3-only", **bo(atq=(0.0, 0.0, 1.0, 2.25))),
    Scen("bo-front1-only", **bo(atq=(1.0, 2.5, 0.0, 0.0))),
    Scen("bo-under", **bo(atq=(1.5, 1.5, 1.5, 1.5))),
    Scen("bo-clip", **bo(atq=(0.0, 0.0, 4.0, 0.0))),
    Scen("bo-slick", **bo(wterr=(0, 0, 2, 2))),
    Scen("bo-slick-3", **bo(wterr=(0, 0, 0, 2))),
    Scen("bo-slick-2", **bo(wterr=(0, 0, 3, 0))),
    Scen("bo-blinking", **bo(wtimer=10000, blink=9000, btime=0.5,
                             btrac=0.7)),
    # ... and not started.
    Scen("bo-steering", **bo(steer=0x0100)),
    Scen("bo-too-fast", **bo(vel=(6.75, 0.0, 0.0), fwd=6.75)),
    Scen("bo-stopped", **bo(vel=Z3, fwd=0.0)),
    Scen("bo-yawed", **bo(vel=(6.0, 1.5, 0.0))),
    Scen("bo-ai", **bo(ctrl=0)),
    Scen("bo-nfs", **bo(dmode=0)),
    Scen("bo-wheel", **bo(joy=21, port=1)),
    # The burn-out, running: cancelled by the clock, the yaw or a lull,
    # and a lull cut short. A lull is every wheel under
    # BurnOutCancelTorqueValue; atq of all zeros writes nothing, and leaves
    # the torques the constructor's Calibrate left, so LULL is small instead.
    Scen("bo-run-time", **bo(bstate=1, btime=0.01, btrac=0.6, atq=Z4)),
    Scen("bo-run-yaw", **bo(bstate=1, btime=1.0, btrac=0.6,
                            vel=(6.0, 2.5, 0.0))),
    Scen("bo-run-lull", **bo(bstate=2, btime=1.0, btrac=0.6, ballow=0.16,
                             atq=LULL)),
    Scen("bo-run-lull-short", **bo(bstate=2, btime=1.0, btrac=0.6,
                                   atq=LULL)),
    Scen("bo-run-torque0", **bo(bstate=1, btime=1.0, btrac=0.6, ballow=0.1,
                                atq=(1.0, 0.0, 0.0, 0.0))),
    Scen("bo-run-torque1", **bo(bstate=1, btime=1.0, btrac=0.6, ballow=0.1,
                                atq=(0.0, 1.0, 0.0, 0.0))),
    Scen("bo-run-torque2", **bo(bstate=1, btime=1.0, btrac=0.6, ballow=0.1,
                                atq=(0.0, 0.0, 1.0, 0.0))),
    Scen("bo-run-torque3", **bo(bstate=1, btime=1.0, btrac=0.6, ballow=0.1,
                                atq=(0.0, 0.0, 0.0, 1.0))),

    # The handbrake, the yaw control it winds down, and its NFS and HP
    # extras.
    Scen("mv-ebrake", **mo(ebrk=1.0, ebpat=1, steps=3)),
    Scen("mv-ebrake-clamp", **mo(ebrk=0.5, steps=3)),
    Scen("mv-ebrake-hp", **mo(dmode=1, ebrk=1.0, thr=0.0, steps=1)),
    Scen("mv-ebrake-hp-fast", **mo(dmode=1, ebrk=1.0, thr=0.0, fwd=36.0,
                                   steps=1)),
    Scen("mv-ebrake-hp-straight", **mo(dmode=1, ebrk=1.0, thr=0.0,
                                       vel=(12.0, 0.0, 0.0), steps=1,
                                       **STRAIGHT)),
    Scen("mv-ebrake-knee", **mo(ebrk=0.2, thr=0.0, steps=1)),
    Scen("mv-ebrake-knee-hp", **mo(dmode=1, ebrk=0.2, thr=0.0, steps=1)),
    # The pedals, tidied.
    Scen("mv-tidy-both", **mo(thr=0.8, brk=0.3, ebrk=0.4, steps=1)),
    Scen("mv-tidy-keep", **mo(thr=0.8, brk=0.5, ebrk=0.7, steps=1)),
    Scen("mv-tidy-lift", **mo(thr=0.4, brk=0.4, ebrk=0.1, steps=1)),
    Scen("mv-tidy-brake", **mo(thr=0.6, brk=0.7, steps=1)),
    Scen("mv-tidy-tie", **mo(thr=0.6, brk=0.1, ebrk=0.6, steps=1)),
    # The body's motion damping.
    Scen("mv-damp-thr", **mo(thr=0.3, vel=(12.0, 0.0, 0.0), steps=1,
                             **STRAIGHT)),
    Scen("mv-damp-tilt", **mo(thr=0.0, mat=TILT, steps=1)),
    Scen("mv-damp-tilt-air", **mo(thr=0.0, mat=TILT, touch=0,
                                  pos=(4.5, -2.25, 2.5), steps=1)),
    # Tilted and high enough that frame 0 leaves one wheel off the ground:
    # frame 1's Move sees three.
    Scen("mv-damp-three", **mo(thr=0.0, mat=TILT, pos=(4.5, -2.25, 0.875),
                               steps=2)),

    # Before the green light: two lurches and a third refused, the timer
    # running out under a held throttle, the countdown and the flyby.
    Scen("mv-prerace", **mo(stage=2, thr=1.0, brk=0.8, thrpat=0b1010110,
                            wstep=2000, steps=7, **STILL)),
    Scen("mv-prerace-held", **mo(stage=2, thr=1.0, wstep=1000, steps=3,
                                 **STILL)),
    Scen("mv-countdown", **mo(stage=3, thr=0.0, brk=0.8, steps=1, **STILL)),
    Scen("mv-flyby", **mo(stage=1, thr=1.0, brk=0.3, steps=1)),

    # The dyno.
    Scen("sd-stopped", **mo(sdebug=1, sd_t=-1.0, sd_disp=5.0,
                            vel=(0.25, 0.0, 0.0), fwd=0.25, steps=1,
                            **STRAIGHT)),
    Scen("sd-stopped-late", **mo(sdebug=1, sd_t=-1.0, sd_disp=5.0,
                                 wtimer=40000, vel=(0.25, 0.0, 0.0),
                                 fwd=0.25, steps=1, **STRAIGHT)),
    Scen("sd-60", **mo(sdebug=1, sd_t=-1.0, sd_disp=5.0, wtimer=40000,
                       vel=(30.0, 0.0, 0.0), fwd=30.0, ww=90.0, **STRAIGHT)),
    Scen("sd-100", **mo(sdebug=1, sd_t=-1.0, vel=(45.0, 0.0, 0.0), fwd=45.0,
                        ww=135.0, steps=1, **STRAIGHT)),
    Scen("sd-qm", **mo(sdebug=1, sd_t=-1.0, sd_qm=400.3,
                       vel=(30.0, 0.0, 0.0), fwd=30.0, ww=90.0, steps=1,
                       **STRAIGHT)),
    Scen("sd-done", **mo(sdebug=1, sd_t=2.0, vel=(45.0, 0.0, 0.0), fwd=45.0,
                         ww=135.0, steps=1, **STRAIGHT)),
    Scen("sd-prerace", **mo(sdebug=1, stage=2, sd_disp=5.0, steps=1)),

    # The gearbox, the nitro and the steering.
    Scen("mv-nitro", **mo(nitro=1, wtimer=12345)),
    # Frame 1 is 4.2 s on: the nitro's four seconds are up.
    Scen("mv-nitro-spent", **mo(nitro=1, wtimer=12345, wstep=16800)),
    Scen("mv-gear", **mo(dgear=4, sgear=1, steps=1)),
    # A SportGear SetSportGear takes (sgear 1, NEUTRAL, it refuses), and
    # SPORT_SHIFT held in the gear it asked for past ten seconds, which
    # hands the driver back AUTOMATIC.
    Scen("mv-sport", **mo(dgear=4, sgear=5, steps=1)),
    Scen("mv-sport-hold", **mo(dgear=-2, sgear=3, wstep=41000, steps=1)),
    Scen("mv-steer", **mo(steer=0x0400, steps=1)),
    # The tyres, the overrides and the damage.
    Scen("mv-blown", **mo(blown=4, tbo=0.75, dbo=1.25, steps=1)),
    Scen("mv-blown-nitro", **mo(blown=1, nitro=1, steps=1)),
    Scen("mv-overrides", **mo(tbo=0.75, dbo=1.25, steps=1)),
    Scen("mv-damage", **mo(dmg=10240, dmgon=1, steps=1)),
    Scen("mv-damage-off", **mo(dmg=10240, steps=1)),
    Scen("mv-boost", **mo(boostf=1.25, steps=1)),
    # A collision's yaw-control boost, fresh, later and spent.
    Scen("mv-collided", **mo(wtimer=20000, ycstamp=19000, steps=1)),
    Scen("mv-collided-hp", **mo(dmode=1, wtimer=20000, ycstamp=18200,
                                steps=1)),
    Scen("mv-collided-old", **mo(wtimer=40000, ycstamp=20000, steps=1)),
    # The first frame's VelocityMagnitude is 0 -- UpdateCar has not run --
    # and so is YawFrictionBoost's speed ramp, and its bonus with it. HP
    # mode reads the collision boost; a second frame, sliding, shows it.
    Scen("mv-collided-hp-slide", **mo(dmode=1, wtimer=20000, ycstamp=18200,
                                      vel=(12.0, 0.0, 0.0), steps=2)),
    Scen("mv-yawctl", **mo(yawctl=0.75, steps=1)),
    # The sub-steps, the debug prints, the skids, and the calibration.
    Scen("mv-dt-one", **mo(dt=0.0044, steps=1)),
    Scen("mv-dt-two", **mo(dt=0.0088, steps=1)),
    Scen("mv-dt-short", **mo(dt=0.001, steps=1)),
    Scen("mv-debug", **mo(dbgprint=1, steps=1)),
    Scen("mv-unrendered", **mo(render=0, steps=1)),
    Scen("mv-traffic", **mo(dtype=3, steps=1)),
    Scen("mv-heavier", **mo(mass=2000.0, steps=1)),
    Scen("mv-reinit", **mo(reinit=1, steps=1)),
]

# The grids for the direct calls, as bit patterns.

B = 0x3e800001                      # the float just above 0.25
S7 = 0x3f333334                     # the float just above 0.7 (0x3f333333)

DAMP_THR = [fb(0.25), fb(0.3), 0x3e99999b]
DAMP_VEC = [(0, 0, 0), (fb(0.25), 0, 0), (B, 0, 0), (0x3f333333, 0, 0),
            (S7, 0, 0), (fb(0.1875), fb(0.125), fb(0.0625)),
            (0, fb(0.5), fb(0.4375))]
DAMP_TILT = [(0, 0), (fb(0.25), 0), (B, 0), (B | 0x80000000, 0),
             (0, B | 0x80000000), (0, fb(-0.25))]

YAW_YAW = [fb(-0.5), fb(-0.25), 0, fb(0.25), 0x3eb2b8c4, 0x3eb2b8c3,
           fb(0.375), fb(1.25)]
YAW_EBRAKE = [0, fb(0.5), 0x3f000001, fb(1.0)]
YAW_SPEED = [fb(-5.0), 0, fb(15.0), fb(30.0), fb(45.0)]
YAW_CTRL = [(fb(0.5), fb(0.25)), (fb(1.5), fb(0.75))]
YAW_MODE = [0, 1]
YAW_TILT = [fb(-0.1875), fb(0.3125)]
YAW_BOOST = [fb(0.5), fb(2.0)]
# (LowSpeedYawBoost, HighSpeedYawBoost, LowSpeedSpeed, HighSpeedSpeed,
#  MaxYawBonus): the image's, then a set with nothing at zero.
YAW_TUNING = [None, (fb(0.25), fb(1.5), fb(4.0), fb(24.0), fb(0.5))]

BRAKE_BIAS = [fb(0.5), fb(0.625), fb(0.3), fb(0.7)]

JUMP_WHEELS = [0, 1, 2, 5]
JUMP_AV = [(0, 0, 0), (fb(0.25), 0, 0), (fb(0.25), fb(0.125), fb(0.1875)),
           (fb(1.0), fb(-0.5), fb(0.75)), (fb(2.5), fb(1.0), fb(-3.0))]

# BottomOut: (name, corners at the bump stop, velocity, trigger, mode)
BOTTOM = [
    ("none", (), (fb(9.0), 0, 0), 0, 0),
    ("corner0", (0,), (fb(9.0), 0, 0), 0, 0),
    ("corners13", (1, 3), (fb(9.0), fb(1.0), 0), 0, 0),
    ("all", (0, 1, 2, 3), (fb(5.0), 0, fb(-2.0)), 0, 0),
    ("bounce", (), (fb(9.0), 0, 0), 1, 1),
    ("bounce-ai", (), (fb(9.0), 0, 0), 1, 0),
    ("damp", (), (fb(0.5), 0, 0), 0, 0),
    ("douse", (), (fb(0.125), 0, 0), 0, 0),
    ("douse-corner2", (2,), (fb(0.125), 0, 0), 0, 0),
]

BOOSTS = [(fb(1.25), fb(0.3125)), (fb(0.5), 0)]

# IterateForces with these wheels locked and their contact patches still.
# Locked and gripping at once is a wheel whose lock outlived the frame that
# set it: GuessGroundForce skips CheckForBrakeLock when the patch has no
# velocity, and the lock stays. A scenario cannot reach it -- the first
# force pass comes after IntegrateEuler has moved the body on the
# constructor's derivative, and a wheel still after that is one of the
# front pair before its first frame, whose zero CarMatrix makes the
# correction zero too -- so the patches are stilled by hand.
LOCKS = [0x0, 0x1, 0x4, 0xf]


# ========================================================= the CTI records

def cti_records(cars=None):
    """The 1368-byte records of `cars`, CARS by default."""
    if not BUNDLE.exists():
        sys.exit("physicscar_check needs %s -- the CTI records are read out "
                 "of it" % BUNDLE.relative_to(ROOT))
    d = BUNDLE.read_bytes()
    # GLOBALB.BUN's chunk list, walked to the CarInfo chunk.
    o = 0
    while o + 8 <= len(d):
        cid, n = struct.unpack_from("<II", d, o)
        if cid == 0x00034600:
            break
        o += 8 + n
    else:
        sys.exit("no CarInfo chunk in %s" % BUNDLE)
    body = o + 8
    # The records are 16-aligned in the file; the chunk opens with the pad.
    base = (body + 15) & ~15
    assert (n - (base - body)) % 1376 == 0, n
    out = []
    for k in (CARS if cars is None else cars):
        rec = d[base + 1376 * k:base + 1376 * (k + 1)]
        out.append(rec[:1368])
    return out


# ================================================================ generation

def c_scen_fields(fields=SCEN_FIELDS):
    parts = []
    for k, t, _ in fields:
        if t == "int":
            parts.append("    int32_t  %s;" % k)
        elif t == "f":
            parts.append("    uint32_t %s;" % k)
        elif t[0] == "i":
            parts.append("    int32_t  %s[%s];" % (k, t[1:]))
        else:
            parts.append("    uint32_t %s[%s];" % (k, t[1:]))
    return NL.join(parts)


def c_scen_value(s, fields=SCEN_FIELDS):
    vals = []
    for k, t, _ in fields:
        v = getattr(s, k)
        if t == "int":
            vals.append("%d" % v)
        elif t == "f":
            vals.append("0x%08xu" % fb(v))
        elif t[0] == "i":
            vals.append("{" + ", ".join("%d" % x for x in v) + "}")
        else:
            vals.append("{" + ", ".join("0x%08xu" % fb(x) for x in v) + "}")
    return '{"%s", %s}' % (s.name, ", ".join(vals))


def c_u32_list(xs):
    return ", ".join("0x%08xu" % x for x in xs)


def c_dumps(types):
    """The declarations the dumps need, then each record's field table --
    name, host offset and host size, for the labels -- and its dump
    function, in the order given: a nested record before its container."""
    g = []
    w = g.append
    w("static void pc_raw(const char *pfx, const char *name, const void *p, size_t n);")
    w("static void pc_ptr(const char *pfx, const char *name, const void *p);")
    w("static const char *pc_sub(const char *pfx, const char *name);")
    w("")
    for t in types:
        lay = LAYOUT[t]
        for f in lay.fields:
            if f.kind == "raw":
                w('_Static_assert(sizeof(((%s *)0)->%s) == %d, "%s.%s is not '
                  'the PS2 size on the host");' % (t, f.name, f.size, t, f.name))
        rows = []
        for f in lay.fields:
            if f.kind == "pad":
                continue
            rows.append('    {"%s", offsetof(%s, %s), sizeof(((%s *)0)->%s)},'
                        % (f.name, t, f.name, t, f.name))
        w("static const PcField pcf_%s[] = {" % t)
        g.extend(rows)
        w("};")
        w('static const PcType pct_%s __attribute__((unused)) = '
          '{"%s", pcf_%s, %d};' % (t, t, t, len(rows)))
        w("")
    for t in types:
        lay = LAYOUT[t]
        w("static void dump_%s(const char *pfx, const %s *p)" % (t, t))
        w("{")
        w("    (void)pfx; (void)p;")
        for f in lay.fields:
            if f.kind == "raw":
                w('    pc_raw(pfx, "%s", &p->%s, %d);' % (f.name, f.name, f.size))
            elif f.kind == "ptr":
                if f.dim:
                    for i in range(f.dim):
                        w('    pc_ptr(pfx, "%s[%d]", p->%s[%d]);'
                          % (f.name, i, f.name, i))
                else:
                    w('    pc_ptr(pfx, "%s", p->%s);' % (f.name, f.name))
            elif f.kind == "nest":
                w('    dump_%s(pc_sub(pfx, "%s"), &p->%s);'
                  % (f.ctype, f.name, f.name))
        w("}")
        w("")
    return g


def generate(ctis):
    """The harness's prefix: the field tables, the dump functions and the
    inputs. The harness text follows it in the same translation unit."""
    g = []
    w = g.append
    w("// Generated by tools/physicscar_check.py. Do not edit.")
    w("#define PC_GENERATED 1")
    w("#include <stddef.h>")
    w("#include <stdint.h>")
    w("#include <stdio.h>")
    w('#include "physicscar.h"')
    w("")
    w("typedef struct PcField { const char *name; size_t hoff, hsize; } PcField;")
    w("typedef struct PcType { const char *name; const PcField *f; int n; } PcType;")
    g.extend(c_dumps(DUMPED))
    w("typedef struct PcScen {")
    w("    const char *name;")
    w(c_scen_fields())
    w("} PcScen;")
    w("static const PcScen pc_scen[] = {")
    for s in SCENARIOS:
        w("    " + c_scen_value(s) + ",")
    w("};")
    w("#define PC_NSCEN %d" % len(SCENARIOS))
    w("")
    w("static const uint8_t pc_cti[%d][1368] = {" % len(ctis))
    for rec in ctis:
        w("    {")
        for i in range(0, 1368, 24):
            w("        " + ", ".join("%d" % b for b in rec[i:i + 24]) + ",")
        w("    },")
    w("};")
    w("")
    w("static const uint32_t pc_damp_thr[] = {%s};" % c_u32_list(DAMP_THR))
    w("static const uint32_t pc_damp_vec[][3] = {%s};" % ", ".join(
        "{%s}" % c_u32_list(v) for v in DAMP_VEC))
    w("static const uint32_t pc_damp_tilt[][2] = {%s};" % ", ".join(
        "{%s}" % c_u32_list(v) for v in DAMP_TILT))
    for nm, xs in (("yaw", YAW_YAW), ("ebrake", YAW_EBRAKE),
                   ("speed", YAW_SPEED), ("tilt", YAW_TILT),
                   ("boost", YAW_BOOST)):
        w("static const uint32_t pc_yaw_%s[] = {%s};" % (nm, c_u32_list(xs)))
    w("static const uint32_t pc_yaw_ctrl[][2] = {%s};" % ", ".join(
        "{%s}" % c_u32_list(v) for v in YAW_CTRL))
    w("static const int32_t pc_yaw_mode[] = {%s};"
      % ", ".join(str(x) for x in YAW_MODE))
    w("static const uint32_t pc_yaw_tuning[][5] = {%s};" % ", ".join(
        "{%s}" % c_u32_list(v) for v in YAW_TUNING if v))
    w("static const uint32_t pc_brake_bias[] = {%s};" % c_u32_list(BRAKE_BIAS))
    w("static const int32_t pc_jump_wheels[] = {%s};"
      % ", ".join(str(x) for x in JUMP_WHEELS))
    w("static const uint32_t pc_jump_av[][3] = {%s};" % ", ".join(
        "{%s}" % c_u32_list(v) for v in JUMP_AV))
    w("typedef struct PcBottom { const char *name; int n; int corner[4]; "
      "uint32_t vel[3]; int32_t trigger, mode; } PcBottom;")
    w("static const PcBottom pc_bottom[] = {")
    for name, corners, vel, trig, mode in BOTTOM:
        cs = list(corners) + [0] * (4 - len(corners))
        w('    {"%s", %d, {%s}, {%s}, %d, %d},'
          % (name, len(corners), ", ".join(str(c) for c in cs),
             c_u32_list(vel), trig, mode))
    w("};")
    w("static const uint32_t pc_boost[][2] = {%s};" % ", ".join(
        "{%s}" % c_u32_list(v) for v in BOOSTS))
    w("static const int32_t pc_locks[] = {%s};"
      % ", ".join(str(x) for x in LOCKS))
    w("#define PC_N(a) ((int)(sizeof(a) / sizeof((a)[0])))")
    w("#define PC_MOVE_INDEX %d" % [s.name for s in SCENARIOS].index("c0-move"))
    w("#define PC_NORMAL_X 0x%08xu" % NORMAL[0])
    w("#define PC_NORMAL_Y 0x%08xu" % NORMAL[1])
    w("#define PC_NORMAL_Z 0x%08xu" % NORMAL[2])
    w("static const uint32_t PC_TERRAIN[4][3] = {%s};" % ", ".join(
        "{%s}" % c_u32_list(v) for v in TERRAIN))
    w("#line 1 \"physicscar_test.c\"")
    return NL.join(g) + NL


# ================================================================= the model

GP = 0x00328bf0
TOPO = 0x01E00000                  # the TopologyCoordinate the car carries
POOL_BASE = 0x01F00000
POOLS = ["RigidBody", "Ackerman", "Wheel", "Engine", "DriveTrain",
         "Aerodynamics", "Suspension"]
POOL_SLOT = [-23408, -23404, -23400, -23396, -23392, -23388, -23384]

# PhysicsCar.obj's .sdata, by gp offset, and the others by address.
G_USENEWCAL = GP - 23356
G_TRIGGER = GP - 23352
G_LOWYAW = GP - 23344
G_HIGHYAW = GP - 23340
G_LOWSPEED = GP - 23336
G_HIGHSPEED = GP - 23332
G_MAXYAW = GP - 23328
G_YAWLOCK = GP - 23312
G_MAGIC = GP - 23260
G_COUNTER = GP - 23256
G_SKIDNORM = GP - 23252
G_JUMPGRAPH = GP - 23248
G_RESOLVETIME = GP - 23240
G_ITERATETIME = GP - 23236
G_AUXTIME = 0x00323130
G_UGLY = 0x00323d70
G_TESTRPM = 0x003241cc

# Move's. PhysicsCar.obj's tuning words, in .sdata order: the two debug
# switches, NFSAdjust and MaximumTimeStep, the nine burn-out words, and
# SpeedDebugInfo; then the dyno's nine floats, and its X and R in .bss.
G_RBDEBUG = 0x003230ac
G_DTDEBUG = 0x003230b0
G_NFSADJUST = 0x003230d4
G_MAXSTEP = 0x003230d8
G_BURNOUT = 0x003230e4
G_SPEEDDEBUGINFO = 0x00323108
G_SPEEDDEBUG = 0x00323134
G_BRAKESETTINGS = 0x002e8550
G_EBRAKESETTINGS = 0x002e8560
G_SDX = 0x002e8570
G_SDR = 0x002e8580
# Everyone else's that Move reads.
G_WORLDTIMER = GP - 20224
G_WORLDELAPSED = GP - 20208
G_RACE = GP - 22776                # pCurrentRace
G_JOYTYPES = 0x00323448            # CurrentJoystickTypes, a byte a port
G_DAMAGEON = 0x00312560            # TheRaceParameters.DamageEnabled
G_SEED = GP - 15456                # bDefaultSeed
RACE_AT = 0x01E00100               # a Race: the stage is its first word
TICK = 0.00025                     # a Timer tick, in seconds

# The image's static initialisers the car needs: PhysicsCar's graph,
# RigidBody's damping tables, Wheel's tables and Aerodynamics', and Car's,
# for the post-collision yaw profile Move reads.
SINITS = [0x00137438, 0x00193d20, 0x0019b558, 0x001a4de8, 0x001347c0]

CAR_SIZE = 2016
DRIVER_SIZE = 560
REALDRIVER_SIZE = 568
PC_SIZE = 116

# CarDriver and Car, which the car reads a handful of words of.
DRV_STEERING, DRV_THROTTLE, DRV_BRAKE, DRV_EBRAKE = 528, 532, 536, 540
DRV_DESIREDGEAR, DRV_SPORTGEAR, DRV_NITRO, DRV_PORT = 544, 548, 552, 564
CAR_CONTROLMODE, CAR_STATE, CAR_DRAFT = 32, 64, 1096
CAR_MYDRIVER, CAR_COLLISIONBODY = 20, 52
CAR_TBO, CAR_DBO, CAR_RENDERING = 1100, 1104, 1160
CAR_DAMAGE, CAR_BLOWN, CAR_BLINKTIMER, CAR_BLINKDURATION = 1940, 1944, 1960, 1964
DRIVERINFO_TYPE = 4
CCB_SIZE, CCB_YAWSTAMP = 336, 264
CARDAMAGE_SIZE, CARDAMAGE_TOTAL = 212, 48
WHEEL_SKIDS = "MaybeMakeSkids__5Wheelf"

VT_CARMOVER = 0x002923e0
VT_PHYSICSCAR = 0x00292708
VT_PHYSICSCAR_VEHICLE = 0x002926e8
VT_PHYSICSVEHICLE = 0x00292728

TABLE_SYM = {
    VT_CARMOVER: "_vt$8CarMover",
    VT_PHYSICSCAR: "_vt$10PhysicsCar",
    VT_PHYSICSCAR_VEHICLE: "_vt$10PhysicsCar$14PhysicsVehicle",
    VT_PHYSICSVEHICLE: "_vt$14PhysicsVehicle",
}

# The entry the port leaves NULL until DoSnapshot lands.
PENDING = {(VT_PHYSICSCAR, 3): "DoSnapshot"}

# CarMover's Move is `__pure_virtual`, which the port spells NULL: a call
# aborts in vt_slot instead of in the pure-virtual trap.
# Where two components' uninitialised stack words are zeroed (see Model).
RB_AUX_JUNK = 0x00193bcc      # ComputeAuxiliaries, after the damping clamp
AERO_DRAG_JUNK = 0x001a4c48   # Aerodynamics::ResolveForces, the drag call
EULER_FRAME = 0x00192584      # IntegrateEuler, after `addiu sp,sp,-656`
BRAKE_STAND_P = 0x00136850    # Move, the three stores before `lqc2 vf1,0(sp)`

PURE = 0x00283c80

# The terrain stand-ins' constants: the plane z = x/32 - y/64 and its unit
# normal, and the four surfaces' static, dynamic and rolling friction.
NORMAL = tuple(fb(c / (1.0 + 1.0 / 1024 + 1.0 / 4096) ** 0.5)
               for c in (-1.0 / 32, 1.0 / 64, 1.0))
TERRAIN = [(fb(1.0), fb(0.9), fb(1.0)), (fb(1.25), fb(0.8), fb(1.5)),
           (fb(0.75), fb(0.625), fb(2.0)), (fb(1.5), fb(1.125), fb(0.5))]
TERRAIN_TABLE = 0x00310a90         # TerrainTypeInfoTable, 140-byte entries
TT_STRIDE, TT_STATIC, TT_DYNAMIC, TT_ROLLING = 140, 28, 32, 36


def hexw(ws):
    return " ".join("%08x" % x for x in ws)


class Model(object):
    def __init__(self, ctis):
        e = self.e = Emu(ieee=True, eediv=True)
        e.stub_bware()
        self.out = []
        self.ctis = ctis
        self.pc = self.car = self.drv = self.cti = 0
        self.tick = 0
        self.inuse = [0] * len(POOLS)
        self.pool_of = {}
        for i, off in enumerate(POOL_SLOT):
            e.put32(GP + off, POOL_BASE + 0x100 * i)
            self.pool_of[POOL_BASE + 0x100 * i] = i

        def omalloc(em):
            pool = em.reg[4] & M32
            p = em.alloc(512, 64)
            em.mem[p:p + 512] = bytes(512)
            self.inuse[self.pool_of[pool]] += 1
            return p

        def ofree(em):
            self.inuse[self.pool_of[em.reg[4] & M32]] -= 1

        def delete(em):
            self.deleted.append(em.reg[4] & M32)

        def afail(em):
            raise mipsemu.MipsError("bAssertFail from 0x%08x" % em.reg[31])

        def ticker(em):
            self.tick = (self.tick + 1000) & M32
            return self.tick

        e.stub("bOMalloc__FP8SlotPool", omalloc)
        e.stub("bFree__FP8SlotPoolPv", ofree)
        e.stub("__builtin_delete", delete)
        e.stub("bAssertFail__FPCcT0i", afail)
        e.stub("bPrintf__FPCce", lambda em: 0)
        e.stub("bPrintf__FcPCce", lambda em: 0)
        e.stub("bGetTicker__Fv", ticker)
        # bGetTickerDifference runs as shipped.
        del e.stubs[e.addr_of("bGetTickerDifference__FUiUi")]
        self.deleted = []

        def dbl(v):
            return struct.unpack("<d", struct.pack("<Q", v & M64))[0]

        def dbits(x):
            return struct.unpack("<Q", struct.pack("<d", x))[0]

        def dptofp(em):
            em.set_f(0, f32(dbl(em.reg[4])))

        # The soft-float doubles, natively: one IEEE double operation each.
        e.stub("fptodp", lambda em: dbits(em.f(12)))
        e.stub("dpadd", lambda em: dbits(dbl(em.reg[4]) + dbl(em.reg[5])))
        e.stub("dpsub", lambda em: dbits(dbl(em.reg[4]) - dbl(em.reg[5])))
        e.stub("dptofp", dptofp)

        e.stub("GetElevation__18TopologyCoordinatePC8bVector3P11TerrainType"
               "P8bVector3Pb", self.elevation)
        e.stub("GetRoadNoise__FP8bVector211TerrainType", self.road_noise)

        def zero_frame(em):
            sp = em.reg[29] & M32
            em.mem[sp - 144:sp] = bytes(144)

        e.hook("BottomOut__10PhysicsCar", zero_frame)

        # Two components leave a word of stack in a force's w lane, and
        # their ports write 0 there: rigidbody.c and aerodynamics.c say
        # which. Each hook sits where the function's frame is final and
        # before the word is first read.
        def zero_words(*offs):
            def h(em):
                sp = em.reg[29] & M32
                for o in offs:
                    em.put32(sp + o, 0)
            return h

        # RigidBody::ComputeAuxiliaries: sp+204 is the w of the quad that
        # zeroes both accumulators and then carries gravity; sp+220 is the
        # w of gravity's point of application.
        e.hook(RB_AUX_JUNK, zero_words(204, 220))
        # Aerodynamics::ResolveForces: sp+28 is the drag point's w.
        e.hook(AERO_DRAG_JUNK, zero_words(28))

        # PhysicsSystem::IntegrateEuler: the derivative array is the first
        # 560 bytes of the frame, and the port clears it (physicssystem.c).
        def zero_derivative(em):
            sp = em.reg[29] & M32
            em.mem[sp:sp + 560] = bytes(560)

        e.hook(EULER_FRAME, zero_derivative)

        # Move's brake stand builds a quad on the stack from three stores
        # and a fourth word nothing wrote, and stores all four in the
        # body's momentum; the port writes 0 there too.
        e.hook(BRAKE_STAND_P, zero_words(12))

        e.stub(WHEEL_SKIDS, self.skids)
        self.race = e.alloc(16, 16)
        e.mem[self.race:self.race + 16] = bytes(16)
        e.put32(G_RACE, self.race)

        for a in SINITS:
            e.call(a)
        for i, (st, dy, ro) in enumerate(TERRAIN):
            a = TERRAIN_TABLE + TT_STRIDE * i
            e.put32(a + TT_STATIC, st)
            e.put32(a + TT_DYNAMIC, dy)
            e.put32(a + TT_ROLLING, ro)

    # ---- memory

    def w(self, a):
        return self.e.u32(a)

    def put(self, a, v):
        self.e.put32(a, v)

    def f(self, a):
        return fbits_to(self.e.u32(a))

    def say(self, s):
        self.out.append(s)

    # ---- the terrain, as the harness's stand-ins have it

    def elevation(self, em):
        topo, pos, tout, nout = (em.reg[r] & M32 for r in (4, 5, 6, 7))
        x, y, z = self.f(pos), self.f(pos + 4), self.f(pos + 8)
        el = f32(f32(f32(0.03125) * x) + f32(f32(-0.015625) * y))
        self.say("elev topo=%s pos=%s tout=%s nout=%s" % (
            self.label(topo), hexw([f_to_bits(x), f_to_bits(y), f_to_bits(z)]),
            self.label(tout), self.label(nout)))
        for i, b in enumerate(NORMAL + (0,)):
            self.put(nout + 4 * i, b)
        if tout:
            h = f32(x * 0.5)
            self.put(tout, int(h) & 3 if abs(h) < 2.0 ** 31 else 0)
        em.set_f(0, el)

    def road_noise(self, em):
        xy, t = em.reg[4] & M32, s32(em.reg[5])
        x = self.f(xy)
        self.say("noise terrain=%d x=%08x" % (t, f_to_bits(x)))
        em.set_f(0, f32(f32(f32(0.25) * t) + f32(f32(0.001) * x)))

    def skids(self, em):
        self.say("skids %s dt=%08x" % (self.label(em.reg[4] & M32),
                                       em.fpr[12] & M32))

    # ---- labels

    def objects(self):
        o = []
        if self.car:
            o.append(("cs", self.car + CAR_STATE, "CarState"))
            o.append(("car", self.car, CAR_SIZE))
        if self.drv:
            o.append(("drv", self.drv, DRIVER_SIZE))
        if self.cti:
            o.append(("cti", self.cti, 1368))
        o.append(("topo", TOPO, 16))
        pc = self.pc
        if pc:
            o.append(("pc", pc, "PhysicsCar"))
            po = LAYOUT["PhysicsCar"]
            for nm, fld, t in (("body", "pBody", "RigidBody"),
                               ("steer", "pSteering",
                                "TwoWheelAckermanSteering")):
                a = self.w(pc + po.off(fld))
                if a:
                    o.append((nm, a, t))
            for i in range(4):
                a = self.w(pc + po.off("pWheel") + 4 * i)
                if a:
                    o.append(("wheel%d" % i, a, "Wheel"))
            for i in range(4):
                a = self.w(pc + po.off("pSuspension") + 4 * i)
                if a:
                    o.append(("susp%d" % i, a, "Suspension"))
            for nm, fld, t in (("engine", "pEngine", "Engine"),
                               ("dtrain", "pDriveTrain", "DriveTrain"),
                               ("aero", "pAerodynamics", "Aerodynamics")):
                a = self.w(pc + po.off(fld))
                if a:
                    o.append((nm, a, t))
        return o

    def label(self, p):
        if p == 0:
            return "null"
        for nm, base, t in self.objects():
            size = LAYOUT[t].size if isinstance(t, str) else t
            if base <= p < base + size:
                off = p - base
                if isinstance(t, str):
                    for f in LAYOUT[t].fields:
                        if f.kind != "pad" and f.off <= off < f.off + f.size:
                            return "%s.%s+%d" % (nm, f.name, off - f.off)
                return "%s+%d" % (nm, off)
        return "?"

    # ---- the dump

    def raw(self, pfx, name, a, n):
        data = self.e.read(a, n)
        if n % 4:
            self.say("%s.%s = %s" % (pfx, name,
                                     " ".join("%02x" % b for b in data)))
            return
        ws = struct.unpack("<%dI" % (n // 4), data)
        if n <= 16:
            self.say("%s.%s = %s" % (pfx, name, hexw(ws)))
            return
        for i in range(0, n // 4, 4):
            self.say("%s.%s@%d = %s" % (pfx, name, 4 * i, hexw(ws[i:i + 4])))

    def dump(self, t, pfx, a):
        for f in LAYOUT[t].fields:
            if f.kind == "raw":
                self.raw(pfx, f.name, a + f.off, f.size)
            elif f.kind == "ptr":
                if f.dim:
                    for i in range(f.dim):
                        self.say("%s.%s[%d] -> %s" % (
                            pfx, f.name, i, self.label(self.w(a + f.off + 4 * i))))
                else:
                    self.say("%s.%s -> %s" % (pfx, f.name,
                                              self.label(self.w(a + f.off))))
            elif f.kind == "nest":
                self.dump(f.ctype, pfx + "." + f.name, a + f.off)

    def globals(self):
        self.say("globals ugly=%08x trigger=%d counter=%d resolve=%08x "
                 "iterate=%08x aux=%08x tick=%d" % (
                     self.w(G_UGLY), s32(self.w(G_TRIGGER)),
                     s32(self.w(G_COUNTER)), self.w(G_RESOLVETIME),
                     self.w(G_ITERATETIME), self.w(G_AUXTIME), self.tick))

    def pools(self):
        self.say("pools " + " ".join("%s=%d" % (n, c)
                                     for n, c in zip(POOLS, self.inuse)))

    def walk(self):
        sysa = self.pc + LAYOUT["PhysicsCar"].off("Vehicle")
        for d, off in (("fwd", 0), ("back", 4)):
            names = []
            a = self.w(sysa + off)
            while a != sysa and len(names) < 32:
                names.append(self.label(a))
                a = self.w(a + off)
            self.say("list %s %s" % (d, " ".join(names)))
        self.raw("pc.Vehicle", "Size", sysa + OFF("PhysicsSystem", "Size"), 4)

    def dump_all(self, tag):
        pc = self.pc
        po = LAYOUT["PhysicsCar"]
        self.say("-- " + tag)
        self.dump("PhysicsCar", "pc", pc)
        self.dump("RigidBody", "body", self.w(pc + po.off("pBody")))
        self.dump("TwoWheelAckermanSteering", "steer",
                  self.w(pc + po.off("pSteering")))
        for i in range(4):
            self.dump("Wheel", "wheel%d" % i,
                      self.w(pc + po.off("pWheel") + 4 * i))
        for i in range(4):
            self.dump("Suspension", "susp%d" % i,
                      self.w(pc + po.off("pSuspension") + 4 * i))
        self.dump("Engine", "engine", self.w(pc + po.off("pEngine")))
        self.dump("DriveTrain", "dtrain", self.w(pc + po.off("pDriveTrain")))
        self.dump("Aerodynamics", "aero", self.w(pc + po.off("pAerodynamics")))
        self.dump("CarState", "cs", self.car + CAR_STATE)
        self.walk()
        self.globals()

    def move_extras(self):
        d = self.drv
        self.say("drv thr=%08x brk=%08x ebrk=%08x steer=%04x dgear=%d sgear=%d "
                 "nitro=%d" % (self.w(d + DRV_THROTTLE), self.w(d + DRV_BRAKE),
                               self.w(d + DRV_EBRAKE),
                               self.w(d + DRV_STEERING) & 0xffff,
                               s32(self.w(d + DRV_DESIREDGEAR)),
                               s32(self.w(d + DRV_SPORTGEAR)),
                               s32(self.w(d + DRV_NITRO))))
        self.say("dyno " + hexw([self.w(G_SPEEDDEBUG + 4 * i)
                                 for i in range(9)]))
        self.raw("dyno", "X", G_SDX, 16)
        self.raw("dyno", "R", G_SDR, 64)
        self.say("seed %08x" % self.w(G_SEED))

    # ---- calls

    def call(self, sym, *args, floats=()):
        for i, v in enumerate(floats):
            self.e.fpr[12 + i] = v
        return self.e.call(sym, *args)

    def vcall(self, obj, vptr_off, slot, *args):
        """A call through the table at obj+vptr_off, adjusting `this` by the
        entry's delta as the image's `lh ; lw ; addu ; jalr` does."""
        vt = self.w(obj + vptr_off)
        delta = struct.unpack("<h", self.e.read(vt + slot, 2))[0]
        fn = self.w(vt + slot + 4)
        return self.e.call(fn, (obj + delta) & M32, *args)

    # ---- the car

    def reset_globals(self, s):
        self.put(G_USENEWCAL, s.newcal)
        self.put(G_TRIGGER, s.trigger)
        self.put(G_MAGIC, s.magic)
        self.put(G_TESTRPM, fb(s.testrpm))
        self.put(G_UGLY, fb(1.0))
        self.put(G_COUNTER, 0)
        self.put(G_RESOLVETIME, 0)
        self.put(G_ITERATETIME, 0)
        self.put(G_AUXTIME, 0)
        self.tick = 0

        self.put(G_WORLDTIMER, s.wtimer & M32)
        self.put(G_WORLDELAPSED, 0)
        self.put(G_SPEEDDEBUGINFO, s.sdebug)
        self.put(G_RBDEBUG, s.dbgprint)
        self.put(G_DTDEBUG, s.dbgprint)
        self.put(G_SEED, s.seed & M32)
        # StartTime, the three display timers, the three times, the
        # measure and the speed.
        for i, v in enumerate([0] + [fb(s.sd_disp)] * 3 + [fb(s.sd_t)] * 3
                              + [fb(s.sd_qm), 0]):
            self.put(G_SPEEDDEBUG + 4 * i, v)
        self.e.mem[G_SDX:G_SDX + 16] = bytes(16)
        self.e.mem[G_SDR:G_SDR + 64] = bytes(64)
        self.e.mem[G_JOYTYPES:G_JOYTYPES + 2] = bytes(2)
        self.e.mem[G_JOYTYPES + s.port] = s.joy
        self.put(G_DAMAGEON, s.dmgon)
        self.put(self.race, s.stage)

    def zalloc(self, n):
        a = self.e.alloc(n, 64)
        self.e.mem[a:a + n] = bytes(n)
        return a

    def build(self, s):
        e = self.e
        self.reset_globals(s)
        cti = self.cti = e.alloc(1376, 64)
        e.write(cti, self.ctis[s.car] + bytes(8))
        self.put(cti + OFF_CTI_CONTROL + 28, fb(s.extreme))
        self.put(cti + OFF_CTI_CONTROL + 16, fb(s.yawctl))
        car = self.car = self.zalloc(CAR_SIZE)
        # A RealDriver, labelled as the CarDriver it starts with.
        drv = self.drv = self.zalloc(REALDRIVER_SIZE)
        self.put(car + CAR_CONTROLMODE, s.ctrl)
        self.put(car + CAR_DRAFT, fb(s.draft))

        di = self.zalloc(20)
        self.put(di + DRIVERINFO_TYPE, s.dtype)
        self.put(car + CAR_MYDRIVER, di)
        ccb = self.zalloc(CCB_SIZE)
        self.put(ccb + CCB_YAWSTAMP, s.ycstamp & M32)
        self.put(car + CAR_COLLISIONBODY, ccb)
        e.mem[car + CAR_RENDERING] = s.render & 0xff
        e.mem[car + CAR_BLOWN] = s.blown & 0xff
        self.put(car + CAR_TBO, fb(s.tbo))
        self.put(car + CAR_DBO, fb(s.dbo))
        if s.dmg >= 0:
            cd = self.zalloc(CARDAMAGE_SIZE)
            e.mem[cd + CARDAMAGE_TOTAL:cd + CARDAMAGE_TOTAL + 2] = struct.pack(
                "<H", s.dmg)
            self.put(car + CAR_DAMAGE, cd)
        if s.blink:
            self.put(car + CAR_BLINKTIMER, s.blink & M32)
            self.put(car + CAR_BLINKDURATION, fb(2.0))

        cs = car + CAR_STATE
        L = LAYOUT["CarState"]
        self.put(cs + L.off("DriverMode"), s.dmode)
        self.put(cs + L.off("BoostFactor"), fb(s.boostf))
        self.put(cs + L.off("BurnOutState"), s.bstate)
        self.put(cs + L.off("BurnOutTime"), fb(s.btime))
        self.put(cs + L.off("BurnOutTraction"), fb(s.btrac))
        self.put(cs + L.off("BurnOutAllow"), fb(s.ballow))
        self.put(drv + DRV_DESIREDGEAR, s.dgear)
        self.put(drv + DRV_SPORTGEAR, s.sgear)
        self.put(drv + DRV_NITRO, s.nitro)
        self.put(drv + DRV_PORT, s.port)
        self.put(cs + L.off("pCarInfo"), cti)
        self.put(cs + L.off("pTopologyCoordinate"), TOPO)
        for i in range(3):
            self.put(cs + L.off("Position") + 4 * i, fb(s.pos[i]))
            self.put(cs + L.off("Velocity") + 4 * i, fb(s.vel[i]))
            self.put(cs + L.off("AngularVelocity") + 4 * i, fb(s.avel[i]))
            for j in range(3):
                self.put(cs + L.off("BodyMatrix") + 16 * i + 4 * j,
                         fb(s.mat[3 * i + j]))
        self.put(cs + L.off("BodyMatrix") + 60, fb(1.0))
        for i in range(4):
            self.put(cs + L.off("WheelAngle") + 4 * i, fb(s.wa))
            self.put(cs + L.off("WheelAngularVelocity") + 4 * i, fb(s.ww))
            e.mem[cs + L.off("WheelTouchingGround") + i] = s.touch
        self.put(cs + L.off("nWheelsTouchingGround"), 4 * s.touch)
        self.put(cs + L.off("RPM"), fb(s.rpm))
        self.put(cs + L.off("CurrentGear"), s.gear)
        self.put(cs + L.off("ForwardSpeed"), fb(s.fwd))
        e.mem[drv + DRV_STEERING:drv + DRV_STEERING + 2] = struct.pack(
            "<H", s.steer)
        self.put(drv + DRV_THROTTLE, fb(s.thr))
        self.put(drv + DRV_BRAKE, fb(s.brk))
        self.put(drv + DRV_EBRAKE, fb(s.ebrk))
        pc = e.alloc(PC_SIZE, 64)
        e.mem[pc:pc + PC_SIZE] = bytes(PC_SIZE)
        self.pc = pc
        self.say("== " + s.name)
        self.call("__10PhysicsCarP11CarTypeInfoP9CarDriverP3Car",
                  pc, cti, drv, car)
        self.pools()

    def comp(self, field, i=None):
        po = LAYOUT["PhysicsCar"]
        off = po.off(field) + (4 * i if i is not None else 0)
        return self.w(self.pc + off)

    def after_ctor(self, s):
        self.put(self.comp("pEngine") + OFF("Engine", "Throttle"),
                 fb(s.eng_thr))
        for i in range(4):
            wa = self.comp("pWheel", i)
            self.put(wa + OFF("Wheel", "Brake"), fb(s.w_brake))
            self.put(wa + OFF("Wheel", "EBrake"), fb(s.w_ebrake))
        if fb(s.thr_ovr) != fb(1.0):
            self.put(self.comp("pEngine") + OFF("Engine", "ThrottleOverride"),
                     fb(s.thr_ovr))
        if any(fb(x) for x in s.atq):
            for i in range(4):
                self.put(self.comp("pWheel", i) + OFF("Wheel", "AppliedTorque"),
                         fb(s.atq[i]))
        for i in range(4):
            if s.wterr[i] >= 0:
                self.put(self.comp("pWheel", i) + OFF("Wheel", "Terrain"),
                         s.wterr[i])
            if s.wlock >> i & 1:
                self.put(self.comp("pWheel", i) + OFF("Wheel", "BrakeLocked"),
                         1)
        if fb(s.mass):
            rbi = self.w(self.comp("pBody") + OFF("RigidBody", "RBI"))
            self.put(rbi, fb(s.mass))

    def teardown(self, flags=0, table="mover"):
        self.deleted = []
        if table == "mover":
            self.vcall(self.pc, OFF("PhysicsCar", "Mover", "_vtable"), 8, flags)
        else:
            self.vcall(self.pc + OFF("PhysicsCar", "Vehicle"),
                       OFF("PhysicsSystem", "_vtable"), 8, flags)
        if not flags & 1:
            self.say("dtor mover.vt=%08x vehicle.vt=%08x" % (
                self.w(self.pc + OFF("PhysicsCar", "Mover", "_vtable")),
                self.w(self.pc + OFF("PhysicsCar", "Vehicle", "_vtable"))))
        self.pools()
        self.pc = self.car = self.drv = self.cti = 0

    def run_car(self, s):
        self.build(s)
        self.dump_all("ctor")
        self.after_ctor(s)
        sysa = self.pc + OFF("PhysicsCar", "Vehicle")
        integ = ("IntegrateRungeKutta__13PhysicsSystemf" if s.integ
                 else "IntegrateEuler__13PhysicsSystemf")
        for n in range(s.steps):
            self.call(integ, sysa, floats=[fb(s.dt)])
            self.dump_all("step %d" % n)
            self.call("UpdateCar__10PhysicsCarf", self.pc, floats=[fb(s.dt)])
            self.say("-- update %d" % n)
            self.dump("CarState", "cs", self.car + CAR_STATE)
        self.reinit(s)
        self.teardown()

    def reinit(self, s):
        if s.reinit:
            self.call("InitializeStateFromCar__10PhysicsCar", self.pc)
            self.dump_all("reinit")

    def run_move(self, s):
        self.build(s)
        # The Ackerman matrices are zero out of the constructor, which
        # frames the wheels from them, so a car moving into its first Move
        # has front wheels with no frame: they grip with the whole spin as
        # slip, the timestep hack stops them dead in a sub-step, and a
        # stopped front pair splits the clutch torque 0/0. The game's cars
        # come to Move from rest; these start at speed, so the steering is
        # set and the wheels framed again first.
        self.vcall(self.comp("pSteering"), OFF("Steering", "_vtable"), 16,
                   s.steer)
        self.call("ComputeAuxiliaries__10PhysicsCar", self.pc)
        self.after_ctor(s)
        d = self.drv
        for n in range(s.steps):
            self.put(G_WORLDTIMER, (s.wtimer + n * s.wstep) & M32)
            self.put(G_WORLDELAPSED, fb(float(s.wstep) * f32(TICK)))
            self.e.mem[d + DRV_STEERING:d + DRV_STEERING + 2] = struct.pack(
                "<H", s.steer)
            self.put(d + DRV_THROTTLE, fb(s.thr) if (s.thrpat >> n) & 1 else 0)
            self.put(d + DRV_BRAKE, fb(s.brk))
            self.put(d + DRV_EBRAKE, fb(s.ebrk) if (s.ebpat >> n) & 1 else 0)
            self.e.fpr[12] = fb(s.dt)
            self.vcall(self.pc, OFF("PhysicsCar", "Mover", "_vtable"), 16)
            self.say("-- move %d ret=%08x" % (n, self.e.fpr[0] & M32))
            self.dump_all("move %d" % n)
            self.move_extras()
        self.reinit(s)
        self.teardown()

    # ---- the direct calls

    def s_static(self):
        self.say("== static")
        self.say("YawLockThreshold %08x" % self.w(G_YAWLOCK))
        pts, n = self.w(G_JUMPGRAPH), s32(self.w(G_JUMPGRAPH + 4))
        self.say("JumpStabilization %d %s" % (
            n, hexw([self.w(pts + 4 * i) for i in range(2 * n)])))
        self.say("tuning %d %d %08x %08x %08x %08x %08x %d %08x" % (
            self.w(G_USENEWCAL), self.w(G_TRIGGER), self.w(G_LOWYAW),
            self.w(G_HIGHYAW), self.w(G_LOWSPEED), self.w(G_HIGHSPEED),
            self.w(G_MAXYAW), self.w(G_MAGIC), self.w(G_SKIDNORM)))
        self.say("move tuning %d %d %s %d" % (
            s32(self.w(G_RBDEBUG)), s32(self.w(G_DTDEBUG)),
            hexw([self.w(G_NFSADJUST), self.w(G_MAXSTEP)]
                 + [self.w(G_BURNOUT + 4 * i) for i in range(9)]),
            s32(self.w(G_SPEEDDEBUGINFO))))
        self.raw("move", "BrakeSettings", G_BRAKESETTINGS, 16)
        self.raw("move", "EBrakeSettings", G_EBRAKESETTINGS, 16)
        self.say("seed %08x" % self.w(G_SEED))

    def s_tables(self):
        self.say("== tables")
        vehicle = OFF("PhysicsCar", "Vehicle")
        for nm, vt in (("CarMover", VT_CARMOVER), ("PhysicsCar", VT_PHYSICSCAR),
                       ("PhysicsCar$Vehicle", VT_PHYSICSCAR_VEHICLE),
                       ("PhysicsVehicle", VT_PHYSICSVEHICLE)):
            n = self.e.elf.syms[TABLE_SYM[vt]][1] // 8
            cells = ["n=%d" % n]
            for i in range(n):
                delta = struct.unpack("<h", self.e.read(vt + 8 * i, 2))[0]
                fn = self.w(vt + 8 * i + 4)
                if (vt, i) in PENDING or fn == PURE:
                    fn = 0
                d = "pc" if delta == -vehicle and delta else str(delta)
                cells.append("%s/%s" % (d, "fn" if fn else "null"))
            self.say("vt %s %s" % (nm, " ".join(cells)))

    def s_damp(self):
        s = Scen("damp", **mv())
        self.build(s)
        self.say("-- damp")
        body = self.comp("pBody")
        R = OFF("RigidBody", "State", "R")
        n = 0
        for t in DAMP_THR:
            for v in DAMP_VEC:
                for av in DAMP_VEC:
                    for tilt in DAMP_TILT:
                        self.put(self.drv + DRV_THROTTLE, t)
                        for i in range(3):
                            self.put(body + OFF("RigidBody", "Velocity") + 4 * i,
                                     v[i])
                            self.put(body + OFF("RigidBody", "AngularVelocity")
                                     + 4 * i, av[(i + 1) % 3])
                        self.put(body + R + 8, tilt[0])
                        self.put(body + R + 16 + 8, tilt[1])
                        r = self.call("CheckDampingSuitability__10PhysicsCar",
                                      self.pc)
                        self.say("damp %d %d" % (n, r))
                        n += 1
        self.teardown()

    def s_bottom(self):
        for name, corners, vel, trig, mode in BOTTOM:
            s = Scen("bottom-" + name, **mv(ctrl=mode))
            self.build(s)
            self.after_ctor(s)
            body = self.comp("pBody")
            for i in range(3):
                self.put(body + OFF("RigidBody", "Velocity") + 4 * i, vel[i])
            self.put(self.drv + DRV_THROTTLE, 0)
            for c in corners:
                sa = self.comp("pSuspension", c)
                si = self.w(sa + OFF("Suspension", "SI"))
                self.put(sa + OFF("Suspension", "State"), self.w(si + 20))
            self.put(G_TRIGGER, trig)
            self.put(G_UGLY, fb(1.0))
            self.call("BottomOut__10PhysicsCar", self.pc)
            self.dump_all("bottom " + name)
            self.teardown()

    def s_yaw(self):
        self.say("== yaw")
        tilt_at = self.e.alloc(16, 16)
        saved = [self.w(a) for a in (G_LOWYAW, G_HIGHYAW, G_LOWSPEED,
                                     G_HIGHSPEED, G_MAXYAW)]
        n = 0
        for tuning in YAW_TUNING:
            vals = tuning or saved
            for a, v in zip((G_LOWYAW, G_HIGHYAW, G_LOWSPEED, G_HIGHSPEED,
                             G_MAXYAW), vals):
                self.put(a, v)
            for yaw in YAW_YAW:
                for eb in YAW_EBRAKE:
                    for sp in YAW_SPEED:
                        for yc, ycn in YAW_CTRL:
                            for mode in YAW_MODE:
                                for tl in YAW_TILT:
                                    for bo in YAW_BOOST:
                                        self.put(tilt_at, tl)
                                        self.call("YawFrictionBoost__FfffffiRff",
                                                  mode, tilt_at,
                                                  floats=[yaw, eb, sp, yc, ycn,
                                                          bo])
                                        self.say("yaw %d %08x %08x" % (
                                            n, self.e.fpr[0], self.w(tilt_at)))
                                        n += 1
        for a, v in zip((G_LOWYAW, G_HIGHYAW, G_LOWSPEED, G_HIGHSPEED,
                         G_MAXYAW), saved):
            self.put(a, v)

    def s_brake(self):
        s = Scen("brake", **mv())
        self.build(s)
        self.say("-- brake")
        bb_at = self.cti + OFF_CTI_BRAKEBIAS
        for bb in BRAKE_BIAS:
            self.put(bb_at, bb)
            for wh in range(4):
                self.call("GetBrakeSettings__10PhysicsCari", self.pc, wh)
                self.say("brake %08x %d %08x" % (bb, wh, self.e.fpr[0]))
        self.teardown()

    def s_jump(self):
        s = Scen("jump", **mv())
        self.build(s)
        self.say("-- jump")
        body = self.comp("pBody")
        nwh = self.car + CAR_STATE + OFF("CarState", "nWheelsTouchingGround")
        for nw in JUMP_WHEELS:
            for av in JUMP_AV:
                self.put(nwh, nw)
                for i in range(4):
                    self.put(body + OFF("RigidBody", "AngularVelocity") + 4 * i,
                             av[i] if i < 3 else 0)
                    self.put(body + OFF("RigidBody", "MomentAccumulator")
                             + 4 * i, 0)
                self.call("JumpStabilizer__10PhysicsCar", self.pc)
                self.raw("jump %d" % nw, "MomentAccumulator",
                         body + OFF("RigidBody", "MomentAccumulator"), 16)
        self.teardown()

    def s_boost(self):
        s = Scen("boost", **mv())
        self.build(s)
        for f, draft in BOOSTS:
            self.put(self.car + CAR_DRAFT, draft)
            self.call("SetBoost__10PhysicsCarf", self.pc, floats=[f])
            self.say("-- boost %08x %08x" % (f, draft))
            self.raw("engine", "CatchupTorqueMultiplier",
                     self.comp("pEngine") + OFF("Engine",
                                                "CatchupTorqueMultiplier"), 4)
            self.raw("body", "CatchUpMultiplier",
                     self.comp("pBody") + OFF("RigidBody", "CatchUpMultiplier"),
                     4)
            self.dump("Aerodynamics", "aero", self.comp("pAerodynamics"))
            for i in range(4):
                self.raw("wheel%d" % i, "CatchupFrictionMultiplier",
                         self.comp("pWheel", i)
                         + OFF("Wheel", "CatchupFrictionMultiplier"), 4)
        self.call("SetFrictionBoost__10PhysicsCarf", self.pc,
                  floats=[fb(0.75)])
        self.raw("pc", "FrictionBoost",
                 self.pc + OFF("PhysicsCar", "FrictionBoost"), 4)
        self.teardown()

    def s_dtors(self):
        s = Scen("dtor-vehicle", **mv(steps=0))
        self.build(s)
        self.teardown(0, table="vehicle")
        s = Scen("dtor-delete", **mv(steps=0))
        self.build(s)
        pc = self.pc
        self.teardown(1)
        self.say("deleted" + "".join(
            " pc" if a == pc else " other" for a in self.deleted))

    def s_joystick(self):
        self.say("== joystick")
        for c in range(256):
            self.e.mem[G_JOYTYPES + 1] = c
            r = s32(self.call("IsJoystickTypeWheel__F12JoystickPort", 1))
            if r:
                self.say("wheel %d %d" % (c, r))
        self.e.mem[G_JOYTYPES] = 7
        self.e.mem[G_JOYTYPES + 1] = 201
        self.say("type %d %d" % tuple(
            s32(self.call("GetJoystickType__F12JoystickPort", p))
            for p in (0, 1)))
        self.e.mem[G_JOYTYPES:G_JOYTYPES + 2] = bytes(2)

    def s_lock(self):
        s = Scen("lock", **mv())
        self.build(s)
        self.vcall(self.comp("pSteering"), OFF("Steering", "_vtable"), 16,
                   s.steer)
        for mask in LOCKS:
            self.call("ComputeAuxiliaries__10PhysicsCar", self.pc)
            for i in range(4):
                if mask >> i & 1:
                    wa = self.comp("pWheel", i)
                    self.put(wa + OFF("Wheel", "BrakeLocked"), 1)
                    for k in range(4):
                        self.put(wa + OFF("Wheel", "Velocity") + 4 * k, 0)
            self.call("IterateForces__10PhysicsCar", self.pc)
            self.dump_all("lock %x" % mask)
        self.teardown()

    def s_damage(self):
        self.say("== damage")
        bd = self.zalloc(196)
        for en in range(3):
            self.put(G_DAMAGEON, en)
            for t in (0, 1, 4095, 4096, 10240, 65535):
                self.e.mem[bd + 40:bd + 42] = struct.pack("<H", t)
                self.call("GetVisibleTotalDamage__10BodyDamage", bd)
                self.say("damage %d %d %08x" % (en, t, self.e.fpr[0] & M32))
        self.put(G_DAMAGEON, 0)

    def run(self):
        self.s_static()
        self.s_tables()
        for s in SCENARIOS:
            if s.move:
                self.run_move(s)
            else:
                self.run_car(s)
        self.s_damp()
        self.s_bottom()
        self.s_yaw()
        self.s_brake()
        self.s_jump()
        self.s_boost()
        self.s_dtors()
        self.s_joystick()
        self.s_damage()
        self.s_lock()
        return self.out


# ControlInfo: Control is at 768 in CarTypeInfo, and BrakeBias 12 into it
# (cartypeinfo_check holds both).
OFF_CTI_CONTROL = 768
OFF_CTI_BRAKEBIAS = OFF_CTI_CONTROL + 12


def model(ctis=None):
    return Model(ctis or cti_records()).run()


# ================================================================ the build

def build_harness(tmp, ctis, name="physicscar_test"):
    text = generate(ctis) + HARNESS.read_text(encoding="utf-8")
    src = Path(tmp) / "physicscar_test.c"
    src.write_text(text, encoding="utf-8", newline=NL)
    # The harness wraps free to see the destructor's delete.
    return hostbuild.build(tmp, [str(src)] + SOURCES_PORT, name=name,
                           flags=hostbuild.FLAGS + ["-Wl,--wrap=free"])


def run_harness(exe, out_path):
    try:
        with open(out_path, "w") as fh:
            r = subprocess.run([str(exe)], stdout=fh, stderr=subprocess.PIPE,
                               text=True, timeout=HARNESS_TIMEOUT)
    except subprocess.TimeoutExpired:
        print("harness hung, killed after %d s" % HARNESS_TIMEOUT)
        return HARNESS_HUNG
    if r.returncode != 0:
        print("harness exited %d" % r.returncode)
        if r.stderr:
            print(r.stderr[:2000])
    return r.returncode


def diff_count(a, b):
    """How many lines differ, for a mutation pass, which prints nothing else.

    difflib over ~95k lines takes minutes when a mutant moves a third of
    them, where the build and the run take seconds. A mutant almost never
    changes the transcript's shape -- every scenario prints the same fields
    -- so equal lengths are compared line for line, each changed line
    counting as the - and the + difflib would print. Otherwise the common
    head and tail are dropped and difflib sees only what is left, when that
    is small enough; past that, every line left counts."""
    if len(a) == len(b):
        return 2 * sum(1 for x, y in zip(a, b) if x != y)
    i = 0
    while i < len(a) and i < len(b) and a[i] == b[i]:
        i += 1
    j = 0
    while j < len(a) - i and j < len(b) - i and a[-1 - j] == b[-1 - j]:
        j += 1
    ma, mb = a[i:len(a) - j], b[i:len(b) - j]
    if len(ma) + len(mb) > 4000:
        return len(ma) + len(mb)
    d = difflib.unified_diff(ma, mb, lineterm="", n=0)
    return len([x for x in d if x.startswith(("+", "-"))
                and not x.startswith(("+++", "---"))])


def diff(a, b, quiet=False):
    if a == b:
        return 0
    if quiet:
        return diff_count(a, b)
    d = list(difflib.unified_diff(a, b, "model", "harness", lineterm="", n=1))
    if d and not quiet:
        for ln in d[:80]:
            print(ln)
        if len(d) > 80:
            print("... %d more diff lines" % (len(d) - 80))
    return len([x for x in d if x.startswith(("+", "-"))
                and not x.startswith(("+++", "---"))])


def layout_problems():
    out = []
    for t in DUMPED + ["RigidBodyState"]:
        out.extend(check_layout(LAYOUT[t]))
    return out


# ============================================================ the mutations

PCC = "3DS Files/source/physicscar.c"
JOYC = "3DS Files/source/joystick.c"
CDMC = "3DS Files/source/cardamage.c"
RACEC = "3DS Files/source/race.c"

MUTATIONS = [
    # -- the static initialiser ---------------------------------------------
    ("pc-sinit-knee", PCC,
     "    JumpStabilizationGraph[1].x = PC_JUMP_KNEE;",
     "    JumpStabilizationGraph[1].x = 0.5f;"),
    ("pc-sinit-top", PCC,
     "    JumpStabilizationGraph[2].y = 20.0f;",
     "    JumpStabilizationGraph[2].y = 10.0f;"),
    ("pc-sinit-yaw-lock", PCC,
     "    YawLockThreshold = PC_YAW_LOCK_THRESHOLD;",
     "    YawLockThreshold = PC_YAW_LOCK_ANGLE;"),
    ("pc-sinit-two-points", PCC,
     "    graph_init(&JumpStabilization, JumpStabilizationGraph, 3);",
     "    graph_init(&JumpStabilization, JumpStabilizationGraph, 2);"),

    # -- the constructor ------------------------------------------------------
    ("pc-ctor-friction-boost", PCC,
     "    pc->FrictionBoost         = 1.0f;",
     "    pc->FrictionBoost         = 0.0f;"),
    ("pc-ctor-body-not-hp", PCC,
     "    pc->pBody->IsHP         = (cti->HighPerformance != 0);",
     "    pc->pBody->IsHP         = 0;"),
    ("pc-ctor-no-speed-limiter", PCC,
     "    pc->pBody->SpeedLimiter = pc->CTI->Control.SpeedLimiter;",
     "    pc->pBody->SpeedLimiter = 0.0f;"),
    ("pc-ctor-tyres-by-side", PCC,
     "                                   &pc->CTI->Tires[i / 2],",
     "                                   &pc->CTI->Tires[i & 1],"),
    ("pc-ctor-steering-at-rear", PCC,
     "                                             (i < 2) ? pc->pSteering : NULL,",
     "                                             (i >= 2) ? pc->pSteering : NULL,"),
    ("pc-ctor-one-suspension-info", PCC,
     "                                             &pc->CTI->Suspension[i / 2]);",
     "                                             &pc->CTI->Suspension[0]);"),
    ("pc-ctor-sway-bar-diagonal", PCC,
     "    pc->pSuspension[0]->pSwayBar = pc->pSuspension[1];",
     "    pc->pSuspension[0]->pSwayBar = pc->pSuspension[2];"),
    ("pc-ctor-engine-not-hp", PCC,
     "    pc->pEngine->IsHP = (cti->HighPerformance != 0);",
     "    pc->pEngine->IsHP = 0;"),
    ("pc-ctor-suspension-before-wheel", PCC,
     "        physicssystem_add_component(&pc->Vehicle,\n"
     "                                    (PhysicsComponent *)pc->pWheel[i]);\n"
     "        physicssystem_add_component(&pc->Vehicle,\n"
     "                                    (PhysicsComponent *)pc->pSuspension[i]);\n",
     "        physicssystem_add_component(&pc->Vehicle,\n"
     "                                    (PhysicsComponent *)pc->pSuspension[i]);\n"
     "        physicssystem_add_component(&pc->Vehicle,\n"
     "                                    (PhysicsComponent *)pc->pWheel[i]);\n"),
    ("pc-ctor-no-calibrate", PCC,
     "    physicscar_calibrate(pc);\n    physicscar_initialize_state_from_car(pc);",
     "    physicscar_initialize_state_from_car(pc);"),
    ("pc-ctor-aux-before-state", PCC,
     "    physicscar_initialize_state_from_car(pc);\n"
     "    physicscar_compute_auxiliaries(pc);",
     "    physicscar_compute_auxiliaries(pc);\n"
     "    physicscar_initialize_state_from_car(pc);"),
    ("pc-ctor-yaw-control", PCC,
     "    pc->YawControlMultiplier = 1.0f;",
     "    pc->YawControlMultiplier = 0.5f;"),
    ("pc-ctor-throttle-held", PCC,
     "    pc->ThrottleReleased     = 1;",
     "    pc->ThrottleReleased     = 0;"),
    ("pc-ctor-three-lurches", PCC,
     "    pc->LurchsLeft           = 2;",
     "    pc->LurchsLeft           = 3;"),
    ("pc-ctor-not-brake-standing", PCC,
     "    pc->BrakeStanding        = 1;",
     "    pc->BrakeStanding        = 0;"),

    # -- the destructor -------------------------------------------------------
    ("pc-dtor-steering-kept", PCC,
     "        ((SteeringDtorFn)e->fn)(vt_this(pc->pSteering, e), 3);",
     "        ((SteeringDtorFn)e->fn)(vt_this(pc->pSteering, e), 2);"),
    ("pc-dtor-aero-kept", PCC,
     "    aerodynamics_delete(pc->pAerodynamics);\n",
     ""),
    ("pc-dtor-never-deletes", PCC,
     "    carmover_destroy(&pc->Mover, flags);",
     "    carmover_destroy(&pc->Mover, flags & 2);"),
    ("pc-dtor-vehicle-vt-not-restored", PCC,
     "    pc->Vehicle._vtable = PHYSICSCAR_VEHICLE_VTABLE;\n"
     "    pc->Mover._vtable   = PHYSICSCAR_VTABLE;\n\n    if (pc->pSteering",
     "    pc->Mover._vtable   = PHYSICSCAR_VTABLE;\n\n    if (pc->pSteering"),

    # -- Calibrate ------------------------------------------------------------
    ("pc-cal-always-new", PCC,
     "    cog = UseNewSuspensionCalibration ? cti->CenterOfGravity.x : 0.0f;",
     "    cog = cti->CenterOfGravity.x;"),
    ("pc-cal-split-sign", PCC,
     "    rear  = (a / (a - b)) * 0.5f;",
     "    rear  = (a / (b - a)) * 0.5f;"),
    ("pc-cal-front-whole", PCC,
     "    front = 0.5f - rear;",
     "    front = 1.0f - rear;"),
    ("pc-cal-gravity", PCC,
     "    total = pc->pBody->Mass * PC_GRAVITY;",
     "    total = pc->pBody->Mass * 9.81f;"),
    ("pc-cal-downforce-subtracted", PCC,
     "    total = total + cti->Aero.AutoBalanceDownforce",
     "    total = total - cti->Aero.AutoBalanceDownforce"),
    ("pc-cal-front-gets-rear", PCC,
     "    suspension_calibrate(pc->pSuspension[0], front);",
     "    suspension_calibrate(pc->pSuspension[0], rear);"),
    ("pc-cal-no-inertia", PCC,
     "    rigidbody_calculate_inertia_tensor(pc->pBody);\n\n    cti = pc->CTI;",
     "    cti = pc->CTI;"),
    ("pc-cal-no-cog", PCC,
     "    rigidbody_calibrate(pc->pBody,\n"
     "                        (const bVector4 *)&pc->CTI->CenterOfGravity);\n",
     ""),
    ("pc-cal-last-wheel", PCC,
     "    wheel_calibrate(pc->pWheel[3]);\n",
     ""),

    # -- ComputeAuxiliaries ---------------------------------------------------
    ("pc-aux-no-bottom-out", PCC,
     "    physicssystem_compute_auxiliaries(&pc->Vehicle);\n"
     "    physicscar_bottom_out(pc);\n",
     "    physicssystem_compute_auxiliaries(&pc->Vehicle);\n"),
    ("pc-aux-no-resolve", PCC,
     "    ((PhysicsVoidFn)e->fn)(vt_this(&pc->Vehicle, e));",
     "    (void)e;"),

    # -- the damping test and BottomOut ---------------------------------------
    ("pc-damp-throttle-le", PCC,
     "    if (PC_DAMP_THROTTLE < pc->Mover.Driver->Throttle)",
     "    if (PC_DAMP_THROTTLE <= pc->Mover.Driver->Throttle)"),
    ("pc-damp-spin-ignored", PCC,
     "    if (PC_DAMP_SPEED < v || PC_DAMP_SPEED < w)",
     "    if (PC_DAMP_SPEED < v)"),
    ("pc-damp-roll-ignored", PCC,
     "    if (0.25f < fabsf(rb->State.R.v0.z) || 0.25f < fabsf(rb->State.R.v1.z))",
     "    if (0.25f < fabsf(rb->State.R.v0.z))"),
    ("pc-damp-pitch-from-y", PCC,
     "    if (0.25f < fabsf(rb->State.R.v0.z) || 0.25f < fabsf(rb->State.R.v1.z))",
     "    if (0.25f < fabsf(rb->State.R.v0.y) || 0.25f < fabsf(rb->State.R.v1.z))"),
    ("pc-damp-douse-band", PCC,
     "    if (0.25f < v || 0.25f < w)\n        return DS_DAMP;",
     "    if (0.5f < v || 0.25f < w)\n        return DS_DAMP;"),
    ("pc-damp-factor", PCC,
     "        float k = PC_DAMP_FACTOR;",
     "        float k = 0.9f;"),
    ("pc-damp-p-w-kept", PCC,
     "  rb->State.P.w *= k;",
     ""),
    ("pc-damp-wheels-kept", PCC,
     "            wheel_set_state_w(pc->pWheel[i], pc->pWheel[i]->State.w * k);",
     "            wheel_set_state_w(pc->pWheel[i], pc->pWheel[i]->State.w);"),
    ("pc-douse-wheels-kept", PCC,
     "            wheel_set_state_w(pc->pWheel[i], 0.0f);",
     "            wheel_set_state_w(pc->pWheel[i], pc->pWheel[i]->State.w);"),
    ("pc-douse-spin-kept", PCC,
     "        pc->pBody->State.L = zero;\n",
     ""),
    ("pc-bottom-ugly-hack", PCC,
     "        gUglyTimestepHack = 0.0f;",
     "        gUglyTimestepHack = 1.0f;"),
    ("pc-bottom-no-aux", PCC,
     "        gUglyTimestepHack = 0.0f;\n"
     "        physicssystem_compute_auxiliaries(&pc->Vehicle);\n",
     "        gUglyTimestepHack = 0.0f;\n"),
    ("pc-bottom-le", PCC,
     "        if (s->State.z == s->SI->BumpStop[0]) {",
     "        if (s->State.z <= s->SI->BumpStop[0]) {"),
    ("pc-bottom-magnitude-set", PCC,
     "            pc->State->WheelBottomOutMagnitude[i] += m;",
     "            pc->State->WheelBottomOutMagnitude[i] = m;"),
    ("pc-bounce-any-mode", PCC,
     "    if (TriggerBounce && pc->pCar->TheControlMode == 1) {",
     "    if (TriggerBounce) {"),
    ("pc-bounce-not-cleared", PCC,
     "        TriggerBounce = 0;\n",
     ""),
    ("pc-bounce-size", PCC,
     "        bVector4 j  = { 0.0f, 0.0f, 25.0f, 0.0f };",
     "        bVector4 j  = { 0.0f, 0.0f, 20.0f, 0.0f };"),

    # -- YawFrictionBoost -----------------------------------------------------
    ("pc-yaw-tilt-signed", PCC,
     "    *tilt = fabsf(*tilt);\n",
     ""),
    ("pc-yaw-base-no-one", PCC,
     "    base = *tilt + 1.0f;",
     "    base = *tilt;"),
    ("pc-yaw-post-collision-ignored", PCC,
     "        control = yawControl + postCollisionBoost * yawControlNFS;",
     "        control = yawControl + yawControlNFS;"),
    ("pc-yaw-ebrake-any-angle", PCC,
     "    if (0.5f < ebrake && m < PC_YAW_LOCK_ANGLE)",
     "    if (0.5f < ebrake)"),
    ("pc-yaw-ebrake-le", PCC,
     "    if (0.5f < ebrake && m < PC_YAW_LOCK_ANGLE)",
     "    if (0.5f <= ebrake && m < PC_YAW_LOCK_ANGLE)"),
    ("pc-yaw-no-cap", PCC,
     "    if (MaxYawBonus < bonus)\n        bonus = MaxYawBonus;\n",
     ""),
    ("pc-yaw-lerp-from-zero", PCC,
     "        + (HighSpeedYawBoost - LowSpeedYawBoost)",
     "        + HighSpeedYawBoost"),
    ("pc-yaw-speed-from-zero", PCC,
     "          * ((speed - LowSpeedSpeed) / (HighSpeedSpeed - LowSpeedSpeed));",
     "          * (speed / (HighSpeedSpeed - LowSpeedSpeed));"),

    # -- GetBrakeSettings -----------------------------------------------------
    ("pc-brake-front-single", PCC,
     "        return bb + bb;",
     "        return bb;"),
    ("pc-brake-one-front", PCC,
     "    if (wheel < 2)",
     "    if (wheel < 1)"),
    ("pc-brake-rear-in-float", PCC,
     "    r = 1.0 - (double)bb;\n    return (float)(r + r);",
     "    return (1.0f - bb) + (1.0f - bb);"),

    # -- InitializeStateFromCar ----------------------------------------------
    ("pc-init-testrpm-inverted", PCC,
     "    if (TestRPM == 100.0f)",
     "    if (TestRPM != 100.0f)"),
    ("pc-init-rpm-unscaled", PCC,
     "    pc->pEngine->State.w = rpm * PC_RPM_TO_RADS;",
     "    pc->pEngine->State.w = rpm;"),
    ("pc-init-clutch-out", PCC,
     "    pc->pDriveTrain->State.clutch       = 1.0f;",
     "    pc->pDriveTrain->State.clutch       = 0.0f;"),
    ("pc-init-desired-gear", PCC,
     "    pc->pDriveTrain->DesiredGear        = cs->CurrentGear;",
     "    pc->pDriveTrain->DesiredGear        = (Gear)(cs->CurrentGear + 1);"),
    ("pc-init-clutch-engaging", PCC,
     "    pc->pDriveTrain->CurrentClutchState = CLUTCH_ENGAGED;",
     "    pc->pDriveTrain->CurrentClutchState = CLUTCH_ENGAGING;"),
    ("pc-init-wheel-args-swapped", PCC,
     "        wheel_set_state2(pc->pWheel[i], cs->WheelAngle[i],\n"
     "                         cs->WheelAngularVelocity[i]);",
     "        wheel_set_state2(pc->pWheel[i], cs->WheelAngularVelocity[i],\n"
     "                         cs->WheelAngle[i]);"),
    ("pc-init-no-suspension", PCC,
     "        suspension_set_state(pc->pSuspension[i]);\n",
     ""),
    ("pc-init-no-body", PCC,
     "    rigidbody_set_state(pc->pBody, (const bVector4 *)&cs->Position,\n"
     "                        &cs->BodyMatrix, (const bVector4 *)&cs->Velocity,\n"
     "                        (const bVector4 *)&cs->AngularVelocity);\n",
     ""),

    # -- ResolveForces --------------------------------------------------------
    ("pc-resolve-no-counter", PCC,
     "    PhysicsCarResolveCounter++;\n",
     ""),
    ("pc-resolve-magic-half", PCC,
     "        downforce = downforce * 0.25f;",
     "        downforce = downforce * 0.5f;"),
    ("pc-resolve-downforce-always", PCC,
     "    else\n        downforce = 0.0f;\n",
     ""),
    ("pc-resolve-no-body", PCC,
     "    ((PhysicsVoidFn)e->fn)(vt_this(pc->pBody, e));",
     "    (void)e;"),
    ("pc-resolve-no-discarded-tick", PCC,
     "    (void)bGetTicker();\n",
     ""),
    ("pc-resolve-no-more-forces", PCC,
     "        suspension_resolve_more_forces(pc->pSuspension[i]);\n",
     ""),
    ("pc-resolve-no-jump-stabilizer", PCC,
     "    physicscar_jump_stabilizer(pc);\n",
     ""),
    ("pc-resolve-iterate-time", PCC,
     "    IterateTime = bGetTickerDifference(t0, bGetTicker());",
     "    IterateTime = 0.0f;"),
    ("pc-resolve-time-before-more", PCC,
     "    for (i = 0; i < 4; i++)\n"
     "        suspension_resolve_more_forces(pc->pSuspension[i]);\n"
     "    physicscar_jump_stabilizer(pc);\n"
     "    ResolveTime = bGetTickerDifference(t0, bGetTicker());\n",
     "    ResolveTime = bGetTickerDifference(t0, bGetTicker());\n"
     "    for (i = 0; i < 4; i++)\n"
     "        suspension_resolve_more_forces(pc->pSuspension[i]);\n"
     "    physicscar_jump_stabilizer(pc);\n"),

    # -- IterateForces --------------------------------------------------------
    ("pc-it-four-passes", PCC,
     "    for (pass = 0; pass < 5; pass++) {",
     "    for (pass = 0; pass < 4; pass++) {"),
    ("pc-it-yaw-sign", PCC,
     "            yaw = (yaw + s->RestPosition.x * f.y) - s->RestPosition.y * f.x;",
     "            yaw = (yaw + s->RestPosition.x * f.y) + s->RestPosition.y * f.x;"),
    ("pc-it-izz-multiplied", PCC,
     "        izz = 1.0f / pc->pBody->I_body_inv.v2.z;\n        yaw = yaw / izz;",
     "        izz = pc->pBody->I_body_inv.v2.z;\n        yaw = yaw * izz;"),
    ("pc-it-mass-inverse", PCC,
     "        a.x = acc.x / mass;",
     "        a.x = acc.x * pc->pBody->Mass_inv;"),
    ("pc-it-locked-modified", PCC,
     "            if (w->Slipping == 0 && w->BrakeLocked == 0) {",
     "            if (w->Slipping == 0) {"),
    ("pc-it-vy-sign", PCC,
     "                v.y = a.y + yaw * s->RestPosition.x;",
     "                v.y = a.y - yaw * s->RestPosition.x;"),
    ("pc-it-vx-sign", PCC,
     "                v.x = a.x - yaw * s->RestPosition.y;",
     "                v.x = a.x + yaw * s->RestPosition.y;"),
    ("pc-it-no-clutch-modify", PCC,
     "        drivetrain_modify_clutch_torque(pc->pDriveTrain);\n",
     ""),
    ("pc-it-no-clutch-guess", PCC,
     "    drivetrain_guess_clutch_torque(pc->pDriveTrain);\n",
     ""),
    ("pc-it-finalize-slider", PCC,
     "        wheel_finalize_ground_force(pc->pWheel[i], i);",
     "        wheel_finalize_ground_force(pc->pWheel[i], 0);"),
    ("pc-it-force-not-transposed", PCC,
     "    bTransposeMatrix(&rt, &pc->pBody->State.R);\n",
     "    rt = pc->pBody->State.R;\n"),

    # -- UpdateCar ------------------------------------------------------------
    ("pc-upd-pad-zeroed", PCC,
     "    o->pad = v->w;",
     "    o->pad = 0.0f;"),
    ("pc-upd-speed-squared", PCC,
     "    cs->VelocityMagnitude = sqrtf(len2(&rb->Velocity));",
     "    cs->VelocityMagnitude = len2(&rb->Velocity);"),
    ("pc-upd-matrix-valid", PCC,
     "    cs->MatrixValid = 0;",
     "    cs->MatrixValid = 1;"),
    ("pc-upd-angle-args-swapped", PCC,
     "        ee_trunc_w(cs->BodyMatrix.v0.x * 65536.0f),\n"
     "        ee_trunc_w(cs->BodyMatrix.v0.y * 65536.0f));",
     "        ee_trunc_w(cs->BodyMatrix.v0.y * 65536.0f),\n"
     "        ee_trunc_w(cs->BodyMatrix.v0.x * 65536.0f));"),
    ("pc-upd-forward-no-z", PCC,
     "                       + cs->Velocity.z * cs->BodyMatrix.v0.z;",
     "                       + cs->Velocity.z * cs->BodyMatrix.v0.y;"),
    ("pc-upd-steering", PCC,
     "    cs->SteeringAngle = pc->Mover.Driver->Steering;",
     "    cs->SteeringAngle = 0;"),
    ("pc-upd-height-unclamped", PCC,
     "            over = mrc - z;",
     "            over = 0.0f;"),
    ("pc-upd-noise-when-airborne", PCC,
     "                                ? w->RoadNoise : 0.0f;",
     "                                ? w->RoadNoise : w->RoadNoise;"),
    ("pc-upd-slip-y-from-x", PCC,
     "        cs->WheelSlip[i].y = w->Slip[1];",
     "        cs->WheelSlip[i].y = w->Slip[0];"),
    ("pc-upd-touching-always", PCC,
     "        carstate_set_wheel_touching_ground(cs, i, (int8_t)w->TouchingGround);",
     "        carstate_set_wheel_touching_ground(cs, i, 1);"),
    ("pc-upd-throttle-no-override", PCC,
     "    cs->Throttle      = e->Throttle * e->ThrottleOverride;",
     "    cs->Throttle      = e->Throttle;"),
    ("pc-upd-clutch-always", PCC,
     "    cs->ClutchEngaged = (d->CurrentClutchState == CLUTCH_ENGAGED);",
     "    cs->ClutchEngaged = 1;"),
    ("pc-upd-rpm-divided", PCC,
     "    cs->RPM           = e->State.w * PC_RADS_TO_RPM;",
     "    cs->RPM           = e->State.w / PC_RPM_TO_RADS;"),
    ("pc-upd-skid-left-from-right", PCC,
     "              fabsf(pc->pWheel[0]->CurrentSlip));",
     "              fabsf(pc->pWheel[1]->CurrentSlip));"),
    ("pc-upd-skid-uncapped", PCC,
     "    if (1.0f < l)\n        l = 1.0f;\n",
     ""),
    ("pc-upd-skid-reciprocal", PCC,
     "    l = l / SkidNormalize;",
     "    l = l * (1.0f / SkidNormalize);"),
    ("pc-upd-traction-half", PCC,
     "                         + pc->pWheel[3]->TractionUsage) * 0.25f;",
     "                         + pc->pWheel[3]->TractionUsage) * 0.5f;"),
    ("pc-upd-no-wheel-matrices", PCC,
     "    carstate_calculate_wheel_matrices(cs);\n",
     ""),
    ("pc-upd-no-geometry", PCC,
     "    carstate_calculate_geometry_position(pc->State);\n",
     ""),
    ("pc-upd-zforce", PCC,
     "        cs->WheelZForce[i] = w->ZForce;",
     "        cs->WheelZForce[i] = 0.0f;"),

    # -- the small methods ----------------------------------------------------
    ("pc-boost-draft-unflipped", PCC,
     "    pc->pAerodynamics->Draft = 1.0f - pc->pCar->DraftFactor;",
     "    pc->pAerodynamics->Draft = pc->pCar->DraftFactor;"),
    ("pc-boost-body", PCC,
     "    pc->pBody->CatchUpMultiplier = f;",
     "    pc->pBody->CatchUpMultiplier = 1.0f;"),
    ("pc-boost-wheels", PCC,
     "        pc->pWheel[i]->CatchupFrictionMultiplier = f;",
     "        pc->pWheel[i]->CatchupFrictionMultiplier = 1.0f;"),
    ("pc-boost-engine", PCC,
     "    pc->pEngine->CatchupTorqueMultiplier = f;",
     "    pc->pEngine->CatchupTorqueMultiplier = 1.0f;"),
    ("pc-friction-boost", PCC,
     "    pc->FrictionBoost = f;",
     "    pc->FrictionBoost = 1.0f;"),
    ("pc-jump-two-wheels-up", PCC,
     "    if (pc->pCar->State.nWheelsTouchingGround >= 2)",
     "    if (pc->pCar->State.nWheelsTouchingGround > 2)"),
    ("pc-jump-sign", PCC,
     "    k = -k;\n",
     ""),
    ("pc-jump-no-mass", PCC,
     "    k = pc->pBody->Mass\n        * graph_get_value",
     "    k = 1.0f\n        * graph_get_value"),
    ("pc-jump-w-lane", PCC,
     "    m.w = w->w * k;",
     "    m.w = 0.0f;"),

    # -- the tables -----------------------------------------------------------
    ("pc-vt-no-delta", PCC,
     "#define VEHICLE_DELTA ((int16_t)-(int)offsetof(PhysicsCar, Vehicle))",
     "#define VEHICLE_DELTA ((int16_t)0)"),
    ("pc-vt-base-aux", PCC,
     "    { VEHICLE_DELTA, 0, (VtFn)vt_PhysicsCar_ComputeAuxiliaries },",
     "    { VEHICLE_DELTA, 0, NULL },"),
    ("pc-vt-mover-no-snapshot", PCC,
     "    { 0, 0, (VtFn)carmover_do_snapshot },",
     "    { 0, 0, NULL },"),

    # -- Move: the pedals, the steering and the gearbox -------------------
    ("mv-tidy-brake-le", PCC,
     "    if (d->Brake < d->Throttle && d->EBrake < d->Throttle) {",
     "    if (d->Brake <= d->Throttle && d->EBrake < d->Throttle) {"),
    ("mv-tidy-either", PCC,
     "    if (d->Brake < d->Throttle && d->EBrake < d->Throttle) {",
     "    if (d->Brake < d->Throttle || d->EBrake < d->Throttle) {"),
    ("mv-tidy-brake-kept", PCC,
     "        if (d->Brake < 0.5f)" + NL + "            d->Brake = 0.0f;",
     "        if (d->Brake < 0.5f)" + NL + "            (void)0;"),
    ("mv-tidy-ebrake-kept", PCC,
     "        if (d->EBrake < 0.5f)" + NL + "            d->EBrake = 0.0f;",
     "        if (d->EBrake < 0.5f)" + NL + "            (void)0;"),
    ("mv-tidy-throttle-kept", PCC,
     "    } else if (d->Throttle < 0.5f) {" + NL + "        d->Throttle = 0.0f;",
     "    } else if (d->Throttle < 0.5f) {" + NL + "        (void)0;"),
    ("mv-steering-straight", PCC,
     "    ((SteeringSetSteeringFn)e->fn)(vt_this(pc->pSteering, e), d->Steering);",
     "    ((SteeringSetSteeringFn)e->fn)(vt_this(pc->pSteering, e), 0);"),
    ("mv-throttle-not-passed", PCC,
     "    pc->pEngine->Throttle = d->Throttle;" + NL
     + "    (void)drivetrain_set_sport_gear",
     "    (void)0;" + NL + "    (void)drivetrain_set_sport_gear"),
    ("mv-sport-gear-not-set", PCC,
     "    (void)drivetrain_set_sport_gear(pc->pDriveTrain, d->SportGear);",
     "    (void)d->SportGear;"),
    ("mv-nitro-not-lit", PCC,
     "        pc->pEngine->NitroFlag = 1;",
     "        (void)0;"),
    ("mv-nitro-timer-zero", PCC,
     "        pc->pEngine->NitroBoostTimer = (float)WorldTimer * PC_TICK;",
     "        pc->pEngine->NitroBoostTimer = 0.0f;"),
    ("mv-nitro-not-decremented", PCC,
     "    engine_decrement_nitro(pc->pEngine);",
     "    (void)0;"),
    ("mv-nitro-request-kept", PCC,
     "        d->NitroFlag = 0;",
     "        (void)0;"),
    ("mv-desired-gear-dropped", PCC,
     "        d->DesiredGear = drivetrain_set_desired_gear(pc->pDriveTrain, want);",
     "        (void)drivetrain_set_desired_gear(pc->pDriveTrain, want);"),
    ("mv-sport-gear-not-returned", PCC,
     "    d->SportGear = pc->pDriveTrain->SportGear;",
     "    (void)0;"),
    ("mv-no-calibrate", PCC,
     "    physicscar_set_boost(pc, pc->pCar->State.BoostFactor);" + NL
     + "    physicscar_calibrate(pc);",
     "    physicscar_set_boost(pc, pc->pCar->State.BoostFactor);"),
    ("mv-boost-factor-ignored", PCC,
     "    physicscar_set_boost(pc, pc->pCar->State.BoostFactor);",
     "    physicscar_set_boost(pc, 1.0f);"),

    # -- Move: damping, the NFS adjust and the burn-out gate ---------------
    ("mv-damp-both", PCC,
     "    if (PC_MOVE_DAMP_THROTTLE < d->Throttle" + NL + "        ||",
     "    if (PC_MOVE_DAMP_THROTTLE < d->Throttle" + NL + "        &&"),
    ("mv-damp-three-wheels", PCC,
     "        || (cs->nWheelsTouchingGround == 4",
     "        || (cs->nWheelsTouchingGround >= 3"),
    ("mv-damp-values-swapped", PCC,
     "        pc->pBody->MotionDamping = 0;" + NL + "    else" + NL
     + "        pc->pBody->MotionDamping = 1;",
     "        pc->pBody->MotionDamping = 1;" + NL + "    else" + NL
     + "        pc->pBody->MotionDamping = 0;"),
    ("mv-nfs-adjust-in-hp", PCC,
     "    if (cs->DriverMode == 0)" + NL + "        boost *= NFSAdjust;",
     "    if (cs->DriverMode != 0)" + NL + "        boost *= NFSAdjust;"),
    ("mv-bottom-out-kept", PCC,
     "        cs->WheelBottomOutMagnitude[i] = 0.0f;",
     "        (void)0;"),
    ("mv-bottom-out-three", PCC,
     "    for (i = 3; i >= 0; i--)",
     "    for (i = 3; i > 0; i--)"),
    ("mv-burnout-on-wheel", PCC,
     "        && !IsJoystickTypeWheel(((const RealDriver *)d)->Port))",
     "        && IsJoystickTypeWheel(((const RealDriver *)d)->Port))"),
    ("mv-burnout-for-ai", PCC,
     "    if (pc->pCar->TheControlMode == REAL_CONTROL" + NL,
     "    if (pc->pCar->TheControlMode != REAL_CONTROL" + NL),

    # -- the burn-out -------------------------------------------------------
    ("bo-time-not-counted", PCC,
     "        cs->BurnOutTime -= WorldTimeElapsed;",
     "        cs->BurnOutTime -= 0.0f;"),
    ("bo-yaw-cancel-signed", PCC,
     "        } else if (BurnOutYawCancel < fabsf(carstate_get_yaw(cs))) {",
     "        } else if (BurnOutYawCancel < carstate_get_yaw(cs)) {"),
    ("bo-cancel-any-wheel", PCC,
     "        } else if (w[0]->AppliedTorque < BurnOutCancelTorqueValue" + NL
     + "                   && w[1]",
     "        } else if (w[0]->AppliedTorque < BurnOutCancelTorqueValue" + NL
     + "                   || w[1]"),
    ("bo-allow-not-counted", PCC,
     "            cs->BurnOutAllow += WorldTimeElapsed;",
     "            cs->BurnOutAllow += 0.0f;"),
    ("bo-allow-not-reset", PCC,
     "            cs->BurnOutAllow = 0.0f;" + NL + "        }" + NL
     + "        return;",
     "            (void)0;" + NL + "        }" + NL + "        return;"),
    ("bo-running-restarts", PCC,
     "        }" + NL + "        return;" + NL + "    }" + NL + NL
     + "    if (cs->DriverMode != 1 || d->Steering != 0)",
     "        }" + NL + "    }" + NL + NL
     + "    if (cs->DriverMode != 1 || d->Steering != 0)"),
    ("bo-any-mode", PCC,
     "    if (cs->DriverMode != 1 || d->Steering != 0)",
     "    if (d->Steering != 0)"),
    ("bo-steering-ignored", PCC,
     "    if (cs->DriverMode != 1 || d->Steering != 0)",
     "    if (cs->DriverMode != 1)"),
    ("bo-when-stopped", PCC,
     "    if (!(0.0f < mph && mph < BurnOutMaxSpeed))",
     "    if (!(mph < BurnOutMaxSpeed))"),
    ("bo-any-speed", PCC,
     "    if (!(0.0f < mph && mph < BurnOutMaxSpeed))",
     "    if (!(0.0f < mph))"),
    ("bo-any-yaw", PCC,
     "    if (!(fabsf(carstate_get_yaw(cs)) < BurnOutYawMax))" + NL
     + "        return;",
     "    (void)0;"),
    ("bo-rear-w2-only", PCC,
     "    if (BurnOutTorqueValue < w[2]->AppliedTorque" + NL
     + "        || BurnOutTorqueValue < w[3]->AppliedTorque) {",
     "    if (BurnOutTorqueValue < w[2]->AppliedTorque) {"),
    ("bo-rear-pick-swapped", PCC,
     "        if (w[3]->AppliedTorque < w[2]->AppliedTorque) {",
     "        if (w[2]->AppliedTorque < w[3]->AppliedTorque) {"),
    ("bo-rear-tie-to-2", PCC,
     "        if (w[3]->AppliedTorque < w[2]->AppliedTorque) {",
     "        if (w[3]->AppliedTorque <= w[2]->AppliedTorque) {"),
    ("bo-rear-state", PCC,
     "            pick = 2;" + NL + "            cs->BurnOutState = 1;",
     "            pick = 2;" + NL + "            cs->BurnOutState = 2;"),
    ("bo-front-w0-only", PCC,
     "    } else if (BurnOutTorqueValue < w[0]->AppliedTorque" + NL
     + "               || BurnOutTorqueValue < w[1]->AppliedTorque) {",
     "    } else if (BurnOutTorqueValue < w[0]->AppliedTorque) {"),
    ("bo-front-pick-swapped", PCC,
     "        if (w[0]->AppliedTorque < w[1]->AppliedTorque) {",
     "        if (w[1]->AppliedTorque < w[0]->AppliedTorque) {"),
    ("bo-front-tie-to-1", PCC,
     "        if (w[0]->AppliedTorque < w[1]->AppliedTorque) {",
     "        if (w[0]->AppliedTorque <= w[1]->AppliedTorque) {"),
    ("bo-front-state", PCC,
     "            pick = 1;" + NL + "            cs->BurnOutState = 1;",
     "            pick = 1;" + NL + "            cs->BurnOutState = 2;"),
    ("bo-blinking-ignored", PCC,
     "    if (pick < 0 || car_is_blinking(pc->pCar))",
     "    if (pick < 0)"),
    ("bo-t-unclipped", PCC,
     "    if (1.0f < t)" + NL + "        t = 1.0f;" + NL
     + "    tr = BurnOutTractionValue;",
     "    tr = BurnOutTractionValue;"),
    ("bo-t-from-clip", PCC,
     "    t = (w[pick]->AppliedTorque - BurnOutTorqueValue)",
     "    t = (w[pick]->AppliedTorque - BurnOutTorqueValueClip)"),
    ("bo-slick-either", PCC,
     "    if (!(static_friction(w[2]) == 1.0f && static_friction(w[3]) == 1.0f))",
     "    if (!(static_friction(w[2]) == 1.0f || static_friction(w[3]) == 1.0f))"),
    ("bo-slick-factor", PCC,
     "        tr *= 1.25f;",
     "        tr *= 1.5f;"),
    ("bo-time-zero", PCC,
     "    cs->BurnOutTime = BurnOutMinTime;",
     "    cs->BurnOutTime = 0.0f;"),
    ("bo-traction-no-speed", PCC,
     "    cs->BurnOutTraction = tr + ((mph / BurnOutMaxSpeed) * (1.0f - t))",
     "    cs->BurnOutTraction = tr + ((1.0f) * (1.0f - t))"),
    ("bo-traction-t", PCC,
     "((mph / BurnOutMaxSpeed) * (1.0f - t))",
     "((mph / BurnOutMaxSpeed) * t)"),

    # -- Move: the yaw multiplier and the brakes ----------------------------
    ("mv-ym-strict", PCC,
     "    if (0.5f <= d->EBrake) {",
     "    if (0.5f < d->EBrake) {"),
    ("mv-ym-rate", PCC,
     "        ym -= dt * 20.0f;",
     "        ym -= dt * 10.0f;"),
    ("mv-ym-floor", PCC,
     "        if (ym < 0.5f)" + NL + "            ym = 0.5f;",
     "        if (ym < 0.0f)" + NL + "            ym = 0.0f;"),
    ("mv-ym-recovers-fast", PCC,
     "        ym += dt;",
     "        ym += dt * 2.0f;"),
    ("mv-ym-uncapped", PCC,
     "        if (1.0f < ym)" + NL + "            ym = 1.0f;",
     "        (void)0;"),
    ("mv-ym-not-stored", PCC,
     "    pc->YawControlMultiplier = ym;",
     "    (void)ym;"),
    ("mv-brake-racing-only", PCC,
     "        if (race_get_race_stage(pCurrentRace) == RACE_STAGE_RACING" + NL
     + "            || (pc->BrakeStanding && i < 2))",
     "        if (race_get_race_stage(pCurrentRace) == RACE_STAGE_RACING)"),
    ("mv-brake-stand-all-four", PCC,
     "            || (pc->BrakeStanding && i < 2))",
     "            || pc->BrakeStanding)"),
    ("mv-brake-no-settings", PCC,
     "            w->Brake = d->Brake * BrakeSettings[i];",
     "            w->Brake = d->Brake;"),
    ("mv-brake-kept-off", PCC,
     "        else" + NL + "            w->Brake = 0.0f;",
     "        else" + NL + "            (void)0;"),
    ("mv-ebrake-no-settings", PCC,
     "        eb = d->EBrake * EBrakeSettings[i];",
     "        eb = d->EBrake;"),
    ("mv-ebrake-nfs-in-hp", PCC,
     "        if (cs->DriverMode == 0) {" + NL
     + "            if (PC_EBRAKE_KNEE < eb)",
     "        if (cs->DriverMode != 0) {" + NL
     + "            if (PC_EBRAKE_KNEE < eb)"),
    ("mv-ebrake-nfs-no-knee", PCC,
     "            if (PC_EBRAKE_KNEE < eb)" + NL
     + "                eb += PC_EBRAKE_NFS;",
     "            eb += PC_EBRAKE_NFS;"),
    ("mv-ebrake-hp-any-yaw", PCC,
     "        } else if (PC_EBRAKE_KNEE < eb" + NL
     + "                   && PC_EBRAKE_YAW < fabsf(carstate_get_yaw(cs))" + NL
     + "                   && mph < 80.0f) {",
     "        } else if (PC_EBRAKE_KNEE < eb" + NL
     + "                   && mph < 80.0f) {"),
    ("mv-ebrake-hp-any-speed", PCC,
     "                   && PC_EBRAKE_YAW < fabsf(carstate_get_yaw(cs))" + NL
     + "                   && mph < 80.0f) {",
     "                   && PC_EBRAKE_YAW < fabsf(carstate_get_yaw(cs))) {"),
    ("mv-ebrake-hp-add", PCC,
     "            eb += 0.5f;",
     "            eb += 0.7f;"),
    ("mv-ebrake-unshaped", PCC,
     "        w->EBrake = eb;",
     "        w->EBrake = d->EBrake;"),

    # -- Move: the traction boosts -----------------------------------------
    ("mv-yfb-at-wheel-3", PCC,
     "        if (i == 2) {" + NL + "            float tilt",
     "        if (i == 3) {" + NL + "            float tilt"),
    ("mv-yfb-ym-ignored", PCC,
     "            boost *= ym * (r - 1.0f) + 1.0f;",
     "            boost *= r;"),
    ("mv-yfb-front-ebrake", PCC,
     "            float eb2   = pc->pWheel[2]->EBrake;",
     "            float eb2   = pc->pWheel[0]->EBrake;"),
    ("mv-yfb-forward-speed", PCC,
     "            float speed = cs->VelocityMagnitude;",
     "            float speed = cs->ForwardSpeed;"),
    ("mv-yfb-controls-swapped", PCC,
     "ctl->YawControl," + NL + "                                           ctl->YawControlNFS,",
     "ctl->YawControlNFS," + NL + "                                           ctl->YawControl,"),
    ("mv-yfb-no-collision-boost", PCC,
     "            float pcb   = car_get_post_collision_yaw_control_boost(car);",
     "            float pcb   = 0.0f;"),
    ("mv-tb-burnout-front-pair", PCC,
     "        if ((i == 0 || i == 3) ? cs->BurnOutState == 1",
     "        if ((i == 0 || i == 1) ? cs->BurnOutState == 1"),
    ("mv-tb-burnout-states-swapped", PCC,
     "? cs->BurnOutState == 1" + NL
     + "                               : cs->BurnOutState == 2)",
     "? cs->BurnOutState == 2" + NL
     + "                               : cs->BurnOutState == 1)"),
    ("mv-tb-burnout-no-traction", PCC,
     "            w->TractionBoost = boost * cs->BurnOutTraction;",
     "            w->TractionBoost = boost;"),
    ("mv-blown-per-wheel", PCC,
     "        if (car->BlownTireBits != 0)" + NL
     + "            w->TractionBoost *= PC_BLOWN_TRACTION;",
     "        if (car->BlownTireBits & (1 << i))" + NL
     + "            w->TractionBoost *= PC_BLOWN_TRACTION;"),
    ("mv-blown-and-override", PCC,
     "        else if (car->fTractionBoostOverride != 0.0f)",
     "        if (car->fTractionBoostOverride != 0.0f)"),
    ("mv-override-ignored", PCC,
     "            w->TractionBoost *= car->fTractionBoostOverride;",
     "            (void)0;"),
    ("mv-damage-override-when-blown", PCC,
     "    if (car->fDamageBoostOverride != 0.0f && car->BlownTireBits == 0)",
     "    if (car->fDamageBoostOverride != 0.0f)"),
    ("mv-damage-override-ignored", PCC,
     "        physicscar_set_boost(pc, car->fDamageBoostOverride);",
     "        (void)0;"),
    ("mv-aero-no-throttle", PCC,
     "    pc->pAerodynamics->Throttle = d->Throttle;",
     "    pc->pAerodynamics->Throttle = 0.0f;"),
    ("mv-ground-effect-half", PCC,
     "        (float)cs->nWheelsTouchingGround * 0.25f;",
     "        (float)cs->nWheelsTouchingGround * 0.5f;"),

    # -- Move: MaxMomentZ, the limiter, the sub-steps ----------------------
    ("mv-mmz-mode-swapped", PCC,
     "    if (cs->DriverMode == 0) {" + NL
     + "        body->MaxMomentZ = ctl->MaxZMomentAcc;",
     "    if (cs->DriverMode != 0) {" + NL
     + "        body->MaxMomentZ = ctl->MaxZMomentAcc;"),
    ("mv-mmz-extreme-overridden", PCC,
     "        if (m == 0.0f) {",
     "        if (1) {"),
    ("mv-mmz-with-spin", PCC,
     "            if (yaw * body->State.L.z < 0.0f && PC_EXTREME_YAW < fabsf(yaw))",
     "            if (yaw * body->State.L.z > 0.0f && PC_EXTREME_YAW < fabsf(yaw))"),
    ("mv-mmz-any-yaw", PCC,
     "            if (yaw * body->State.L.z < 0.0f && PC_EXTREME_YAW < fabsf(yaw))",
     "            if (yaw * body->State.L.z < 0.0f)"),
    ("mv-mmz-20", PCC,
     "                m = 20.0f;",
     "                m = 10.0f;"),
    ("mv-limiter-no-damage", PCC,
     "        k = 1.0f - bodydamage_get_visible_total_damage(",
     "        k = 1.0f - 0.0f * bodydamage_get_visible_total_damage("),
    ("mv-limiter-on-nitro", PCC,
     "        body->SpeedLimiter = 0.0f;" + NL
     + "    else if (car->BlownTireBits != 0)",
     "        body->SpeedLimiter = ctl->SpeedLimiter;" + NL
     + "    else if (car->BlownTireBits != 0)"),
    ("mv-limiter-blown-first", PCC,
     "    if (pc->pEngine->NitroFlag)" + NL
     + "        body->SpeedLimiter = 0.0f;" + NL
     + "    else if (car->BlownTireBits != 0)" + NL
     + "        body->SpeedLimiter = 60.0f;",
     "    if (car->BlownTireBits != 0)" + NL
     + "        body->SpeedLimiter = 60.0f;" + NL
     + "    else if (pc->pEngine->NitroFlag)" + NL
     + "        body->SpeedLimiter = 0.0f;"),
    ("mv-limiter-blown-80", PCC,
     "        body->SpeedLimiter = 60.0f;",
     "        body->SpeedLimiter = 80.0f;"),
    ("mv-limiter-k-ignored", PCC,
     "        body->SpeedLimiter = ctl->SpeedLimiter * k;",
     "        body->SpeedLimiter = ctl->SpeedLimiter;"),
    ("mv-n-no-extra-step", PCC,
     "    n = (int32_t)((uint32_t)ee_trunc_w(dt / MaximumTimeStep) + 1u);",
     "    n = (int32_t)((uint32_t)ee_trunc_w(dt / MaximumTimeStep));"),
    ("mv-n-ceil", PCC,
     "    n = (int32_t)((uint32_t)ee_trunc_w(dt / MaximumTimeStep) + 1u);",
     "    n = (int32_t)((uint32_t)ee_trunc_w(ceilf(dt / MaximumTimeStep)));"),
    ("mv-step-max", PCC,
     "    step = dt / (float)n;",
     "    step = MaximumTimeStep;"),
    ("mv-dyno-x-only-with-dyno", PCC,
     "        if (SpeedDebugInfo != 0" + NL
     + "            || race_get_race_stage(pCurrentRace) != RACE_STAGE_RACING) {",
     "        if (SpeedDebugInfo != 0) {"),
    ("mv-dyno-r-not-saved", PCC,
     "            SpeedDebugR = pc->pBody->State.R;",
     "            (void)0;"),
    ("mv-hack-whole-dt", PCC,
     "        gUglyTimestepHack = step;",
     "        gUglyTimestepHack = dt;"),
    ("mv-no-orthonormalize", PCC,
     "        eOrthonormalizeMatrix(&pc->pBody->State.R, &pc->pBody->State.R);",
     "        (void)0;"),
    ("mv-brake-stand-prerace-only", PCC,
     "        if (stage != RACE_STAGE_RACING)" + NL
     + "            move_brake_stand(pc, stage);",
     "        if (stage == RACE_STAGE_PRERACE)" + NL
     + "            move_brake_stand(pc, stage);"),
    ("mv-dyno-idle-dropped", PCC,
     "        else" + NL + "            move_speed_debug_idle();",
     "        else" + NL + "            (void)0;"),
    ("mv-dyno-60-not-counted", PCC,
     "            SpeedDebugDisplayTime60 -= WorldTimeElapsed;",
     "            (void)0;"),
    ("mv-dyno-100-at-zero", PCC,
     "        if (0.0f < SpeedDebugDisplayTime100)",
     "        if (0.0f <= SpeedDebugDisplayTime100)"),
    ("mv-dyno-qm-not-counted", PCC,
     "            SpeedDebugDisplayTimeQM -= WorldTimeElapsed;",
     "            (void)0;"),
    ("mv-update-car-step", PCC,
     "    physicscar_update_car(pc, dt);",
     "    physicscar_update_car(pc, step);"),
    ("mv-skids-always", PCC,
     "    if (car_should_visual_effects_be_generated(pc->pCar))" + NL,
     "    if (1)" + NL),
    ("mv-skids-step", PCC,
     "            wheel_maybe_make_skids(pc->pWheel[i], dt);",
     "            wheel_maybe_make_skids(pc->pWheel[i], step);"),
    ("mv-returns-step", PCC,
     "    (void)bGetTickerDifference(t0, bGetTicker());" + NL + "    return dt;",
     "    (void)bGetTickerDifference(t0, bGetTicker());" + NL + "    return step;"),

    # -- the brake-stand ------------------------------------------------------
    ("bs-countdown-only", PCC,
     "    if (stage >= RACE_STAGE_PRERACE) {",
     "    if (stage > RACE_STAGE_PRERACE) {"),
    ("bs-timeout-ignored", PCC,
     "              * PC_TICK)" + NL + "            pc->BrakeStanding = 1;",
     "              * PC_TICK)" + NL + "            (void)0;"),
    ("bs-held-lurches-again", PCC,
     "            if (pc->ThrottleReleased && pc->LurchsLeft) {",
     "            if (pc->LurchsLeft) {"),
    ("bs-lurches-unlimited", PCC,
     "            if (pc->ThrottleReleased && pc->LurchsLeft) {",
     "            if (pc->ThrottleReleased) {"),
    ("bs-lo-swapped", PCC,
     "                float lo = pc->LurchsLeft == 2 ? 0.25f : 0.5f;",
     "                float lo = pc->LurchsLeft == 2 ? 0.5f : 0.25f;"),
    ("bs-timer-without-lo", PCC,
     "                    (uint32_t)ee_trunc_w((r + lo) * 4000.0f);",
     "                    (uint32_t)ee_trunc_w(r * 4000.0f);"),
    ("bs-lurch-not-counted", PCC,
     "                pc->LurchsLeft--;",
     "                (void)0;"),
    ("bs-still-standing", PCC,
     "                pc->BrakeStanding = 0;",
     "                (void)0;"),
    ("bs-release-kept", PCC,
     "                pc->ThrottleReleased = 0;",
     "                (void)0;"),
    ("bs-start-zero", PCC,
     "                pc->BrakeStandTimerStart.PackedTime =" + NL
     + "                    (uint32_t)ee_trunc_w((float)WorldTimer * PC_TICK" + NL
     + "                                         * 4000.0f);",
     "                pc->BrakeStandTimerStart.PackedTime = 0;"),
    ("bs-release-not-noted", PCC,
     "            pc->BrakeStanding = 1;" + NL
     + "            pc->ThrottleReleased = 1;",
     "            pc->BrakeStanding = 1;"),
    ("bs-p-kept", PCC,
     "    if (pc->BrakeStanding) {" + NL
     + "        // Three words stored and a quad loaded: the port zeroes the fourth." + NL
     + "        bVector4 zero = { 0.0f, 0.0f, 0.0f, 0.0f };" + NL
     + "        pc->pBody->State.P = zero;",
     "    if (pc->BrakeStanding) {" + NL
     + "        bVector4 zero = { 0.0f, 0.0f, 0.0f, 0.0f };" + NL
     + "        (void)zero;"),

    # -- the dyno -------------------------------------------------------------
    ("sd-never-restarts", PCC,
     "    if (mph < PC_DYNO_STOPPED) {",
     "    if (mph < 0.0f) {"),
    ("sd-restart-keeps-measure", PCC,
     "        SpeedDebugQMMeasure = 0.0f;" + NL
     + "        SpeedDebugQMTime = -1.0f;",
     "        SpeedDebugQMTime = -1.0f;"),
    ("sd-restart-start-zero", PCC,
     "        SpeedDebugStartTime = now;",
     "        SpeedDebugStartTime = 0.0f;"),
    ("sd-60-restamped", PCC,
     "    if (SpeedDebug060Time < 0.0f && 60.0f < mph) {",
     "    if (60.0f < mph) {"),
    ("sd-60-display", PCC,
     "        SpeedDebugDisplayTime60 = 30.0f;",
     "        SpeedDebugDisplayTime60 = 20.0f;"),
    ("sd-100-at-60", PCC,
     "    if (SpeedDebug0100Time < 0.0f && 100.0f < mph) {",
     "    if (SpeedDebug0100Time < 0.0f && 60.0f < mph) {"),
    ("sd-qm-after-done", PCC,
     "    if (SpeedDebugQMTime < 0.0f) {",
     "    if (1) {"),
    ("sd-qm-speed", PCC,
     "            SpeedDebugQMSpeed = mph;",
     "            SpeedDebugQMSpeed = 0.0f;"),
    ("sd-height-not-kept", PCC,
     "    SpeedDebugX.z = body->State.X.z;",
     "    (void)0;"),
    ("sd-not-put-back", PCC,
     "    body->State.X = SpeedDebugX;",
     "    (void)0;"),
    ("sd-idle-start-zero", PCC,
     "    SpeedDebugStartTime = (float)WorldTimer * PC_TICK;" + NL
     + "    SpeedDebug0100Time = 1.0f;",
     "    SpeedDebugStartTime = 0.0f;" + NL
     + "    SpeedDebug0100Time = 1.0f;"),
    ("sd-idle-qm-waiting", PCC,
     "    SpeedDebugQMTime = 1.0f;",
     "    SpeedDebugQMTime = -1.0f;"),

    # -- the stand-in modules: joystick, damage, race ------------------------
    ("joy-no-22", JOYC,
     "    case 22:" + NL,
     ""),
    ("joy-port-0", JOYC,
     "    return CurrentJoystickTypes[port];",
     "    return CurrentJoystickTypes[0];"),
    ("dmg-always-enabled", CDMC,
     "    if (RaceParametersDamageEnabled == 0)" + NL + "        return 0.0f;",
     "    (void)0;"),
    ("dmg-enabled-is-one", CDMC,
     "    if (RaceParametersDamageEnabled == 0)",
     "    if (RaceParametersDamageEnabled != 1)"),
    ("dmg-scale", CDMC,
     "CompressedTotalDamage * 0.000244140625f;",
     "CompressedTotalDamage * 0.00048828125f;"),
    ("dmg-signed-half", CDMC,
     "    return (float)(int32_t)b->CompressedTotalDamage",
     "    return (float)(int16_t)b->CompressedTotalDamage"),
    ("race-stage-second-word", RACEC,
     "    return *(const eRaceStage *)(const void *)r;",
     "    return ((const eRaceStage *)(const void *)r)[1];"),
]

# Each of these changes nothing the shipped code can see, for the reason
# beside it, checked against the image.
EQUIVALENT = {
    "pc-dtor-vehicle-vt-not-restored":
        "~PhysicsSystem stores PHYSICSSYSTEM_VTABLE on entry, and nothing "
        "between the steering's destructor and the aerodynamics' delete "
        "reads Vehicle._vtable: the store it drops is overwritten unread.",
    "pc-brake-rear-in-float":
        "GetBrakeSettings' rear arm is fptodp/dpsub/dpadd/dptofp; "
        "(1 - b) + (1 - b) in float rounds the same for every one of the "
        "2^32 floats, NaNs aside (an exhaustive run, not a sample).",
    "pc-resolve-no-body":
        "RigidBody::ResolveForces, 0x00193c68, is `jr ra ; nop`.",
    "pc-resolve-time-before-more":
        "ResolveTime and IterateTime are written and never read anywhere "
        "in the image (the only references are the swc1s at 0x00136d98 "
        "and 0x00136de8), and the stand-in ticker counts reads, not what "
        "they are stored into.",
    "pc-it-finalize-slider":
        "Wheel::FinalizeGroundForce passes the wheel number on to "
        "SetSliderValue__Fifff, 0x00199c30, which is empty.",
    "mv-update-car-step":
        "UpdateCar__10PhysicsCarf never reads $f12; physicscar_update_car "
        "is `(void)dt`, so the step and the frame's dt are the same call.",
}

write_source = hostbuild.write_source


def mutate_pass():
    ctis = cti_records()
    base = model(ctis)
    caught = 0
    survived = []
    equivalent = []
    missing = []

    for m in MUTATIONS:
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
            write_source(path, new)
            with tempfile.TemporaryDirectory() as tmp:
                try:
                    exe = build_harness(tmp, ctis)
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
                write_source(path, text)
            except OSError:
                sys.exit("could not restore %s -- it still holds the "
                         "mutation %s. Put the original line back before "
                         "trusting anything printed above." % (rel, name))

    real = [m for m in MUTATIONS if m[0] not in missing]
    holes = [s for s in survived if s not in EQUIVALENT]
    # An entry whose mutant was caught is a wrong reason, not a spare one.
    stale = [n for n in EQUIVALENT
             if n not in equivalent and n not in missing]
    if missing:
        print("%d PATTERN NOT FOUND -- the tally above is over %d of %d"
              % (len(missing), len(real), len(MUTATIONS)))
    print("%d mutations, %d caught, %d equivalent, %d unexplained"
          % (len(real), caught, len(equivalent), len(holes)))
    for name in stale:
        ran = any(m[0] == name for m in MUTATIONS)
        print("  listed as equivalent but %s: %s"
              % ("caught" if ran else "names no mutation", name))
    return 1 if (holes or missing or stale) else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mutate", action="store_true")
    ap.add_argument("--dump", metavar="PREFIX")
    args = ap.parse_args()

    probs = layout_problems()
    for p in probs:
        print("layout: " + p)
    if probs:
        sys.exit(1)

    if args.mutate:
        sys.exit(mutate_pass())

    ctis = cti_records()
    lines = model(ctis)
    with tempfile.TemporaryDirectory() as tmp:
        exe = build_harness(tmp, ctis)
        out = Path(tmp) / "harness.txt"
        run_harness(exe, out)
        harness = out.read_text().splitlines()

    if args.dump:
        d = Path(args.dump)
        d.parent.mkdir(parents=True, exist_ok=True)
        d.with_suffix(".model").write_text(NL.join(lines) + NL)
        d.with_suffix(".harness").write_text(NL.join(harness) + NL)

    n = diff(lines, harness)
    print("%d scenarios, %d lines, %d differ"
          % (len(SCENARIOS), len(harness), n))
    sys.exit(1 if n else 0)


if __name__ == "__main__":
    main()
