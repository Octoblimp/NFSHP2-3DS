#!/usr/bin/env python3
"""Cross-check mellowmover -- MellowMover.obj minus its two DoSnapshots --
against the image itself, run in mipsemu.

    3DS Files/source/mellowmover.{c,h}   Mellovator: the constructor and
                                         destructor, Calibrate, the state
                                         accessors, GetDerivative,
                                         ComputeAuxiliaries and its gearbox,
                                         the suspension, ResolveForces,
                                         BottomOut and the one-liners.
                                         MellowMover: the constructor and
                                         destructor, the three tables,
                                         Calibrate, InitializeStateFromCar,
                                         Move, UpdateCar, ComputeAuxiliaries,
                                         ResolveForces, SetBoost and
                                         JumpStabilizer. The static
                                         initialiser.

MellowMover is the car the game drives when it is not driving it hard: the
AI's and the traffic's, and the player's between races. It is a body, a
Mellovator -- one component that is four wheel speeds, four springs and a
tyre model -- and an Aerodynamics, in a PhysicsSystem; the four Wheels are
there to be drawn and skidded with, and nothing integrates them.

The oracle and the machinery are physicscar_check's, imported rather than
copied: the header parse and the check of every offset against mdebug, the
generated dump functions and field tables, the CTI records, the emulator's
stubs -- the allocator, the ticker, the terrain plane, the skids -- and its
hooks, and the diff. See physicscar_check for what each one is and why.
What is MellowMover's is here: the objects and their labels, the
scenarios, and the direct calls.

**Scenarios** are frames of Move through the mover's own table, as Car
calls it, each after the constructor and each ending in the destructor
through the same table with the delete bit set, so the pools are seen to
come back empty. Every object the mover owns is printed after each frame.
The direct calls reach what a frame does not: every gear the box can be
asked for from every gear it can be in, the brake locks at their edges,
GetDerivative's idle arm and boost arms, BottomOut against a hub going
each way, JumpStabilizer with none, one and two wheels down and the car
upright or not -- and falling straight down, where the heading has no
length and the VU divides by zero the EE's way -- SetBoost either side of
30 mph, and the one-line accessors.

**Uninitialised stack.** JumpStabilizer levels the side axis against `u`,
a quad of which it stores three words (0x00206f78 .. 0x00206f88); the
fourth reaches the moment's w lane. The port zeroes it, and the model
zeroes sp+60 on the `lqc2` that reads it.

    python tools/mellowmover_check.py
    python tools/mellowmover_check.py --mutate
    python tools/mellowmover_check.py --dump out/mellowmover
"""
import argparse
import math
import os
import re
import struct
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hostbuild
import physicscar_check as pcc
from mipsemu import M32, f32, s32
from physicscar_check import LAYOUT, OFF, fb, hexw

ROOT = pcc.ROOT
NL = pcc.NL
HARNESS = ROOT / "tools" / "src" / "mellowmover_test.c"
MMC = "3DS Files/source/mellowmover.c"

SOURCES_PORT = [MMC] + pcc.SOURCES_PORT

# ================================================================ the layout

pcc.HEADERS["Mellovator"] = "mellowmover.h"
pcc.HEADERS["MellowMover"] = "mellowmover.h"
for _t in ("Mellovator", "MellowMover"):
    LAYOUT[_t] = pcc.parse(_t)
pcc.UNNAMED.update({("MellowMover", "Mover"), ("MellowMover", "Vehicle")})

# Nested records first.
DUMPED = ["Table", "SkidMaker", "CarMover", "PhysicsSystem", "Mellovator",
          "MellowMover", "RigidBody", "Wheel", "Aerodynamics", "CarState"]


def layout_problems():
    out = []
    for t in DUMPED + ["RigidBodyState"]:
        out.extend(pcc.check_layout(LAYOUT[t]))
    return out


# `#define MV_NAME  <literal>f  // gp-N  <hex>`: the literal, the word the
# comment claims and the word in the image's pool must be one number. Two
# of them were not -- a BAM_TO_RAD typed a digit short and a HALF_PI taken
# for the nearest float -- and each moved bSin's truncated angle by one.
LIT4 = re.compile(r"#define\s+(MV_\w+)\s+([-0-9.eE+]+)f\s*//\s*gp-(\d+)\s+"
                  r"([0-9a-f]{8})")


def constant_problems():
    from mipsemu import Emu
    e = Emu(ieee=True)
    gp = e.reg[28]
    out = []
    text = (ROOT / MMC).read_text(encoding="utf-8")
    found = LIT4.findall(text)
    if not found:
        out.append("no MV_ constants found in %s" % MMC)
    for name, lit, off, hx in found:
        lit_w = struct.unpack(">I", struct.pack(">f", float(lit)))[0]
        img_w = struct.unpack("<I", bytes(e.read(gp - int(off), 4)))[0]
        if not lit_w == int(hx, 16) == img_w:
            out.append("%s: literal %08x, comment %s, image gp-%s %08x"
                       % (name, lit_w, hx, off, img_w))
    return out


# ============================================================ the scenarios

IDENT = pcc.IDENT
YAW = pcc.YAW
TILT = pcc.TILT
Z3 = (0.0, 0.0, 0.0)
Z4 = (0.0, 0.0, 0.0, 0.0)
# Rolled about x until the up axis's z is 0.1 exactly -- not upright, since
# JumpStabilizer's test is strict.
ROLLED = [1.0, 0.0, 0.0,
          0.0, 0.1, f32(0.99 ** 0.5),
          0.0, -f32(0.99 ** 0.5), 0.1]

SCEN_FIELDS = [
    # name, C type, default
    ("car", "int", 0),              # index into physicscar_check.CARS
    ("pos", "f3", (0.0, 0.0, 0.4375)),
    ("mat", "f9", IDENT),
    ("vel", "f3", Z3),
    ("avel", "f3", Z3),
    ("wa", "f", 0.0),               # every WheelAngle
    ("ww", "f4", Z4),               # WheelAngularVelocity
    ("fwd", "f", 0.0),              # ForwardSpeed
    ("ntouch", "int", 4),           # the first n WheelTouchingGround, and n
    ("thr", "f", 0.0),              # the driver's
    ("brk", "f", 0.0),
    ("steer", "int", 0),
    ("dgear", "int", -1),           # AUTOMATIC
    ("draft", "f", 0.0),            # Car.DraftFactor
    ("render", "int", 1),           # Car.RenderingEnabled
    ("dtype", "int", 0),            # the DriverInfo's TheDriverType
    ("newcal", "int", 1),           # UseNewSuspensionCalibration
    ("dmode", "int", 0),            # CarState.DriverMode
    ("boostf", "f", 1.0),           # CarState.BoostFactor
    ("dt", "f", 1.0 / 60.0),
    ("steps", "int", 3),
    # 1: the mover is given a CarState of its own, "cs2", the Car's copied
    # with ForwardSpeed `fwd2`, so each read shows whose state it took.
    ("apart", "int", 0),
    ("fwd2", "f", 0.0),
]


class Scen(object):
    def __init__(self, name, **kw):
        self.name = name
        for k, _, d in SCEN_FIELDS:
            setattr(self, k, kw.pop(k, d))
        assert not kw, kw


# Upside down: the up axis points at the ground, and no wheel's cosine
# reaches 0.001.
INVERTED = [1.0, 0.0, 0.0,
            0.0, -1.0, 0.0,
            0.0, 0.0, -1.0]
# TILT turned half way round about the world's z: the side axis's y is
# negative, which the hold's bank term takes the absolute value of.
TILT_BACK = [-x if i % 3 < 2 else x for i, x in enumerate(TILT)]

# The records the scenarios drive. physicscar_check's four, then CAR 34, the
# first of the five shipped cars whose two final drives differ, then two
# made from CAR 0 by changing a field no shipped record varies: a centre of
# gravity off the centreline (no record has one), and a droop stop far
# enough down that the -100 a wheel on its side is given is not the only
# answer below it.
CTI_COG_Y = 276                    # CenterOfGravity.y
CTI_DROOP = (584, 616)             # Suspension[i].BumpStop[1]
C34, C0_COGY, C0_DROOP = 4, 5, 6


def cti_records():
    recs = pcc.cti_records() + pcc.cti_records([34])
    cogy = bytearray(recs[0])
    struct.pack_into("<f", cogy, CTI_COG_Y, 0.0625)
    droop = bytearray(recs[0])
    for o in CTI_DROOP:
        struct.pack_into("<f", droop, o, -2.0)
    return recs + [bytes(cogy), bytes(droop)]


# A Corvette on the plane at 15 m/s, yawed 36.87 degrees, its wheels
# turning with the ground and the throttle part open.
MOVING = dict(pos=(4.5, -2.25, 0.5), mat=YAW, vel=(12.0, 9.0, 0.0),
              avel=(0.0, 0.0, 0.25), wa=0.5, ww=(46.5, 46.5, 45.0, 45.0),
              fwd=15.0, thr=0.625)


def mv(**kw):
    d = dict(MOVING)
    d.update(kw)
    return d


SCENARIOS = [
    Scen("c0-rest"),
    Scen("c0-move", **mv()),
    Scen("c33-move", **mv(car=1)),
    Scen("c65-move", **mv(car=2, pos=(4.5, -2.25, 0.55))),
    Scen("c1-move", **mv(car=3)),
    Scen("c33-brake", **mv(car=1, thr=0.0, brk=0.5)),
    # A hard brake under 30 rad/s locks: the wheels stop dead, and a
    # locked wheel holds against the slope.
    Scen("c65-lock", **mv(car=2, pos=(4.5, -2.25, 0.55), vel=(4.0, 3.0, 0.0),
                          ww=(15.0, 15.0, 14.0, 14.0), fwd=5.0, thr=0.0,
                          brk=1.0)),
    # Stopped on the slope on the brakes: the hold without a lock.
    Scen("c0-hold", brk=0.5),
    Scen("c0-hold-tilt", mat=TILT, pos=(0.0, 0.0, 0.5), brk=0.6),
    # Off the ground, spinning: the jump stabiliser's three moments, then
    # the first alone.
    Scen("c0-air", **mv(pos=(0.0, 0.0, 2.5), avel=(1.25, 0.5, 0.75),
                        vel=(10.0, 0.0, -1.0), ntouch=0)),
    Scen("c0-air-one", **mv(pos=(0.0, 0.0, 2.5), avel=(1.25, 0.5, 0.75),
                            vel=(10.0, 0.0, -1.0), ntouch=1)),
    # Falling straight down: no heading across the ground, so the
    # normalise divides by zero.
    Scen("c0-fall", pos=(0.0, 0.0, 2.5), vel=(0.0, 0.0, -3.0),
         avel=(0.25, 0.0, 0.5), ntouch=0),
    Scen("c0-rolled", pos=(0.0, 0.0, 2.5), mat=ROLLED, vel=(5.0, 1.0, 0.0),
         ntouch=0),
    # The box: fast enough in first to shift up, reverse, and a fixed gear
    # the box leaves alone.
    Scen("c1-shift-up", **mv(car=3, ww=(90.0, 90.0, 88.0, 88.0), thr=1.0,
                             vel=(21.6, 16.2, 0.0), fwd=27.0)),
    Scen("c0-reverse", **mv(dgear=0, vel=(-2.4, -1.8, 0.0),
                            ww=(-9.0, -9.0, -9.0, -9.0), fwd=-3.0, thr=0.5)),
    Scen("c0-fixed-gear", **mv(dgear=4)),
    # Boost above 1, and a mode-1 driver above 30 mph.
    Scen("c0-boost", **mv(boostf=1.5)),
    Scen("c1-hp-fast", **mv(car=3, dmode=1, fwd=20.0, boostf=1.25)),
    Scen("c1-hp-slow", **mv(car=3, dmode=1, fwd=13.0, boostf=1.25)),
    # Dropped onto the stops: bottom-out.
    Scen("c0-bottom", pos=(0.0, 0.0, 0.3), vel=(0.0, 0.0, -2.0)),
    Scen("c33-bottom-roll", car=1, pos=(0.0, 0.0, 0.3), vel=(1.0, 0.0, -1.5),
         avel=(0.75, -0.5, 0.0)),
    # The rears spun far past the ground: the friction circle, the slide.
    Scen("c0-spin", **mv(ww=(46.5, 46.5, 20000.0, 20000.0), steps=1)),
    Scen("c0-steer", **mv(steer=0x0800)),
    Scen("c0-steer-left", **mv(steer=0xf400, ntouch=2)),
    Scen("c65-oldcal", **mv(car=2, newcal=0, pos=(4.5, -2.25, 0.55))),
    # The firetruck's centre of gravity is at x = 0, so the old calibration
    # needs a car whose is not.
    Scen("c0-oldcal", **mv(newcal=0)),
    # The drive and the engine speed take the second final drive.
    Scen("c34-move", **mv(car=C34)),
    Scen("c0-cogy-move", **mv(car=C0_COGY)),
    # On its side, low enough that one rear wheel is between its stops
    # and the front beside it is past the upper one; the cosine is 0.084.
    Scen("c0-rolled-down", pos=(0.0, 0.0, 0.72), mat=ROLLED, ntouch=1),
    # Upside down, with the droop stop below -1: the -100 sets the answer.
    Scen("c0-droop-inverted", car=C0_DROOP, pos=(0.0, 0.0, 1.0),
         mat=INVERTED, ntouch=0, steps=1),
    Scen("c0-tilt-back", mat=TILT_BACK, pos=(0.0, 0.0, 0.5)),
    Scen("c0-ww-apart", **mv(ww=(46.5, 46.0, 45.5, 44.75))),
    # A frame shorter than the suspension's floor on its step, which is
    # the only way under it: Move sets the step before every integration.
    Scen("c0-tiny-frame", **mv(pos=(4.5, -2.25, 0.53), dt=0.00005, steps=1)),
    # A mover given a CarState that is not the Car's, dropped onto its
    # stops so BottomOut writes to one of them.
    Scen("c0-apart", pos=(0.0, 0.0, 0.3), vel=(0.0, 0.0, -2.0), apart=1,
         fwd2=15.0, steps=2),
    Scen("c0-draft", **mv(draft=0.25)),
    # No skids: a car not rendering, and a traffic car.
    Scen("c0-no-render", **mv(render=0)),
    Scen("c0-traffic", **mv(dtype=3)),
    # One long frame, six sub-steps; and one that is exactly two.
    Scen("c0-long-frame", **mv(dt=0.05, steps=1)),
    Scen("c0-two-steps", **mv(dt=0.0168, steps=2)),
]

# ============================================================ direct calls

# ComputeAuxiliaries' box: the gear asked for, the gear it is in, and the
# rear wheels' speed.
GEAR_DESIRED = [-1, 0, 4]
GEAR_START = [0, 1, 2, 5, 7]
GEAR_WW = [0.0, 12.0, 45.0, 110.0, -20.0]
# Its locks: the brake, each wheel's speed, and which were locked before.
LOCK_BRAKE = [0.1, 0.2, 0.5, 0.95, 0.96]
LOCK_WW = (5.0, 29.875, 30.0, -31.0)
LOCK_BEFORE = [0x0, 0xa]

# GetDerivative's: RPM (idle is substituted per car), throttle, boost,
# brake, and the body's speed along x.
DERIV_RPM = [None, 2500.0, 7200.0]
DERIV_THR = [0.0, 0.04, 0.05, 0.6, 1.0]
DERIV_BOOST = [1.0, 1.4]
DERIV_BRAKE = [0.0, 0.7]
DERIV_SPEED = [0.0, 15.0]
DERIV_WW = (10.0, 25.0, -5.0, 40.0)
DERIV_FORCE = (100.0, -50.0, 25.0, 0.0)
DERIV_LOCKS = [0x0, 0x9]

# BottomOut's: the penetration of each wheel, and the hub's velocity.
BOTTOM_PEN = [(0.0, 0.0, 0.0, 0.0), (0.05, 0.0, 0.0, 0.0),
              (0.05, 0.02, 0.01, 0.1), (-0.1, 0.0, 0.03, 0.0)]
BOTTOM_VEL = [((0.0, 0.0, -2.0), Z3), ((0.0, 0.0, 2.0), Z3),
              ((3.0, 0.0, -1.0), (0.5, 0.25, 0.0))]

# JumpStabilizer's: wheels down, the body matrix, the car's velocity.
JUMP_N = [0, 1, 2]
JUMP_MAT = [TILT, ROLLED]
JUMP_VEL = [(6.0, 3.0, 0.0), (0.0, 0.0, -4.0)]
JUMP_AV = (0.5, -0.25, 1.5)

# SetBoost's: f, DriverMode, ForwardSpeed. 30 mph is 13.4108 m/s.
BOOST_F = [0.5, 1.0, 1.5]
BOOST_MODE = [0, 1]
BOOST_FWD = [13.0, 13.42, 20.0]

# The accessors' wheel state and controls, and the ground and slip flags
# poked in before the per-wheel getters, so that no two neighbours agree.
ACCESS_STATE = (1.5, -2.25, 3.0, 4.75)
ACCESS_SET4 = (7.0, 8.5, -9.0, 10.25)
ACCESS_TOUCH = (0, 1, 1, 0)
ACCESS_SLIP = (0, 1, 0, 1)

# The shift-point edges: the rear wheels' speed, and the gear each test
# starts in -- an up-shift from 3 and a down-shift from 4.
EDGE_WW = 45.0
EDGE_UP, EDGE_DOWN = 3, 4
FLT_MAX_BITS = 0x7f7fffff


def knee_boost(s, l):
    """(mag, boost): the slip's magnitude as ResolveForces takes it, and the
    friction boost whose knee -- boost * 0.05 -- is that magnitude exactly,
    or None. The harness searches the same way, from the same bits."""
    mag = f32(math.sqrt(f32(f32(s * s) + f32(l * l))))
    if not mag > 0.0:
        return mag, None
    k = f32(0.05)
    b = f32(mag / k)
    for _ in range(64):
        e = f32(b * k)
        if e == mag:
            return mag, b
        b = struct.unpack("<f", struct.pack(
            "<I", fb(b) + (1 if e < mag else -1)))[0]
    return mag, None


def u32s(xs):
    return ", ".join("0x%08xu" % fb(x) for x in xs)


def ints(xs):
    return ", ".join("%d" % x for x in xs)


def generate(ctis):
    g = []
    w = g.append
    w("// Generated by tools/mellowmover_check.py. Do not edit.")
    w("#define MM_GENERATED 1")
    w("#include <stddef.h>")
    w("#include <stdint.h>")
    w("#include <stdio.h>")
    w('#include "mellowmover.h"')
    w("")
    w("typedef struct PcField { const char *name; size_t hoff, hsize; } PcField;")
    w("typedef struct PcType { const char *name; const PcField *f; int n; } PcType;")
    g.extend(pcc.c_dumps(DUMPED))
    w("typedef struct MmScen {")
    w("    const char *name;")
    w(pcc.c_scen_fields(SCEN_FIELDS))
    w("} MmScen;")
    w("static const MmScen mm_scen[] = {")
    for s in SCENARIOS:
        w("    " + pcc.c_scen_value(s, SCEN_FIELDS) + ",")
    w("};")
    w("#define MM_NSCEN %d" % len(SCENARIOS))
    w("#define MM_MOVING_INDEX %d"
      % [s.name for s in SCENARIOS].index("c0-move"))
    w("")
    w("static const uint8_t mm_cti[%d][1368] = {" % len(ctis))
    for rec in ctis:
        w("    {")
        for i in range(0, 1368, 24):
            w("        " + ", ".join("%d" % b for b in rec[i:i + 24]) + ",")
        w("    },")
    w("};")
    w("")
    w("static const int32_t mm_gear_desired[] = {%s};" % ints(GEAR_DESIRED))
    w("static const int32_t mm_gear_start[] = {%s};" % ints(GEAR_START))
    w("static const uint32_t mm_gear_ww[] = {%s};" % u32s(GEAR_WW))
    w("static const uint32_t mm_lock_brake[] = {%s};" % u32s(LOCK_BRAKE))
    w("static const uint32_t mm_lock_ww[4] = {%s};" % u32s(LOCK_WW))
    w("static const int32_t mm_lock_before[] = {%s};" % ints(LOCK_BEFORE))
    w("static const uint32_t mm_deriv_rpm[] = {%s};"
      % ", ".join("0xffffffffu" if r is None else "0x%08xu" % fb(r)
                  for r in DERIV_RPM))
    w("static const uint32_t mm_deriv_thr[] = {%s};" % u32s(DERIV_THR))
    w("static const uint32_t mm_deriv_boost[] = {%s};" % u32s(DERIV_BOOST))
    w("static const uint32_t mm_deriv_brake[] = {%s};" % u32s(DERIV_BRAKE))
    w("static const uint32_t mm_deriv_speed[] = {%s};" % u32s(DERIV_SPEED))
    w("static const uint32_t mm_deriv_ww[4] = {%s};" % u32s(DERIV_WW))
    w("static const uint32_t mm_deriv_force[4] = {%s};" % u32s(DERIV_FORCE))
    w("static const int32_t mm_deriv_locks[] = {%s};" % ints(DERIV_LOCKS))
    w("static const uint32_t mm_bottom_pen[][4] = {%s};" % ", ".join(
        "{%s}" % u32s(p) for p in BOTTOM_PEN))
    w("static const uint32_t mm_bottom_vel[][2][3] = {%s};" % ", ".join(
        "{{%s}, {%s}}" % (u32s(v), u32s(a)) for v, a in BOTTOM_VEL))
    w("static const int32_t mm_jump_n[] = {%s};" % ints(JUMP_N))
    w("static const uint32_t mm_jump_mat[][9] = {%s};" % ", ".join(
        "{%s}" % u32s(m) for m in JUMP_MAT))
    w("static const uint32_t mm_jump_vel[][3] = {%s};" % ", ".join(
        "{%s}" % u32s(v) for v in JUMP_VEL))
    w("static const uint32_t mm_jump_av[3] = {%s};" % u32s(JUMP_AV))
    w("static const uint32_t mm_boost_f[] = {%s};" % u32s(BOOST_F))
    w("static const int32_t mm_boost_mode[] = {%s};" % ints(BOOST_MODE))
    w("static const uint32_t mm_boost_fwd[] = {%s};" % u32s(BOOST_FWD))
    w("static const uint32_t mm_access_state[4] = {%s};" % u32s(ACCESS_STATE))
    w("static const uint32_t mm_access_set4[4] = {%s};" % u32s(ACCESS_SET4))
    w("static const int32_t mm_access_touch[4] = {%s};" % ints(ACCESS_TOUCH))
    w("static const int32_t mm_access_slip[4] = {%s};" % ints(ACCESS_SLIP))
    w("#define MM_EDGE_WW 0x%08xu" % fb(EDGE_WW))
    w("#define MM_EDGE_UP %d" % EDGE_UP)
    w("#define MM_EDGE_DOWN %d" % EDGE_DOWN)
    w("#define MM_FLT_MAX_BITS 0x%08xu" % FLT_MAX_BITS)
    w("#define MM_N(a) ((int)(sizeof(a) / sizeof((a)[0])))")
    w("#define MM_NORMAL_X 0x%08xu" % pcc.NORMAL[0])
    w("#define MM_NORMAL_Y 0x%08xu" % pcc.NORMAL[1])
    w("#define MM_NORMAL_Z 0x%08xu" % pcc.NORMAL[2])
    w("static const uint32_t MM_TERRAIN[4][3] = {%s};" % ", ".join(
        "{%s}" % pcc.c_u32_list(v) for v in pcc.TERRAIN))
    w("#line 1 \"mellowmover_test.c\"")
    return NL.join(g) + NL


# ================================================================= the model

GP = pcc.GP
G_MELLOVATOR_POOL = GP - 23380
G_MELLOWMOVER_POOL = GP - 23376
POOLS = pcc.POOLS + ["Mellovator", "MellowMover"]

G_USENEWCAL = pcc.G_USENEWCAL
G_UGLY = pcc.G_UGLY
G_GPI = 0x00323d74                 # gGroundPenaltyImpulse
G_MAXI = 0x00324a40                # MaxiMellowTimeStep
G_FEEDBACK = 0x00324a38            # MellowForceFeedbackGraph
G_JUMP = 0x00324a48                # MellowJumpStabilization

SINIT = 0x00208420
JUMP_U_W = 0x00206f8c              # `lqc2 vf1,48(sp)`, u's three stores done

VT_MELLOVATOR = 0x0029f2c8
VT_MELLOWMOVER = 0x0029f330
VT_MELLOWMOVER_VEHICLE = 0x0029f310
TABLE_SYM = {
    VT_MELLOVATOR: "_vt$10Mellovator",
    VT_MELLOWMOVER: "_vt$11MellowMover",
    VT_MELLOWMOVER_VEHICLE: "_vt$11MellowMover$14PhysicsVehicle",
}
# The entry the port leaves NULL until DoSnapshot lands.
PENDING = {(VT_MELLOWMOVER, 3): "DoSnapshot"}

CAR_SIZE = pcc.CAR_SIZE
DRIVER_SIZE = pcc.DRIVER_SIZE
CAR_STATE, CAR_DRAFT, CAR_MYDRIVER = pcc.CAR_STATE, pcc.CAR_DRAFT, pcc.CAR_MYDRIVER
CAR_RENDERING = pcc.CAR_RENDERING
DRIVERINFO_TYPE = pcc.DRIVERINFO_TYPE
DRV_STEERING, DRV_THROTTLE, DRV_BRAKE = (pcc.DRV_STEERING, pcc.DRV_THROTTLE,
                                         pcc.DRV_BRAKE)
DRV_DESIREDGEAR = pcc.DRV_DESIREDGEAR

# The Mellovator's table, in bytes.
MV_VT = 8
MV_GETSIZE, MV_GETSTATE, MV_GETSTATE_PF, MV_SETSTATE_PF = 16, 24, 32, 40
MV_RESOLVE, MV_DERIV, MV_AUX = 48, 56, 64

CTI_IDLE = 688                     # CarTypeInfo.Engine.IdleRPM

SYM = {
    "ctor": "__11MellowMoverP3CarP11CarTypeInfoP9CarDriverP8CarState",
    "new": "__nw__11MellowMoverUi",
    "delete": "__dl__11MellowMoverPv",
    "jump": "JumpStabilizer__11MellowMover",
    "boost": "SetBoost__11MellowMoverf",
    "bottom": "BottomOut__10MellovatorP8CarState",
}


class Model(pcc.Model):
    def __init__(self, ctis):
        pcc.Model.__init__(self, ctis)
        e = self.e
        self.mm = 0
        self.cs2 = 0
        self.inuse += [0, 0]
        for i, a in ((7, G_MELLOVATOR_POOL), (8, G_MELLOWMOVER_POOL)):
            base = pcc.POOL_BASE + 0x100 * i
            e.put32(a, base)
            self.pool_of[base] = i

        def zero_u_w(em):
            em.put32((em.reg[29] & M32) + 60, 0)

        e.hook(JUMP_U_W, zero_u_w)
        e.call(SINIT)
        # The race is racing, as the harness's is; nothing here reads it.
        self.put(self.race, 4)

    # ---- the objects

    def mv(self):
        return self.w(self.mm + OFF("MellowMover", "pMellovator"))

    def comp(self, field, i=None):
        off = OFF("MellowMover", field) + (4 * i if i is not None else 0)
        return self.w(self.mm + off)

    def objects(self):
        o = []
        if self.car:
            o.append(("cs", self.car + CAR_STATE, "CarState"))
            o.append(("car", self.car, CAR_SIZE))
        if self.cs2:
            o.append(("cs2", self.cs2, "CarState"))
        if self.drv:
            o.append(("drv", self.drv, DRIVER_SIZE))
        if self.cti:
            o.append(("cti", self.cti, 1368))
        o.append(("topo", pcc.TOPO, 16))
        if self.mm:
            o.append(("mm", self.mm, "MellowMover"))
            for nm, fld, t in (("mv", "pMellovator", "Mellovator"),
                               ("body", "pBody", "RigidBody"),
                               ("aero", "pAerodynamics", "Aerodynamics")):
                a = self.comp(fld)
                if a:
                    o.append((nm, a, t))
            for i in range(4):
                a = self.comp("pWheels", i)
                if a:
                    o.append(("wheel%d" % i, a, "Wheel"))
        return o

    # ---- the dump

    def globals(self):
        self.say("globals ugly=%08x gpi=%08x maxi=%08x newcal=%d tick=%d" % (
            self.w(G_UGLY), self.w(G_GPI), self.w(G_MAXI),
            s32(self.w(G_USENEWCAL)), self.tick))

    def pools(self):
        self.say("pools " + " ".join("%s=%d" % (n, c)
                                     for n, c in zip(POOLS, self.inuse)))

    def walk(self):
        sysa = self.mm + OFF("MellowMover", "Vehicle")
        for d, off in (("fwd", 0), ("back", 4)):
            names = []
            a = self.w(sysa + off)
            while a != sysa and len(names) < 32:
                names.append(self.label(a))
                a = self.w(a + off)
            self.say("list %s %s" % (d, " ".join(names)))
        self.raw("mm.Vehicle", "Size", sysa + OFF("PhysicsSystem", "Size"), 4)

    def dump_all(self, tag):
        self.say("-- " + tag)
        self.dump("MellowMover", "mm", self.mm)
        self.dump("Mellovator", "mv", self.mv())
        self.dump("RigidBody", "body", self.comp("pBody"))
        self.dump("Aerodynamics", "aero", self.comp("pAerodynamics"))
        for i in range(4):
            self.dump("Wheel", "wheel%d" % i, self.comp("pWheels", i))
        self.dump("CarState", "cs", self.car + CAR_STATE)
        if self.cs2:
            self.dump("CarState", "cs2", self.cs2)
        self.walk()
        self.globals()

    # ---- the mover

    def pf(self, a, v):
        self.put(a, fb(v))

    def build(self, s):
        e = self.e
        self.put(G_USENEWCAL, s.newcal)
        self.pf(G_UGLY, 1.0)
        self.tick = 0
        cti = self.cti = e.alloc(1376, 64)
        e.write(cti, self.ctis[s.car] + bytes(8))
        car = self.car = self.zalloc(CAR_SIZE)
        drv = self.drv = self.zalloc(DRIVER_SIZE)
        di = self.zalloc(20)
        self.put(di + DRIVERINFO_TYPE, s.dtype)
        self.put(car + CAR_MYDRIVER, di)
        self.pf(car + CAR_DRAFT, s.draft)
        e.mem[car + CAR_RENDERING] = s.render & 0xff

        cs = car + CAR_STATE
        L = LAYOUT["CarState"]
        self.put(cs + L.off("pCarInfo"), cti)
        self.put(cs + L.off("pTopologyCoordinate"), pcc.TOPO)
        for i in range(3):
            self.pf(cs + L.off("Position") + 4 * i, s.pos[i])
            self.pf(cs + L.off("Velocity") + 4 * i, s.vel[i])
            self.pf(cs + L.off("AngularVelocity") + 4 * i, s.avel[i])
            for j in range(3):
                self.pf(cs + L.off("BodyMatrix") + 16 * i + 4 * j,
                        s.mat[3 * i + j])
        self.pf(cs + L.off("BodyMatrix") + 60, 1.0)
        for i in range(4):
            self.pf(cs + L.off("WheelAngle") + 4 * i, s.wa)
            self.pf(cs + L.off("WheelAngularVelocity") + 4 * i, s.ww[i])
            e.mem[cs + L.off("WheelTouchingGround") + i] = int(i < s.ntouch)
        self.put(cs + L.off("nWheelsTouchingGround"), s.ntouch)
        self.pf(cs + L.off("ForwardSpeed"), s.fwd)
        self.put(cs + L.off("DriverMode"), s.dmode)
        self.pf(cs + L.off("BoostFactor"), s.boostf)

        e.mem[drv + DRV_STEERING:drv + DRV_STEERING + 2] = struct.pack(
            "<H", s.steer)
        self.pf(drv + DRV_THROTTLE, s.thr)
        self.pf(drv + DRV_BRAKE, s.brk)
        self.put(drv + DRV_DESIREDGEAR, s.dgear)

        self.cs2 = 0
        arg = cs
        if s.apart:
            n = L.size
            arg = self.cs2 = self.zalloc(n)
            e.mem[arg:arg + n] = e.read(cs, n)
            self.pf(arg + L.off("ForwardSpeed"), s.fwd2)

        self.say("== " + s.name)
        mm = self.call(SYM["new"], 64) & M32
        self.mm = mm
        self.call(SYM["ctor"], mm, car, cti, drv, arg)
        self.pools()

    def teardown(self, flags=1, table="mover"):
        mm = self.mm
        if table == "mover":
            self.vcall(mm, OFF("MellowMover", "Mover", "_vtable"), 8, flags)
        else:
            self.vcall(mm + OFF("MellowMover", "Vehicle"),
                       OFF("PhysicsSystem", "_vtable"), 8, flags)
        if not flags & 1:
            self.say("dtor mover.vt=%08x vehicle.vt=%08x" % (
                self.w(mm + OFF("MellowMover", "Mover", "_vtable")),
                self.w(mm + OFF("MellowMover", "Vehicle", "_vtable"))))
            self.call(SYM["delete"], mm)
        self.mm = 0
        self.pools()
        self.car = self.drv = self.cti = self.cs2 = 0

    def run_move(self, s):
        self.build(s)
        self.dump_all("ctor")
        for n in range(s.steps):
            self.e.fpr[12] = fb(s.dt)
            self.vcall(self.mm, OFF("MellowMover", "Mover", "_vtable"), 16)
            self.say("-- move %d ret=%08x" % (n, self.e.fpr[0] & M32))
            self.dump_all("move %d" % n)
        self.teardown()

    # ---- the direct calls

    def mvf(self, name, i=0):
        """A Mellovator field's address, element i of an array."""
        f = LAYOUT["Mellovator"].by[name]
        return self.mv() + f.off + 4 * i

    def s_static(self):
        self.say("== static")
        for nm, g in (("MellowForceFeedbackGraph", G_FEEDBACK),
                      ("MellowJumpStabilization", G_JUMP)):
            pts, n = self.w(g), s32(self.w(g + 4))
            self.say("%s %d %s" % (nm, n, hexw([self.w(pts + 4 * i)
                                                for i in range(2 * n)])))
        self.say("MaxiMellowTimeStep %08x gGroundPenaltyImpulse %08x"
                 % (self.w(G_MAXI), self.w(G_GPI)))

    def s_tables(self):
        self.say("== tables")
        vehicle = OFF("MellowMover", "Vehicle")
        for nm, vt in (("Mellovator", VT_MELLOVATOR),
                       ("MellowMover", VT_MELLOWMOVER),
                       ("MellowMover$Vehicle", VT_MELLOWMOVER_VEHICLE)):
            n = self.e.elf.syms[TABLE_SYM[vt]][1] // 8
            cells = ["n=%d" % n]
            for i in range(n):
                delta = struct.unpack("<h", self.e.read(vt + 8 * i, 2))[0]
                fn = self.w(vt + 8 * i + 4)
                if (vt, i) in PENDING:
                    fn = 0
                d = "mm" if delta == -vehicle and delta else str(delta)
                cells.append("%s/%s" % (d, "fn" if fn else "null"))
            self.say("vt %s %s" % (nm, " ".join(cells)))

    def s_gearbox(self):
        self.build(Scen("gearbox", **mv(steps=0)))
        m = self.mv()
        for d in GEAR_DESIRED:
            for g0 in GEAR_START:
                for ww in GEAR_WW:
                    self.put(self.mvf("CurrentGear"), g0)
                    self.put(self.mvf("DesiredGear"), d)
                    self.pf(self.mvf("Brake"), 0.0)
                    for i in range(4):
                        self.pf(self.mvf("State", i), ww)
                        self.put(self.mvf("BrakeLocked", i), 0)
                    self.vcall(m, MV_VT, MV_AUX)
                    self.say("gear d=%d g0=%d ww=%08x -> gear=%d rpm=%08x" % (
                        d, g0, fb(ww), s32(self.w(self.mvf("CurrentGear"))),
                        self.w(self.mvf("RPM"))))
        for b in LOCK_BRAKE:
            for before in LOCK_BEFORE:
                self.put(self.mvf("CurrentGear"), 2)
                self.put(self.mvf("DesiredGear"), -1)
                self.pf(self.mvf("Brake"), b)
                for i in range(4):
                    self.pf(self.mvf("State", i), LOCK_WW[i])
                    self.put(self.mvf("BrakeLocked", i), before >> i & 1)
                self.vcall(m, MV_VT, MV_AUX)
                self.say("lock brk=%08x before=%x -> ww=%s locked=%s" % (
                    fb(b), before,
                    hexw([self.w(self.mvf("State", i)) for i in range(4)]),
                    " ".join("%d" % s32(self.w(self.mvf("BrakeLocked", i)))
                             for i in range(4))))
        self.edge(m, EDGE_UP, True)
        self.edge(m, EDGE_DOWN, False)
        self.dump("Mellovator", "mv", m)
        self.teardown()

    def edge(self, m, g, up):
        """A shift point equal to the RPM. A probe in a fixed gear reads the
        RPM the box will see; that is made the point, and the neighbour that
        could shift the car back is cleared, so only the test's strictness
        decides. The two tables are put back after."""
        def arm(desired):
            self.put(self.mvf("CurrentGear"), g)
            self.put(self.mvf("DesiredGear"), desired)
            self.pf(self.mvf("Brake"), 0.0)
            for i in range(4):
                self.pf(self.mvf("State", i), EDGE_WW)
                self.put(self.mvf("BrakeLocked", i), 0)

        arm(4)
        self.vcall(m, MV_VT, MV_AUX)
        probe = self.w(self.mvf("RPM"))
        ua, da = self.mvf("ShiftUpRPM"), self.mvf("ShiftDownRPM")
        saved = self.e.read(ua, 36), self.e.read(da, 36)
        if up:
            self.put(ua + 4 * g, probe)
            self.put(da + 4 * g, 0)
            self.put(da + 4 * (g + 1), 0)
        else:
            self.put(ua + 4 * g, FLT_MAX_BITS)
            self.put(da + 4 * g, probe)
            self.put(da + 4 * (g - 1), 0)
        arm(-1)
        self.vcall(m, MV_VT, MV_AUX)
        self.say("edge %s g=%d probe=%08x -> gear=%d rpm=%08x" % (
            "up" if up else "down", g, probe,
            s32(self.w(self.mvf("CurrentGear"))), self.w(self.mvf("RPM"))))
        self.e.mem[ua:ua + 36] = saved[0]
        self.e.mem[da:da + 36] = saved[1]

    def s_derivative(self):
        self.build(Scen("derivative", **mv(steps=0)))
        m = self.mv()
        body = self.comp("pBody")
        out = self.zalloc(16)
        idle = self.w(self.cti + CTI_IDLE)
        for r in DERIV_RPM:
            for t in DERIV_THR:
                for bo in DERIV_BOOST:
                    for br in DERIV_BRAKE:
                        for sp in DERIV_SPEED:
                            for lk in DERIV_LOCKS:
                                self.put(self.mvf("RPM"),
                                         idle if r is None else fb(r))
                                self.pf(self.mvf("Throttle"), t)
                                self.pf(self.mvf("CurrentBoost"), bo)
                                self.pf(self.mvf("Brake"), br)
                                self.pf(body + OFF("RigidBody", "Velocity"), sp)
                                for i in range(4):
                                    self.pf(self.mvf("State", i), DERIV_WW[i])
                                    self.put(self.mvf("BrakeLocked", i),
                                             lk >> i & 1)
                                    self.pf(self.mvf("WheelForce", 2 * i),
                                            DERIV_FORCE[i])
                                ret = self.vcall(m, MV_VT, MV_DERIV, out) & M32
                                self.say("deriv rpm=%08x thr=%08x boost=%08x "
                                         "brk=%08x v=%08x lock=%x -> %s %s" % (
                                             self.w(self.mvf("RPM")), fb(t),
                                             fb(bo), fb(br), fb(sp), lk,
                                             hexw([self.w(out + 4 * i)
                                                   for i in range(4)]),
                                             "out" if ret == out else "?"))
        self.teardown()

    def s_bottom(self):
        self.build(Scen("bottom"))
        m = self.mv()
        body = self.comp("pBody")
        cs = self.car + CAR_STATE
        for pen in BOTTOM_PEN:
            for v, av in BOTTOM_VEL:
                for i in range(3):
                    self.pf(body + OFF("RigidBody", "Velocity") + 4 * i, v[i])
                    self.pf(body + OFF("RigidBody", "AngularVelocity") + 4 * i,
                            av[i])
                for i in range(4):
                    self.pf(self.mvf("GroundPenetration", i), pen[i])
                    self.pf(self.mvf("SuspensionPosition", i), 0.0625 * i)
                self.call(SYM["bottom"], m, cs)
                self.say("bottom pen=%s v=%s ret=%08x" % (
                    hexw([fb(x) for x in pen]), hexw([fb(x) for x in v + av]),
                    self.e.fpr[0] & M32))
                self.dump("RigidBody", "body", body)
                self.raw("cs", "WheelBottomOutMagnitude",
                         cs + LAYOUT["CarState"].off("WheelBottomOutMagnitude"),
                         16)
        self.teardown()

    def s_jump(self):
        self.build(Scen("jump"))
        body = self.comp("pBody")
        L = LAYOUT["CarState"]
        cs = self.car + CAR_STATE
        for n in JUMP_N:
            for mat in JUMP_MAT:
                for v in JUMP_VEL:
                    self.put(cs + L.off("nWheelsTouchingGround"), n)
                    for i in range(3):
                        self.pf(cs + L.off("Velocity") + 4 * i, v[i])
                        for j in range(3):
                            self.pf(cs + L.off("BodyMatrix") + 16 * i + 4 * j,
                                    mat[3 * i + j])
                        self.pf(body + OFF("RigidBody", "AngularVelocity")
                                + 4 * i, JUMP_AV[i])
                    for f in ("ForceAccumulator", "MomentAccumulator"):
                        a = body + OFF("RigidBody", f)
                        self.e.mem[a:a + 16] = bytes(16)
                    self.call(SYM["jump"], self.mm)
                    self.say("jump n=%d up=%08x v=%s" % (
                        n, fb(mat[8]), hexw([fb(x) for x in v])))
                    self.dump("RigidBody", "body", body)
        self.teardown()

    def s_boost(self):
        self.build(Scen("boost", boostf=1.25, draft=0.2))
        L = LAYOUT["CarState"]
        cs = self.car + CAR_STATE
        for f in BOOST_F:
            for md in BOOST_MODE:
                for fwd in BOOST_FWD:
                    self.put(cs + L.off("DriverMode"), md)
                    self.pf(cs + L.off("ForwardSpeed"), fwd)
                    self.call(SYM["boost"], self.mm, floats=[fb(f)])
                    a, b = self.comp("pAerodynamics"), self.comp("pBody")
                    self.say("boost f=%08x mode=%d fwd=%08x -> aero=%08x %08x "
                             "catchup=%08x boost=%08x friction=%08x" % (
                                 fb(f), md, fb(fwd),
                                 self.w(a + OFF("Aerodynamics", "Boost")),
                                 self.w(a + OFF("Aerodynamics", "Draft")),
                                 self.w(b + OFF("RigidBody", "CatchUpMultiplier")),
                                 self.w(self.mvf("CurrentBoost")),
                                 self.w(self.mvf("CurrentFrictionBoost"))))
        self.teardown()

    def s_access(self):
        self.build(Scen("access", **mv(steps=0)))
        m = self.mv()
        c = self.call
        self.say("size %d" % self.vcall(m, MV_VT, MV_GETSIZE))
        self.say("state -> %s" % self.label(
            self.vcall(m, MV_VT, MV_GETSTATE) & M32))
        buf = self.zalloc(16)
        for i in range(4):
            self.pf(buf + 4 * i, ACCESS_STATE[i])
        self.vcall(m, MV_VT, MV_SETSTATE_PF, buf)
        self.e.mem[buf:buf + 16] = bytes(16)
        self.vcall(m, MV_VT, MV_GETSTATE_PF, buf)
        self.say("get state %s" % hexw([self.w(buf + 4 * i) for i in range(4)]))
        c("SetThrottle__10Mellovatorf", m, floats=[fb(0.375)])
        c("SetBrake__10Mellovatorf", m, floats=[fb(0.8125)])
        c("SetSteering__10MellovatorUs", m, 0xf123)
        c("SetDesiredGear__10Mellovator4Gear", m, 5)
        c("SetCurrentBoost__10Mellovatorf", m, floats=[fb(1.125)])
        c("SetCurrentFrictionBoost__10Mellovatorf", m, floats=[fb(0.875)])
        c("GetRPM__10Mellovator", m)
        rpm = self.e.fpr[0] & M32
        self.say("rpm %08x gear %d" % (rpm, c("GetCurrentGear__10Mellovator", m)))
        for i in range(4):
            self.put(self.mvf("TouchingGround", i), ACCESS_TOUCH[i])
            self.put(self.mvf("bSlipping", i), ACCESS_SLIP[i])
        for i in range(4):
            tg = c("GetTouchingGround__10Mellovatori", m, i)
            c("GetSuspensionForce__10Mellovatori", m, i)
            sf = self.e.fpr[0] & M32
            c("GetSuspensionPosition__10Mellovatori", m, i)
            sp = self.e.fpr[0] & M32
            sl = c("GetWheelSlipping__10Mellovatori", m, i)
            slip = c("GetWheelSlip__10Mellovatori", m, i) & M32
            c("GetWheelAngularVelocity__10Mellovatori", m, i)
            av = self.e.fpr[0] & M32
            self.say("wheel %d touch=%d force=%08x pos=%08x slipping=%d "
                     "slip=%s ww=%08x" % (i, tg, sf, sp, sl, self.label(slip),
                                          av))
        # ResolveForces clears every wheel's slipping flag first: the two
        # off the ground keep theirs only if it does not.
        for i in range(4):
            self.put(self.mvf("bSlipping", i), 1)
        self.vcall(m, MV_VT, MV_RESOLVE)
        self.say("rf slipping %s" % " ".join(
            "%d" % s32(self.w(self.mvf("bSlipping", i))) for i in range(4)))
        # The grip knee, met exactly: the friction boost is set so that
        # boost * 0.05 is a grounded wheel's slip magnitude.
        for k in range(4):
            if not ACCESS_TOUCH[k]:
                continue
            s = self.f(self.mvf("WheelSlip", 2 * k))
            l = self.f(self.mvf("WheelSlip", 2 * k + 1))
            mag, b = knee_boost(s, l)
            if b is None:
                continue
            self.pf(self.mvf("CurrentFrictionBoost"), b)
            self.vcall(m, MV_VT, MV_RESOLVE)
            self.say("knee wheel=%d mag=%08x boost=%08x force=%s" % (
                k, fb(mag), fb(b), hexw([self.w(self.mvf("WheelForce", 2 * k)),
                                         self.w(self.mvf("WheelForce",
                                                         2 * k + 1))])))
            break
        else:
            self.say("knee none")
        # SetState(ffff) clears the locks and the suspension.
        for i in range(4):
            self.put(self.mvf("BrakeLocked", i), 1)
            self.pf(self.mvf("SuspensionPosition", i), 0.25)
        c("SetState__10Mellovatorffff", m, floats=[fb(x) for x in ACCESS_SET4])
        self.dump("Mellovator", "mv", m)
        self.teardown()

    def s_calibrate(self):
        # Calibrate recomputes the body's mass and inverse tensor from its
        # record every time, so a body whose were changed is put back.
        self.build(Scen("calibrate", **mv(steps=0)))
        body = self.comp("pBody")
        self.pf(body + OFF("RigidBody", "Mass"), 2.0)
        self.pf(body + OFF("RigidBody", "Mass_inv"), 0.5)
        for i in range(16):
            self.pf(body + OFF("RigidBody", "I_body_inv") + 4 * i, 0.25)
        self.call("Calibrate__11MellowMover", self.mm)
        self.dump("RigidBody", "body", body)
        self.dump("Mellovator", "mv", self.mv())
        self.teardown()

    def s_dtors(self):
        self.build(Scen("dtor-mover-0"))
        mvp = self.mv()
        self.teardown(0, "mover")
        # A freed slot keeps all but its first word, so the Mellovator's
        # vptr is the last destructor's.
        self.say("freed mv.vt=%08x" % self.w(mvp + MV_VT))
        self.build(Scen("dtor-vehicle-1"))
        self.teardown(1, "vehicle")
        self.build(Scen("dtor-vehicle-0"))
        self.teardown(0, "vehicle")
        # The Mellovator's own destructor without the delete bit, which no
        # PhysicsSystem passes it.
        self.build(Scen("dtor-mellovator-0"))
        p = self.call("__nw__10MellovatorUi", 448) & M32
        self.call("__10MellovatorP11CarTypeInfoP9RigidBodyP18TopologyCoordinate",
                  p, self.cti, self.comp("pBody"), pcc.TOPO)
        self.vcall(p, MV_VT, 8, 0)
        self.say("mellovator dtor 0 vt=%08x" % self.w(p + MV_VT))
        self.pools()
        self.call("__dl__10MellovatorPv", p)
        self.pools()
        self.teardown()

    def run(self):
        self.s_static()
        self.s_tables()
        for s in SCENARIOS:
            self.run_move(s)
        self.s_gearbox()
        self.s_derivative()
        self.s_bottom()
        self.s_jump()
        self.s_boost()
        self.s_access()
        self.s_calibrate()
        self.s_dtors()
        return self.out


def model(ctis=None):
    return Model(ctis or cti_records()).run()


# ================================================================ the build

def build_harness(tmp, ctis, name="mellowmover_test"):
    text = generate(ctis) + HARNESS.read_text(encoding="utf-8")
    src = Path(tmp) / "mellowmover_test.c"
    src.write_text(text, encoding="utf-8", newline=NL)
    return hostbuild.build(tmp, [str(src)] + SOURCES_PORT, name=name)


run_harness = pcc.run_harness
diff = pcc.diff

# ============================================================ the mutations

MUTATIONS = [
    # -- the static initialiser and the tuning -------------------------------
    ("mm-sinit-feedback-y0", MMC,
     "    MellowForceFeedbackData[0].y = MV_FEEDBACK_Y0;",
     "    MellowForceFeedbackData[0].y = 0.5f;"),
    ("mm-sinit-feedback-x1", MMC,
     "    MellowForceFeedbackData[1].x = 20.0f;",
     "    MellowForceFeedbackData[1].x = 10.0f;"),
    ("mm-sinit-feedback-y1", MMC,
     "    MellowForceFeedbackData[1].y = 0.5f;",
     "    MellowForceFeedbackData[1].y = 0.4f;"),
    ("mm-sinit-feedback-one-point", MMC,
     "graph_init(&MellowForceFeedbackGraph, MellowForceFeedbackData, 2);",
     "graph_init(&MellowForceFeedbackGraph, MellowForceFeedbackData, 1);"),
    ("mm-sinit-jump-knee", MMC,
     "    MellowJumpStabilizationGraph[1].x = MV_JUMP_KNEE;",
     "    MellowJumpStabilizationGraph[1].x = 0.5f;"),
    ("mm-sinit-jump-top-y", MMC,
     "    MellowJumpStabilizationGraph[2].y = 20.0f;",
     "    MellowJumpStabilizationGraph[2].y = 10.0f;"),
    ("mm-sinit-jump-top-x", MMC,
     "    MellowJumpStabilizationGraph[2].x = 2.0f;",
     "    MellowJumpStabilizationGraph[2].x = 4.0f;"),
    ("mm-sinit-jump-two-points", MMC,
     "graph_init(&MellowJumpStabilization, MellowJumpStabilizationGraph, 3);",
     "graph_init(&MellowJumpStabilization, MellowJumpStabilizationGraph, 2);"),
    ("mm-maxi-step", MMC,
     "float MaxiMellowTimeStep = 0.0084f;",
     "float MaxiMellowTimeStep = 0.0168f;"),
    ("mm-sway-table", MMC,
     "SwayBarTable[4] = { 1, 0, 3, 2 };",
     "SwayBarTable[4] = { 3, 2, 1, 0 };"),
    ("mm-k-mph", MMC,
     "#define MV_MS_TO_MPH          2.237f",
     "#define MV_MS_TO_MPH          1.0f"),
    ("mm-k-high-speed-friction", MMC,
     "#define MV_HIGH_SPEED_FRICTION 0.7f",
     "#define MV_HIGH_SPEED_FRICTION 0.5f"),
    ("mm-k-upright", MMC,
     "#define MV_UPRIGHT            0.1f",
     "#define MV_UPRIGHT            0.05f"),
    ("mm-k-gravity", MMC,
     "#define MV_GRAVITY            9.8f",
     "#define MV_GRAVITY            9.81f"),
    ("mm-k-idle-throttle", MMC,
     "#define MV_IDLE_THROTTLE      0.05f",
     "#define MV_IDLE_THROTTLE      0.0f"),
    ("mm-k-spin-scale-rounded", MMC,
     "#define MV_SPIN_SCALE         124.99999237060547f",
     "#define MV_SPIN_SCALE         125.0f"),
    ("mm-k-lock-brake", MMC,
     "#define MV_LOCK_BRAKE         0.95f",
     "#define MV_LOCK_BRAKE         0.9f"),
    ("mm-k-unlock-brake", MMC,
     "#define MV_UNLOCK_BRAKE       0.2f",
     "#define MV_UNLOCK_BRAKE       0.25f"),
    ("mm-k-rpm", MMC,
     "#define MV_RADS_TO_RPM_HALF   4.774652004241943f",
     "#define MV_RADS_TO_RPM_HALF   4.8f"),
    ("mm-k-min-cos", MMC,
     "#define MV_MIN_COS            0.001f",
     "#define MV_MIN_COS            0.5f"),
    ("mm-k-min-dt", MMC,
     "#define MV_MIN_DT             0.0001f",
     "#define MV_MIN_DT             0.01f"),
    ("mm-k-bam-to-rad-short", MMC,
     "#define MV_BAM_TO_RAD         9.58738019107841e-05f",
     "#define MV_BAM_TO_RAD         9.587379463482648e-05f"),
    ("mm-k-half-pi-nearest", MMC,
     "#define MV_HALF_PI            1.5707964897155762f",
     "#define MV_HALF_PI            1.5707963705062866f"),
    ("mm-k-slip-knee", MMC,
     "#define MV_SLIP_KNEE          0.05f",
     "#define MV_SLIP_KNEE          0.1f"),
    ("mm-k-hold-brake", MMC,
     "#define MV_HOLD_BRAKE         0.4f",
     "#define MV_HOLD_BRAKE         0.5f"),
    ("mm-k-hold-speed", MMC,
     "#define MV_HOLD_SPEED         0.1f",
     "#define MV_HOLD_SPEED         0.2f"),

    # -- the VU idioms ----------------------------------------------------------
    ("mm-dot3-order", MMC,
     "    return (p[0] * q[0] + p[1] * q[1]) + p[2] * q[2];",
     "    return p[0] * q[0] + (p[1] * q[1] + p[2] * q[2]);"),
    ("mm-cross3-w-from-b", MMC,
     "    o->w = a->w;",
     "    o->w = b->w;"),
    ("mm-cross3-y-sign", MMC,
     "    float y = a->z * b->x - b->z * a->x;",
     "    float y = b->z * a->x - a->z * b->x;"),
    ("mm-normalize-ieee-divide", MMC,
     "    float inv = 0.0f + ee_div(1.0f, sqrtf(len2(v)));",
     "    float inv = 0.0f + 1.0f / sqrtf(len2(v));"),
    ("mm-normalize-w-kept", MMC,
     "    v->w = v->w * inv;",
     "    v->w = v->w;"),
    ("mm-quad-pad-zero", MMC,
     "    o->pad = v->w;",
     "    o->pad = 0.0f;"),
    ("mm-min-is-max", MMC,
     "    return (b < a) ? b : a;",
     "    return (a < b) ? b : a;"),
    ("mm-max-is-min", MMC,
     "    return (a < b) ? b : a;\n}\n\n// `lqc2",
     "    return (b < a) ? b : a;\n}\n\n// `lqc2"),
    ("mm-hub-x", MMC,
     "    o->x = (0.0f - c->x) + w->PositionX;",
     "    o->x = c->x + w->PositionX;"),
    ("mm-hub-y", MMC,
     "    o->y = (0.0f - c->y) + w->PositionY;",
     "    o->y = c->y + w->PositionY;"),
    ("mm-hub-z", MMC,
     "    o->z = (0.0f - c->z) + w->PositionZ;",
     "    o->z = c->z + w->PositionZ;"),
    ("mm-hub-pad", MMC,
     "    o->pad = (1.0f - c->pad) + w->Radius;",
     "    o->pad = 1.0f;"),
    ("mm-gear-number", MMC,
     "    return g - 1;",
     "    return g - 2;"),

    # -- Mellovator: new, delete, the constructor, the destructor -------------
    ("mm-mv-delete-kept", MMC,
     "    bSlotFree(MellovatorSlotPool, p);",
     "    (void)p;"),
    ("mm-mv-ctor-no-vtable", MMC,
     "    m->_vtable = MELLOVATOR_VTABLE;\n    table_init(",
     "    table_init("),
    ("mm-mv-ctor-torque-points", MMC,
     "cti->Engine.TorqueCurveTable, 9,",
     "cti->Engine.TorqueCurveTable, 8,"),
    ("mm-mv-ctor-torque-from-zero", MMC,
     "    table_init(&m->TorqueCurve, cti->Engine.TorqueCurveTable, 9,\n"
     "               cti->Engine.IdleRPM, cti->Engine.MaxRPM);",
     "    table_init(&m->TorqueCurve, cti->Engine.TorqueCurveTable, 9,\n"
     "               0.0f, cti->Engine.MaxRPM);"),
    ("mm-mv-ctor-braking-points", MMC,
     "cti->Engine.EngineBrakingTable, 3,",
     "cti->Engine.EngineBrakingTable, 2,"),
    ("mm-mv-ctor-braking-from-zero", MMC,
     "    table_init(&m->EngineBraking, cti->Engine.EngineBrakingTable, 3,\n"
     "               cti->Engine.IdleRPM, cti->Engine.MaxRPM);",
     "    table_init(&m->EngineBraking, cti->Engine.EngineBrakingTable, 3,\n"
     "               0.0f, cti->Engine.MaxRPM);"),
    ("mm-mv-ctor-shift-scale", MMC,
     "m->ShiftUpRPM, m->ShiftDownRPM, 1.0f);",
     "m->ShiftUpRPM, m->ShiftDownRPM, 0.9f);"),
    ("mm-mv-ctor-shift-swapped", MMC,
     "m->ShiftUpRPM, m->ShiftDownRPM, 1.0f);",
     "m->ShiftDownRPM, m->ShiftUpRPM, 1.0f);"),
    ("mm-mv-ctor-boost", MMC,
     "    m->CurrentBoost = 1.0f;",
     "    m->CurrentBoost = 0.0f;"),
    ("mm-mv-ctor-gear", MMC,
     "    m->CurrentGear  = FIRST_GEAR;",
     "    m->CurrentGear  = NEUTRAL;"),
    ("mm-mv-ctor-no-tc", MMC,
     "    m->TC           = tc;",
     "    m->TC           = NULL;"),
    ("mm-mv-dtor-vtable-kept", MMC,
     "    m->_vtable = MELLOVATOR_VTABLE;\n    physicscomponent_fini(m);",
     "    physicscomponent_fini(m);"),
    ("mm-mv-dtor-no-fini", MMC,
     "    physicscomponent_fini(m);\n    if (flags & 1)\n"
     "        mellovator_delete(m);",
     "    if (flags & 1)\n        mellovator_delete(m);"),
    ("mm-mv-dtor-always-delete", MMC,
     "    if (flags & 1)\n        mellovator_delete(m);",
     "    mellovator_delete(m);"),

    # -- Mellovator::Calibrate --------------------------------------------------
    ("mm-cal-always-new", MMC,
     "cog = UseNewSuspensionCalibration ? cti->CenterOfGravity.x : 0.0f;",
     "cog = cti->CenterOfGravity.x;"),
    ("mm-cal-front-wheel", MMC,
     "    a = cti->Wheels[0].PositionX - cog;",
     "    a = cti->Wheels[2].PositionX - cog;"),
    ("mm-cal-rear-wheel", MMC,
     "    b = cti->Wheels[3].PositionX - cog;",
     "    b = cti->Wheels[1].PositionX - cog;"),
    ("mm-cal-no-gravity", MMC,
     "    load  = m->pBody->Mass * MV_GRAVITY\n",
     "    load  = m->pBody->Mass\n"),
    ("mm-cal-downforce-unscaled", MMC,
     "            + cti->Aero.AutoBalanceDownforce * downforce;",
     "            + downforce;"),
    ("mm-cal-rear-share", MMC,
     "    rear  = (a / (a - b)) * 0.5f;",
     "    rear  = (b / (a - b)) * 0.5f;"),
    ("mm-cal-front-share", MMC,
     "    front = 0.5f - rear;",
     "    front = rear;"),
    ("mm-cal-rest3", MMC,
     "    m->RestLoad[3] = load * rear;",
     "    m->RestLoad[3] = load * front;"),
    ("mm-cal-rest2", MMC,
     "    m->RestLoad[2] = load * rear;",
     "    m->RestLoad[2] = load * front;"),
    ("mm-cal-rest1", MMC,
     "    m->RestLoad[1] = load * front;",
     "    m->RestLoad[1] = load * rear;"),
    ("mm-cal-rest0", MMC,
     "    m->RestLoad[0] = load * front;",
     "    m->RestLoad[0] = load * rear;"),

    # -- the state ----------------------------------------------------------------
    ("mm-ss4-w0", MMC,
     "    m->State.ww[0] = w0;",
     "    m->State.ww[0] = w1;"),
    ("mm-ss4-w3", MMC,
     "    m->State.ww[3] = w3;",
     "    m->State.ww[3] = w2;"),
    ("mm-ss4-locks-kept", MMC,
     "        m->BrakeLocked[i] = 0;\n        m->SuspensionPosition[i] = 0.0f;",
     "        m->SuspensionPosition[i] = 0.0f;"),
    ("mm-ss4-suspension-kept", MMC,
     "        m->BrakeLocked[i] = 0;\n        m->SuspensionPosition[i] = 0.0f;",
     "        m->BrakeLocked[i] = 0;"),
    ("mm-set-state-three", MMC,
     "    for (i = 0; i < 4; i++)\n        m->State.ww[i] = in[i];",
     "    for (i = 0; i < 3; i++)\n        m->State.ww[i] = in[i];"),
    ("mm-get-state-three", MMC,
     "    for (i = 0; i < 4; i++)\n        out[i] = m->State.ww[i];",
     "    for (i = 0; i < 3; i++)\n        out[i] = m->State.ww[i];"),
    ("mm-state-pointer", MMC,
     "    return m->State.ww;",
     "    return &m->State.ww[1];"),
    ("mm-get-size", MMC,
     "    (void)m;\n    return 4;",
     "    (void)m;\n    return 3;"),

    # -- Mellovator::GetDerivative --------------------------------------------
    ("mm-d-locked-spins", MMC,
     "        if (!m->BrakeLocked[i]) {\n            int32_t front = (i < 2);",
     "        if (1) {\n            int32_t front = (i < 2);"),
    ("mm-d-front-driven", MMC,
     "            if (!front) {\n                const CarTypeInfo *cti;",
     "            if (1) {\n                const CarTypeInfo *cti;"),
    ("mm-d-rpm-unboosted", MMC,
     "                rpm = m->RPM / m->CurrentBoost;",
     "                rpm = m->RPM;"),
    ("mm-d-no-engine-braking", MMC,
     "                tq = m->Throttle * t - (1.0f - m->Throttle) * eb;",
     "                tq = m->Throttle * t;"),
    ("mm-d-engine-braking-sign", MMC,
     "                tq = m->Throttle * t - (1.0f - m->Throttle) * eb;",
     "                tq = m->Throttle * t + (1.0f - m->Throttle) * eb;"),
    ("mm-d-idle-cut-any-rpm", MMC,
     "                if (m->Throttle < MV_IDLE_THROTTLE\n"
     "                    && m->RPM == cti->Engine.IdleRPM)",
     "                if (m->Throttle < MV_IDLE_THROTTLE)"),
    ("mm-d-idle-cut-halved", MMC,
     "                    tq = 0.0f;",
     "                    tq = tq * 0.5f;"),
    ("mm-d-final-drive", MMC,
     "                drive = (tq * cti->DriveTrain.FinalDrive[1])",
     "                drive = (tq * cti->DriveTrain.FinalDrive[0])"),
    ("mm-d-gear-not-halved", MMC,
     "* (cti->DriveTrain.GearRatios[m->CurrentGear] * 0.5f);",
     "* cti->DriveTrain.GearRatios[m->CurrentGear];"),
    ("mm-d-brake-cap", MMC,
     "min_s(m->State.ww[i], 20.0f) * -0.5f",
     "min_s(m->State.ww[i], 30.0f) * -0.5f"),
    ("mm-d-brake-scale", MMC,
     "min_s(m->State.ww[i], 20.0f) * -0.5f",
     "min_s(m->State.ww[i], 20.0f) * -1.0f"),
    ("mm-d-k2-base", MMC,
     "            k2 = 1.25f;",
     "            k2 = 1.0f;"),
    ("mm-d-k2-boost", MMC,
     "k2 = ((m->CurrentBoost - 1.0f) * 2.5f + 1.0f) * 1.25f;",
     "k2 = ((m->CurrentBoost - 1.0f) * 2.0f + 1.0f) * 1.25f;"),
    ("mm-d-k1-boost", MMC,
     "k1 = (m->CurrentBoost - 1.0f) * 3.0f + 1.0f;",
     "k1 = (m->CurrentBoost - 1.0f) * 2.5f + 1.0f;"),
    ("mm-d-feedback-squared-speed", MMC,
     "                                sqrtf(len2(&m->pBody->Velocity)));",
     "                                len2(&m->pBody->Velocity));"),
    ("mm-d-feedback-front-too", MMC,
     "            if (!front)\n                g = g / (k1 * k2);",
     "            g = g / (k1 * k2);"),
    ("mm-d-feedback-k2-only", MMC,
     "                g = g / (k1 * k2);",
     "                g = g / k2;"),
    ("mm-d-drive-unboosted", MMC,
     "            acc = (drive * k1 + brake) - m->WheelForce[i].x * g;",
     "            acc = (drive + brake) - m->WheelForce[i].x * g;"),
    ("mm-d-lateral-force", MMC,
     "            acc = (drive * k1 + brake) - m->WheelForce[i].x * g;",
     "            acc = (drive * k1 + brake) - m->WheelForce[i].y * g;"),
    ("mm-d-unscaled", MMC,
     "        d[i] = acc * MV_SPIN_SCALE;",
     "        d[i] = acc;"),

    # -- Mellovator::ComputeAuxiliaries --------------------------------------
    ("mm-ca-no-suspension", MMC,
     "    mellovator_compute_suspension_forces(m);\n\n    cti     = m->CTI;",
     "\n    cti     = m->CTI;"),
    ("mm-ca-lock-signed", MMC,
     "fabsf(m->State.ww[i]) < 30.0f",
     "m->State.ww[i] < 30.0f"),
    ("mm-ca-lock-speed", MMC,
     "fabsf(m->State.ww[i]) < 30.0f",
     "fabsf(m->State.ww[i]) < 20.0f"),
    ("mm-ca-lock-strict", MMC,
     "        if (MV_LOCK_BRAKE < brake && ",
     "        if (MV_LOCK_BRAKE <= brake && "),
    ("mm-ca-lock-still-spins", MMC,
     "            m->State.ww[i] = 0.0f;\n            m->BrakeLocked[i] = 1;",
     "            m->BrakeLocked[i] = 1;"),
    ("mm-ca-lock-no-flag", MMC,
     "            m->State.ww[i] = 0.0f;\n            m->BrakeLocked[i] = 1;",
     "            m->State.ww[i] = 0.0f;"),
    ("mm-ca-never-unlock", MMC,
     "        if (brake < MV_UNLOCK_BRAKE)\n            m->BrakeLocked[i] = 0;",
     "        (void)0;"),
    ("mm-ca-unlock-inclusive", MMC,
     "        if (brake < MV_UNLOCK_BRAKE)",
     "        if (brake <= MV_UNLOCK_BRAKE)"),
    ("mm-ca-front-axle", MMC,
     "(m->State.ww[2] + m->State.ww[3])",
     "(m->State.ww[0] + m->State.ww[1])"),
    ("mm-ca-final-drive", MMC,
     "    w = (cti->DriveTrain.FinalDrive[1] * ",
     "    w = (cti->DriveTrain.FinalDrive[0] * "),
    ("mm-ca-rpm-unit", MMC,
     "        * MV_RADS_TO_RPM_HALF;",
     "        * 1.0f;"),
    ("mm-ca-first-rpm-follows", MMC,
     "            m->CurrentGear = FIRST_GEAR;\n        while",
     "            m->CurrentGear = FIRST_GEAR,\n"
     "            rpm = w * cti->DriveTrain.GearRatios[FIRST_GEAR];\n        while"),
    ("mm-ca-sport-is-auto", MMC,
     "    if (desired == AUTOMATIC) {",
     "    if (desired < NEUTRAL) {"),
    ("mm-ca-below-neutral", MMC,
     "        if (gear < FIRST_GEAR)",
     "        if (gear < NEUTRAL)"),
    ("mm-ca-up-one-short", MMC,
     "        while (gear_number(m->CurrentGear) < cti->DriveTrain.NumGears",
     "        while (gear_number(m->CurrentGear) + 1 < cti->DriveTrain.NumGears"),
    ("mm-ca-up-inclusive", MMC,
     "               && m->ShiftUpRPM[m->CurrentGear] < rpm) {",
     "               && m->ShiftUpRPM[m->CurrentGear] <= rpm) {"),
    ("mm-ca-up-rpm-stale", MMC,
     "            m->CurrentGear = m->CurrentGear + 1;\n"
     "            rpm = w * cti->DriveTrain.GearRatios[m->CurrentGear];",
     "            m->CurrentGear = m->CurrentGear + 1;"),
    ("mm-ca-down-to-neutral", MMC,
     "        while (!(gear_number(m->CurrentGear) < 2)",
     "        while (!(gear_number(m->CurrentGear) < 1)"),
    ("mm-ca-down-inclusive", MMC,
     "               && rpm < m->ShiftDownRPM[m->CurrentGear]) {",
     "               && rpm <= m->ShiftDownRPM[m->CurrentGear]) {"),
    ("mm-ca-down-rpm-stale", MMC,
     "            m->CurrentGear = m->CurrentGear - 1;\n"
     "            rpm = w * cti->DriveTrain.GearRatios[m->CurrentGear];",
     "            m->CurrentGear = m->CurrentGear - 1;"),
    ("mm-ca-reverse-ratio", MMC,
     "        rpm = w * cti->DriveTrain.GearRatios[0];",
     "        rpm = w * cti->DriveTrain.GearRatios[1];"),
    ("mm-ca-reverse-gear", MMC,
     "        m->CurrentGear = REVERSE;",
     "        m->CurrentGear = NEUTRAL;"),
    ("mm-ca-neutral-is-reverse", MMC,
     "    } else if (desired == REVERSE) {",
     "    } else if (desired == NEUTRAL) {"),
    ("mm-ca-no-idle-floor", MMC,
     "    if (rpm < cti->Engine.IdleRPM)\n        rpm = cti->Engine.IdleRPM;",
     "    if (0)\n        rpm = cti->Engine.IdleRPM;"),
    ("mm-ca-no-redline", MMC,
     "    else if (cti->Engine.MaxRPM < rpm)\n        rpm = cti->Engine.MaxRPM;",
     "    else if (0)\n        rpm = cti->Engine.MaxRPM;"),

    # -- GetGroundHeightAndWheelPos -------------------------------------------
    ("mm-gghawp-unrotated", MMC,
     "        eMulVector3(&pos[i], &rb->State.R, &r);",
     "        pos[i] = r;"),
    ("mm-gghawp-x", MMC,
     "        pos[i].x   = pos[i].x + rb->State.X.x;",
     "        pos[i].x   = pos[i].x;"),
    ("mm-gghawp-y", MMC,
     "        pos[i].y   = pos[i].y + rb->State.X.y;",
     "        pos[i].y   = pos[i].y;"),
    ("mm-gghawp-z", MMC,
     "        pos[i].z   = pos[i].z + rb->State.X.z;",
     "        pos[i].z   = pos[i].z;"),
    ("mm-gghawp-pad", MMC,
     "        pos[i].pad = pos[i].pad + rb->State.X.w;",
     "        pos[i].pad = 0.0f;"),
    ("mm-gghawp-one-normal", MMC,
     "        height[i] = ground(m->TC, &pos[i], &m->GroundNormal[i]);",
     "        height[i] = ground(m->TC, &pos[i], &m->GroundNormal[0]);"),
    ("mm-gghawp-no-tc", MMC,
     "        height[i] = ground(m->TC, &pos[i], &m->GroundNormal[i]);",
     "        height[i] = ground(NULL, &pos[i], &m->GroundNormal[i]);"),

    # -- ComputeSuspensionForces ------------------------------------------------
    ("mm-csf-axle-by-side", MMC,
     "&cti->Suspension[i / 2];",
     "&cti->Suspension[i & 1];"),
    ("mm-csf-off-ground-depth", MMC,
     "            x = -100.0f;",
     "            x = -1.0f;"),
    ("mm-csf-no-cosine", MMC,
     "            x = (height[i] - pos[i].z) / c;",
     "            x = height[i] - pos[i].z;"),
    ("mm-csf-radius-sign", MMC,
     "        x = x + cti->Wheels[i].Radius;",
     "        x = x - cti->Wheels[i].Radius;"),
    ("mm-csf-droop-stop", MMC,
     "        if (x < si->BumpStop[1]) {",
     "        if (x < si->BumpStop[0]) {"),
    ("mm-csf-droop-position", MMC,
     "            m->SuspensionPosition[i] = si->BumpStop[1];",
     "            m->SuspensionPosition[i] = x;"),
    ("mm-csf-droop-touches", MMC,
     "            m->SuspensionPosition[i] = si->BumpStop[1];\n"
     "            m->TouchingGround[i]     = 0;",
     "            m->SuspensionPosition[i] = si->BumpStop[1];\n"
     "            m->TouchingGround[i]     = 1;"),
    ("mm-csf-droop-penetration", MMC,
     "            m->TouchingGround[i]     = 0;\n"
     "            m->GroundPenetration[i]  = 0.0f;",
     "            m->TouchingGround[i]     = 0;\n"
     "            m->GroundPenetration[i]  = 1.0f;"),
    ("mm-csf-bump-stop", MMC,
     "        } else if (si->BumpStop[0] < x) {",
     "        } else if (si->BumpStop[1] < x) {"),
    ("mm-csf-bump-position", MMC,
     "            m->SuspensionPosition[i] = si->BumpStop[0];",
     "            m->SuspensionPosition[i] = x;"),
    ("mm-csf-bump-penetration", MMC,
     "            m->GroundPenetration[i]  = x - si->BumpStop[0];",
     "            m->GroundPenetration[i]  = 0.0f;"),
    ("mm-csf-travel-off-ground", MMC,
     "            m->SuspensionPosition[i] = x;\n"
     "            m->TouchingGround[i]     = 1;",
     "            m->SuspensionPosition[i] = x;\n"
     "            m->TouchingGround[i]     = 0;"),
    ("mm-csf-travel-penetration", MMC,
     "            m->GroundPenetration[i]  = 0.0f;\n        }\n\n        p = ",
     "            m->GroundPenetration[i]  = 1.0f;\n        }\n\n        p = "),
    ("mm-csf-velocity-absolute", MMC,
     "        v = (p - old) / max_s(gUglyTimestepHack, MV_MIN_DT);",
     "        v = p / max_s(gUglyTimestepHack, MV_MIN_DT);"),
    ("mm-csf-velocity-unfloored", MMC,
     "        v = (p - old) / max_s(gUglyTimestepHack, MV_MIN_DT);",
     "        v = (p - old) / gUglyTimestepHack;"),
    ("mm-csf-velocity-not-stored", MMC,
     "        m->SuspensionVelocity[i] = v;",
     "        m->SuspensionVelocity[i] = 0.0f;"),
    ("mm-csf-no-rest-load", MMC,
     "            f = m->RestLoad[i]\n",
     "            f = 0.0f\n"),
    ("mm-csf-progression-both-ways", MMC,
     "(max_s(p, 0.0f) * si->Progression",
     "(p * si->Progression"),
    ("mm-csf-progression-no-one", MMC,
     "* si->Progression\n                                        + 1.0f));",
     "* si->Progression));"),
    ("mm-csf-no-stiffness-travel", MMC,
     "                + p * (si->Stiffness * ",
     "                + (si->Stiffness * "),
    ("mm-csf-damping-at-rest", MMC,
     "si->Damping[(v <= 0.0f) ? 1 : 0];",
     "si->Damping[(v < 0.0f) ? 1 : 0];"),
    ("mm-csf-damping-swapped", MMC,
     "si->Damping[(v <= 0.0f) ? 1 : 0];",
     "si->Damping[(v <= 0.0f) ? 0 : 1];"),
    ("mm-csf-no-sway-bar", MMC,
     "            f = f + si->SwayBarStiffness\n",
     "            f = f + 0.0f\n"),
    ("mm-csf-sway-partner", MMC,
     "(p - m->SuspensionPosition[SwayBarTable[i]]);",
     "(p - m->SuspensionPosition[i ^ 2]);"),
    ("mm-csf-no-clamp", MMC,
     "            if (f < 0.0f)\n                f = 0.0f;",
     "            if (0)\n                f = 0.0f;"),
    ("mm-csf-airborne-force", MMC,
     "        f = 0.0f;\n        if (m->TouchingGround[i]) {",
     "        f = 1.0f;\n        if (m->TouchingGround[i]) {"),

    # -- Mellovator::ResolveForces --------------------------------------------
    ("mm-rf-hub-unrotated", MMC,
     "        bMulMatrixVec3(&r, R, &tmp);",
     "        r = tmp;"),
    ("mm-rf-slipping-kept", MMC,
     "        m->bSlipping[i] = 0;\n",
     ""),
    ("mm-rf-contact-x", MMC,
     "            W.x = rb->Velocity.x - rb->AngularVelocity.z * r.y;",
     "            W.x = rb->Velocity.x + rb->AngularVelocity.z * r.y;"),
    ("mm-rf-contact-y", MMC,
     "            W.y = rb->Velocity.y + rb->AngularVelocity.z * r.x;",
     "            W.y = rb->Velocity.y - rb->AngularVelocity.z * r.x;"),
    ("mm-rf-rear-steers", MMC,
     "            if (front)\n                h = h + (float)m->Steering",
     "            h = h + (float)m->Steering"),
    ("mm-rf-steering-signed", MMC,
     "                h = h + (float)m->Steering * MV_BAM_TO_RAD;",
     "                h = h + (float)(int16_t)m->Steering * MV_BAM_TO_RAD;"),
    ("mm-rf-cos-sign", MMC,
     "            c = bSinF(h + MV_HALF_PI);",
     "            c = bSinF(h - MV_HALF_PI);"),
    ("mm-rf-lng-sign", MMC,
     "            lng = W.x * c + W.y * s;",
     "            lng = W.x * c - W.y * s;"),
    ("mm-rf-lat-sign", MMC,
     "            lat = -W.x * s + W.y * c;",
     "            lat = W.x * s + W.y * c;"),
    ("mm-rf-slip-no-radius", MMC,
     "            slip = lng - m->State.ww[i] * m->CTI->Wheels[i].Radius;",
     "            slip = lng - m->State.ww[i];"),
    ("mm-rf-slip-x", MMC,
     "            m->WheelSlip[i].x = slip;",
     "            m->WheelSlip[i].x = lng;"),
    ("mm-rf-slip-y", MMC,
     "            m->WheelSlip[i].y = lat;",
     "            m->WheelSlip[i].y = slip;"),
    ("mm-rf-mag-manhattan", MMC,
     "            mag  = sqrtf(slip * slip + lat * lat);",
     "            mag  = fabsf(slip) + fabsf(lat);"),
    ("mm-rf-grip-base", MMC,
     "            grip = 1.0f;",
     "            grip = 0.5f;"),
    ("mm-rf-grip-quarter", MMC,
     "                grip = m->CurrentFrictionBoost * 0.25f;",
     "                grip = m->CurrentFrictionBoost * 0.5f;"),
    ("mm-rf-knee-unboosted", MMC,
     "            if (m->CurrentFrictionBoost * MV_SLIP_KNEE < mag)",
     "            if (MV_SLIP_KNEE < mag)"),
    ("mm-rf-knee-inclusive", MMC,
     "            if (m->CurrentFrictionBoost * MV_SLIP_KNEE < mag)",
     "            if (m->CurrentFrictionBoost * MV_SLIP_KNEE <= mag)"),
    ("mm-rf-slipping-threshold", MMC,
     "            if (6.0f < mag)",
     "            if (3.0f < mag)"),
    ("mm-rf-load-scale", MMC,
     "            sf   = m->SuspensionForce[i] * 1.25f;",
     "            sf   = m->SuspensionForce[i];"),
    ("mm-rf-longitudinal-sign", MMC,
     "            fl   = (-slip * grip) * sf;",
     "            fl   = (slip * grip) * sf;"),
    ("mm-rf-lateral-no-grip", MMC,
     "            flat = (-lat * grip) * sf;",
     "            flat = -lat * sf;"),
    ("mm-rf-rear-turned-back", MMC,
     "            if (front)\n                ang = (float)m->Steering",
     "            ang = (float)m->Steering"),
    ("mm-rf-back-cos", MMC,
     "            c = bSinF(ang + MV_HALF_PI);",
     "            c = bSinF(ang);"),
    ("mm-rf-fx-sign", MMC,
     "            F[i].x = c * fl - s * flat;",
     "            F[i].x = c * fl + s * flat;"),
    ("mm-rf-fy-sign", MMC,
     "            F[i].y = s * fl + c * flat;",
     "            F[i].y = s * fl - c * flat;"),
    ("mm-rf-airborne-fy", MMC,
     "            F[i].y = 0.0f;\n            F[i].x = 0.0f;",
     "            F[i].y = 1.0f;\n            F[i].x = 0.0f;"),
    ("mm-rf-airborne-fx", MMC,
     "            F[i].y = 0.0f;\n            F[i].x = 0.0f;",
     "            F[i].y = 0.0f;\n            F[i].x = 1.0f;"),
    ("mm-rf-no-load", MMC,
     "        F[i].z   = m->SuspensionForce[i];",
     "        F[i].z   = 0.0f;"),
    ("mm-rf-pad", MMC,
     "        F[i].pad = 0.0f;",
     "        F[i].pad = 1.0f;"),
    ("mm-rf-body-frame", MMC,
     "        bMulMatrixVec3(&W, R, &F[i]);",
     "        W = F[i];"),
    ("mm-rf-circle-squared", MMC,
     "            len = sqrtf(W.x * W.x + W.y * W.y);",
     "            len = W.x * W.x + W.y * W.y;"),
    ("mm-rf-circle-scale", MMC,
     "            lim = (m->SuspensionForce[i] * 1000.0f) * m->CurrentFrictionBoost;",
     "            lim = (m->SuspensionForce[i] * 100.0f) * m->CurrentFrictionBoost;"),
    ("mm-rf-circle-unboosted", MMC,
     "            lim = (m->SuspensionForce[i] * 1000.0f) * m->CurrentFrictionBoost;",
     "            lim = m->SuspensionForce[i] * 1000.0f;"),
    ("mm-rf-circle-off", MMC,
     "            if (lim < len) {",
     "            if (0) {"),
    ("mm-rf-circle-x-only", MMC,
     "                W.y = W.y * q;\n                W.x = W.x * q;",
     "                W.x = W.x * q;"),
    ("mm-rf-boost-scale", MMC,
     "                kb = cb * 2.5f + 1.0f;",
     "                kb = cb * 2.0f + 1.0f;"),
    ("mm-rf-boost-x-only", MMC,
     "            W.y = W.y * kb;\n            W.x = W.x * kb;",
     "            W.x = W.x * kb;"),
    ("mm-rf-hold-unlocked", MMC,
     "            if (m->BrakeLocked[i]\n                || (MV_HOLD_BRAKE",
     "            if (0\n                || (MV_HOLD_BRAKE"),
    ("mm-rf-hold-any-brake", MMC,
     "                || (MV_HOLD_BRAKE < m->Brake\n",
     "                || (0.0f <= m->Brake\n"),
    ("mm-rf-hold-any-speed", MMC,
     "                    && sqrtf(len2(&rb->Velocity)) < MV_HOLD_SPEED)) {",
     "                    && 1)) {"),
    ("mm-rf-hold-no-cosine", MMC,
     "                q = m->SuspensionForce[i] / R->v2.z;\n"
     "                W.x = W.x + -R->v2.x * q;",
     "                q = m->SuspensionForce[i];\n"
     "                W.x = W.x + -R->v2.x * q;"),
    ("mm-rf-hold-x", MMC,
     "                W.x = W.x + -R->v2.x * q;",
     "                W.x = W.x;"),
    ("mm-rf-hold-y", MMC,
     "                W.y = W.y + -R->v2.y * q;",
     "                W.y = W.y;"),
    ("mm-rf-bank-outside-circle", MMC,
     "            } else if (len < lim) {",
     "            } else {"),
    ("mm-rf-bank-no-cosine", MMC,
     "                q = m->SuspensionForce[i] / R->v2.z;\n"
     "                W.x = W.x + (-R->v2.x",
     "                q = m->SuspensionForce[i];\n"
     "                W.x = W.x + (-R->v2.x"),
    ("mm-rf-bank-x-signed", MMC,
     "(-R->v2.x * fabsf(R->v1.x))",
     "(-R->v2.x * R->v1.x)"),
    ("mm-rf-bank-y-signed", MMC,
     "(-R->v2.y * fabsf(R->v1.y))",
     "(-R->v2.y * R->v1.y)"),
    ("mm-rf-bank-x", MMC,
     "                W.x = W.x + (-R->v2.x * fabsf(R->v1.x)) * q;",
     "                W.x = W.x;"),
    ("mm-rf-bank-y", MMC,
     "                W.y = W.y + (-R->v2.y * fabsf(R->v1.y)) * q;",
     "                W.y = W.y;"),
    ("mm-rf-force-at-hub", MMC,
     "rigidbody_apply_force(rb, (const bVector4 *)&W, (const bVector4 *)&r);",
     "rigidbody_apply_force(rb, (const bVector4 *)&W, (const bVector4 *)&tmp);"),
    ("mm-rf-wheel-force-world", MMC,
     "        m->WheelForce[i].x = F[i].x;",
     "        m->WheelForce[i].x = W.x;"),
    ("mm-rf-wheel-force-y", MMC,
     "        m->WheelForce[i].y = F[i].y;",
     "        m->WheelForce[i].y = F[i].x;"),

    # -- Mellovator::BottomOut --------------------------------------------------
    ("mm-bo-inclusive", MMC,
     "        if (!(0.0f < m->GroundPenetration[i]))",
     "        if (!(0.0f <= m->GroundPenetration[i]))"),
    ("mm-bo-no-travel", MMC,
     "        tmp.z = tmp.z + m->SuspensionPosition[i];",
     "        tmp.z = tmp.z;"),
    ("mm-bo-unrotated", MMC,
     "        bMulMatrixVec3(&p, &rb->State.R, &tmp);",
     "        p = tmp;"),
    ("mm-bo-no-spin", MMC,
     "suspension_get_point_velocity(&pv, &rb->Velocity, &rb->AngularVelocity,",
     "suspension_get_point_velocity(&pv, &rb->Velocity, &rb->Velocity,"),
    ("mm-bo-sign", MMC,
     "        k = -dot3(&pv, n);",
     "        k = dot3(&pv, n);"),
    ("mm-bo-no-penalty", MMC,
     "        k = k * gGroundPenaltyImpulse;",
     "        k = k * 1.0f;"),
    ("mm-bo-no-mass", MMC,
     "        k = k * rb->Mass;",
     "        k = k * 1.0f;"),
    ("mm-bo-jx", MMC,
     "        j.x = n->x * k;",
     "        j.x = n->y * k;"),
    ("mm-bo-jz", MMC,
     "        j.z = n->z * k;",
     "        j.z = n->x * k;"),
    ("mm-bo-jw", MMC,
     "        j.w = n->pad * k;",
     "        j.w = k;"),
    ("mm-bo-total-last", MMC,
     "        total = total + k;",
     "        total = k;"),
    ("mm-bo-impulse-at-hub", MMC,
     "rigidbody_apply_impulse(rb, &j, (const bVector4 *)&p);",
     "rigidbody_apply_impulse(rb, &j, (const bVector4 *)&tmp);"),
    ("mm-bo-magnitude-not-summed", MMC,
     "cs->WheelBottomOutMagnitude[i] = cs->WheelBottomOutMagnitude[i] + k;",
     "cs->WheelBottomOutMagnitude[i] = k;"),

    # -- the accessors ----------------------------------------------------------
    ("mm-set-throttle", MMC,
     "{ m->Throttle = f; }",
     "{ m->Brake = f; }"),
    ("mm-set-brake", MMC,
     "{ m->Brake = f; }",
     "{ m->Throttle = f; }"),
    ("mm-set-steering", MMC,
     "{ m->Steering = bam; }",
     "{ m->Steering = (uint16_t)(bam >> 1); }"),
    ("mm-set-desired-gear", MMC,
     "{ m->DesiredGear = g; }",
     "{ m->CurrentGear = g; }"),
    ("mm-set-boost", MMC,
     "{ m->CurrentBoost = f; }",
     "{ m->CurrentFrictionBoost = f; }"),
    ("mm-set-friction-boost", MMC,
     "    m->CurrentFrictionBoost = f;\n}",
     "    m->CurrentBoost = f;\n}"),
    ("mm-get-rpm", MMC,
     "{ return m->RPM; }",
     "{ return m->Throttle; }"),
    ("mm-get-gear", MMC,
     "{ return m->CurrentGear; }",
     "{ return m->DesiredGear; }"),
    ("mm-get-touching", MMC,
     "    return m->TouchingGround[i];",
     "    return m->TouchingGround[0];"),
    ("mm-get-suspension-force", MMC,
     "    return m->SuspensionForce[i];",
     "    return m->SuspensionForce[0];"),
    ("mm-get-suspension-position", MMC,
     "    return m->SuspensionPosition[i];",
     "    return m->SuspensionPosition[0];"),
    ("mm-get-wheel-spin", MMC,
     "    return m->State.ww[i];",
     "    return m->State.ww[0];"),
    ("mm-get-slip", MMC,
     "    return &m->WheelSlip[i];",
     "    return &m->WheelSlip[0];"),
    ("mm-get-slipping", MMC,
     "    return m->bSlipping[i];",
     "    return m->bSlipping[0];"),

    # -- MellowMover: new, delete, the constructor ----------------------------
    ("mm-delete-kept", MMC,
     "    bSlotFree(MellowMoverSlotPool, p);",
     "    (void)p;"),
    ("mm-ctor-no-car", MMC,
     "    mm->pCar            = car;",
     "    mm->pCar            = NULL;"),
    ("mm-ctor-state-is-cars", MMC,
     "    mm->State           = cs;",
     "    mm->State           = &car->State;"),
    ("mm-ctor-body-not-component", MMC,
     "    physicssystem_add_component(&mm->Vehicle, (PhysicsComponent *)mm->pBody);",
     "    (void)0;"),
    ("mm-ctor-mv-no-tc", MMC,
     "                                      cs->pTopologyCoordinate);",
     "                                      NULL);"),
    ("mm-ctor-mv-not-component", MMC,
     "    physicssystem_add_component(&mm->Vehicle,\n"
     "                                (PhysicsComponent *)mm->pMellovator);",
     "    (void)0;"),
    ("mm-ctor-no-speed-limiter", MMC,
     "    mm->pBody->SpeedLimiter = mm->CTI->Control.SpeedLimiter;",
     "    mm->pBody->SpeedLimiter = 0.0f;"),
    ("mm-ctor-no-calibrate", MMC,
     "    // Before the wheels: Calibrate does not touch them.\n"
     "    mellowmover_calibrate(mm);",
     "    (void)0;"),
    ("mm-ctor-tyres-by-side", MMC,
     "                                    &mm->CTI->Tires[i / 2],",
     "                                    &mm->CTI->Tires[i & 1],"),
    ("mm-ctor-wheels-on-cs", MMC,
     "                                    &mm->CTI->Control, &mm->pCar->State);",
     "                                    &mm->CTI->Control, mm->State);"),
    ("mm-ctor-no-state-from-car", MMC,
     "    mellowmover_initialize_state_from_car(mm);\n"
     "    mellowmover_compute_auxiliaries(mm);",
     "    mellowmover_compute_auxiliaries(mm);"),
    ("mm-ctor-no-auxiliaries", MMC,
     "    mellowmover_initialize_state_from_car(mm);\n"
     "    mellowmover_compute_auxiliaries(mm);",
     "    mellowmover_initialize_state_from_car(mm);"),

    # -- the destructor ---------------------------------------------------------
    ("mm-dtor-aero-kept", MMC,
     "    aerodynamics_delete(mm->pAerodynamics);",
     "    (void)0;"),
    ("mm-dtor-wheels-kept", MMC,
     "            ((PhysicsDtorFn)e->fn)(vt_this(w, e), 3);",
     "            ((PhysicsDtorFn)e->fn)(vt_this(w, e), 2);"),
    ("mm-dtor-three-wheels", MMC,
     "    for (i = 0; i < 4; i++) {\n        Wheel *w = mm->pWheels[i];",
     "    for (i = 0; i < 3; i++) {\n        Wheel *w = mm->pWheels[i];"),
    ("mm-dtor-no-system", MMC,
     "    physicssystem_fini(&mm->Vehicle, 0);",
     "    (void)0;"),
    ("mm-dtor-no-carmover", MMC,
     "    carmover_destroy(&mm->Mover, 0);",
     "    (void)0;"),
    ("mm-dtor-always-delete", MMC,
     "    if (flags & 1)\n        mellowmover_delete(mm);",
     "    mellowmover_delete(mm);"),

    # -- MellowMover::Calibrate and InitializeStateFromCar --------------------
    ("mm-cal-no-body", MMC,
     "    rigidbody_calibrate(mm->pBody,\n",
     "    if (0) rigidbody_calibrate(mm->pBody,\n"),
    ("mm-cal-no-inertia", MMC,
     "    rigidbody_calculate_inertia_tensor(mm->pBody);",
     "    (void)0;"),
    ("mm-cal-speed-from-cs", MMC,
     "mm->pAerodynamics, mm->pCar->State.ForwardSpeed));",
     "mm->pAerodynamics, mm->State->ForwardSpeed));"),
    ("mm-isc-throttle", MMC,
     "    m->Throttle    = d->Throttle;",
     "    m->Throttle    = 0.0f;"),
    ("mm-isc-brake", MMC,
     "    m->Brake       = d->Brake;",
     "    m->Brake       = 0.0f;"),
    ("mm-isc-steering", MMC,
     "    m->Steering    = d->Steering;",
     "    m->Steering    = 0;"),
    ("mm-isc-gear", MMC,
     "    m->DesiredGear = d->DesiredGear;",
     "    m->DesiredGear = AUTOMATIC;"),
    ("mm-isc-spin-is-velocity", MMC,
     "                        (const bVector4 *)&cs->AngularVelocity);",
     "                        (const bVector4 *)&cs->Velocity);"),
    ("mm-isc-ww3", MMC,
     "                          cs->WheelAngularVelocity[3]);",
     "                          cs->WheelAngularVelocity[2]);"),
    ("mm-isc-no-auxiliaries", MMC,
     "    e = vt_slot(mm->Vehicle._vtable, PHYSICSSYSTEM_VT_COMPUTE_AUXILIARIES);\n"
     "    ((PhysicsVoidFn)e->fn)(vt_this(&mm->Vehicle, e));",
     "    (void)e;"),

    # -- MellowMover::UpdateCar -------------------------------------------------
    ("mm-uc-position", MMC,
     "    quad_to3(&cs->Position, &rb->State.X);",
     "    quad_to3(&cs->Position, &rb->Velocity);"),
    ("mm-uc-no-matrix", MMC,
     "    cs->BodyMatrix = rb->State.R;",
     "    (void)0;"),
    ("mm-uc-no-geometry", MMC,
     "    carstate_calculate_geometry_position(cs);",
     "    (void)0;"),
    ("mm-uc-velocity", MMC,
     "    quad_to3(&cs->Velocity, &rb->Velocity);",
     "    quad_to3(&cs->Velocity, &rb->AngularVelocity);"),
    ("mm-uc-speed-squared", MMC,
     "    cs->VelocityMagnitude = sqrtf(len2(&rb->Velocity));",
     "    cs->VelocityMagnitude = len2(&rb->Velocity);"),
    ("mm-uc-matrix-valid", MMC,
     "    cs->MatrixValid = 0;",
     "    cs->MatrixValid = 1;"),
    ("mm-uc-spin", MMC,
     "    quad_to3(&cs->AngularVelocity, &rb->AngularVelocity);",
     "    quad_to3(&cs->AngularVelocity, &rb->Velocity);"),
    ("mm-uc-angle-args", MMC,
     "bATan(rb->State.R.v0.x, rb->State.R.v0.y);",
     "bATan(rb->State.R.v0.y, rb->State.R.v0.x);"),
    ("mm-uc-clutch", MMC,
     "    cs->ClutchEngaged = 1;",
     "    cs->ClutchEngaged = 0;"),
    ("mm-uc-skid-left", MMC,
     "    cs->SkidLeft  = 0.0f;",
     "    cs->SkidLeft  = 1.0f;"),
    ("mm-uc-skid-right", MMC,
     "    cs->SkidRight = 0.0f;",
     "    cs->SkidRight = 1.0f;"),
    ("mm-uc-forward-axis", MMC,
     "dot3(&cs->Velocity, &mm->pBody->State.R.v0);",
     "dot3(&cs->Velocity, &mm->pBody->State.R.v1);"),
    ("mm-uc-angle-still", MMC,
     "        angle = cs->WheelAngle[i] + dt * m->State.ww[i];",
     "        angle = cs->WheelAngle[i];"),
    ("mm-uc-rear-steers", MMC,
     "        if (w->WI->WheelNumber < 2)",
     "        if (w->WI->WheelNumber < 4)"),
    ("mm-uc-no-steer", MMC,
     "                                       (uint16_t)ee_trunc_w(steer),",
     "                                       (uint16_t)0,"),
    ("mm-uc-spin-wheel0", MMC,
     "                                       m->State.ww[i],\n",
     "                                       m->State.ww[0],\n"),
    ("mm-uc-no-travel", MMC,
     "                                       m->SuspensionPosition[i]);",
     "                                       0.0f);"),
    ("mm-uc-always-touching", MMC,
     "                                           (int8_t)m->TouchingGround[i]);",
     "                                           (int8_t)1);"),
    ("mm-uc-cs-slip-y", MMC,
     "        cs->WheelSlip[i].y        = m->WheelSlip[i].y;",
     "        cs->WheelSlip[i].y        = m->WheelSlip[i].x;"),
    ("mm-uc-cs-slip-x", MMC,
     "        cs->WheelSlip[i].x        = m->WheelSlip[i].x;",
     "        cs->WheelSlip[i].x        = m->WheelSlip[i].y;"),
    ("mm-uc-traction", MMC,
     "        cs->WheelTractionUsage[i] = 0.0f;",
     "        cs->WheelTractionUsage[i] = 1.0f;"),
    ("mm-uc-z-force", MMC,
     "        cs->WheelZForce[i]        = m->SuspensionForce[i];",
     "        cs->WheelZForce[i]        = 0.0f;"),
    ("mm-uc-wheel-touching", MMC,
     "        w->TouchingGround         = (m->TouchingGround[i] != 0);",
     "        w->TouchingGround         = 1;"),
    ("mm-uc-wheel-slip0", MMC,
     "        w->Slip[0]     = m->WheelSlip[i].x;",
     "        w->Slip[0]     = m->WheelSlip[i].y;"),
    ("mm-uc-wheel-slip1", MMC,
     "        w->Slip[1]     = m->WheelSlip[i].y;",
     "        w->Slip[1]     = m->WheelSlip[i].x;"),
    ("mm-uc-wheel-slipping", MMC,
     "        w->Slipping    = (uint8_t)m->bSlipping[i];",
     "        w->Slipping    = 0;"),
    ("mm-uc-wheel-current-slip", MMC,
     "        w->CurrentSlip = m->WheelSlip[i].x;",
     "        w->CurrentSlip = m->WheelSlip[i].y;"),
    ("mm-uc-skids-always", MMC,
     "        if (car_should_visual_effects_be_generated(mm->pCar))\n",
     "        if (1)\n"),
    ("mm-uc-skids-no-dt", MMC,
     "            wheel_maybe_make_skids(mm->pWheels[i], dt);",
     "            wheel_maybe_make_skids(mm->pWheels[i], 0.0f);"),
    ("mm-uc-gear", MMC,
     "    cs->CurrentGear = mm->pMellovator->CurrentGear;",
     "    cs->CurrentGear = mm->pMellovator->DesiredGear;"),
    ("mm-uc-rpm", MMC,
     "    cs->RPM         = mm->pMellovator->RPM;",
     "    cs->RPM         = 0.0f;"),

    # -- MellowMover::ComputeAuxiliaries and ResolveForces --------------------
    ("mm-mca-no-second-pass", MMC,
     "    if (0.0f < mellovator_bottom_out(mm->pMellovator, mm->State))\n"
     "        physicssystem_compute_auxiliaries(&mm->Vehicle);",
     "    (void)mellovator_bottom_out(mm->pMellovator, mm->State);"),
    ("mm-mca-always-second-pass", MMC,
     "    if (0.0f < mellovator_bottom_out(mm->pMellovator, mm->State))\n"
     "        physicssystem_compute_auxiliaries(&mm->Vehicle);",
     "    (void)mellovator_bottom_out(mm->pMellovator, mm->State);\n"
     "    physicssystem_compute_auxiliaries(&mm->Vehicle);"),
    ("mm-mca-bottom-on-cars-state", MMC,
     "    if (0.0f < mellovator_bottom_out(mm->pMellovator, mm->State))",
     "    if (0.0f < mellovator_bottom_out(mm->pMellovator, &mm->pCar->State))"),
    ("mm-mca-no-forces", MMC,
     "    e = vt_slot(mm->Vehicle._vtable, PHYSICSSYSTEM_VT_RESOLVE_FORCES);\n"
     "    ((PhysicsVoidFn)e->fn)(vt_this(&mm->Vehicle, e));",
     "    (void)e;"),
    ("mm-mrf-no-mellovator", MMC,
     "    ((PhysicsVoidFn)e->fn)(vt_this(m, e));\n    aerodynamics_resolve_forces",
     "    (void)e;\n    aerodynamics_resolve_forces"),
    ("mm-mrf-no-aero", MMC,
     "    aerodynamics_resolve_forces(mm->pAerodynamics, NULL);",
     "    (void)0;"),
    ("mm-mrf-no-stabilizer", MMC,
     "    mellowmover_jump_stabilizer(mm);\n}",
     "}"),

    # -- MellowMover::SetBoost --------------------------------------------------
    ("mm-sb-aero-boost-is-f", MMC,
     "    mm->pAerodynamics->Boost = car->State.BoostFactor;",
     "    mm->pAerodynamics->Boost = f;"),
    ("mm-sb-draft", MMC,
     "    mm->pAerodynamics->Draft = 1.0f - car->DraftFactor;",
     "    mm->pAerodynamics->Draft = car->DraftFactor;"),
    ("mm-sb-catch-up", MMC,
     "    mm->pBody->CatchUpMultiplier = f;",
     "    mm->pBody->CatchUpMultiplier = 1.0f;"),
    ("mm-sb-mph", MMC,
     "    if (30.0f < car->State.ForwardSpeed * MV_MS_TO_MPH",
     "    if (40.0f < car->State.ForwardSpeed * MV_MS_TO_MPH"),
    ("mm-sb-mode", MMC,
     "        && car->State.DriverMode == 1)",
     "        && car->State.DriverMode == 0)"),
    ("mm-sb-friction-unboosted", MMC,
     "        fb = f * MV_HIGH_SPEED_FRICTION;",
     "        fb = MV_HIGH_SPEED_FRICTION;"),
    ("mm-sb-friction-is-f", MMC,
     "    mellovator_set_current_friction_boost(mm->pMellovator, fb);",
     "    mellovator_set_current_friction_boost(mm->pMellovator, f);"),
    ("mm-sb-boost-is-fb", MMC,
     "    mellovator_set_current_boost(mm->pMellovator, f);",
     "    mellovator_set_current_boost(mm->pMellovator, fb);"),

    # -- MellowMover::JumpStabilizer --------------------------------------------
    ("mm-js-one-wheel", MMC,
     "    if (n < 2) {",
     "    if (n < 1) {"),
    ("mm-js-no-mass", MMC,
     "        k = rb->Mass * graph_get_value(&MellowJumpStabilization,",
     "        k = graph_get_value(&MellowJumpStabilization,"),
    ("mm-js-squared-spin", MMC,
     "                                       sqrtf(len2(w)));",
     "                                       len2(w));"),
    ("mm-js-not-negated", MMC,
     "        k = -k;\n",
     ""),
    ("mm-js-mx", MMC,
     "        m.x = w->x * k;",
     "        m.x = w->y * k;"),
    ("mm-js-mw", MMC,
     "        m.w = w->w * k;",
     "        m.w = 0.0f;"),
    ("mm-js-one-wheel-turns", MMC,
     "    if (n != 0)\n        return;",
     "    if (n > 1)\n        return;"),
    ("mm-js-upright-axis", MMC,
     "    if (!(MV_UPRIGHT < car->State.BodyMatrix.v2.z))",
     "    if (!(MV_UPRIGHT < car->State.BodyMatrix.v1.z))"),
    ("mm-js-upright-inclusive", MMC,
     "    if (!(MV_UPRIGHT < car->State.BodyMatrix.v2.z))",
     "    if (!(MV_UPRIGHT <= car->State.BodyMatrix.v2.z))"),
    ("mm-js-heading-z", MMC,
     "        h.z = 0.0f;",
     "        h.z = car->State.Velocity.z;"),
    ("mm-js-heading-w", MMC,
     "        h.w = car->State.Velocity.pad;",
     "        h.w = 0.0f;"),
    ("mm-js-heading-unit", MMC,
     "        normalize4(&h);\n        cross3(&m, &h, &bm->v0);",
     "        cross3(&m, &h, &bm->v0);"),
    ("mm-js-yaw-axis-order", MMC,
     "        cross3(&m, &h, &bm->v0);",
     "        cross3(&m, &bm->v0, &h);"),
    ("mm-js-yaw-gain", MMC,
     "k = mm->pBody->Mass * ((dot3(&h, &bm->v0) - 1.0f) * 100.0f);",
     "k = mm->pBody->Mass * ((dot3(&h, &bm->v0) - 1.0f) * 50.0f);"),
    ("mm-js-no-yaw", MMC,
     "        rigidbody_apply_moment(mm->pBody, &m);\n\n        // Level",
     "\n        // Level"),
    ("mm-js-up-w", MMC,
     "        u.w = 0.0f;",
     "        u.w = 1.0f;"),
    ("mm-js-up-down", MMC,
     "        u.z = 1.0f;",
     "        u.z = -1.0f;"),
    ("mm-js-side-unit", MMC,
     "        cross3(&s, &u, &bm->v0);\n        normalize4(&s);",
     "        cross3(&s, &u, &bm->v0);"),
    ("mm-js-level-axis-order", MMC,
     "        cross3(&m, &s, &bm->v1);",
     "        cross3(&m, &bm->v1, &s);"),
    ("mm-js-level-gain", MMC,
     "k = mm->pBody->Mass * ((dot3(&s, &bm->v1) - 1.0f) * 100.0f);",
     "k = mm->pBody->Mass * ((dot3(&s, &bm->v1) - 1.0f) * 50.0f);"),
    ("mm-js-no-level", MMC,
     "        rigidbody_apply_moment(mm->pBody, &m);\n    }\n}",
     "    }\n}"),

    # -- MellowMover::Move ------------------------------------------------------
    ("mm-move-no-calibrate", MMC,
     "    (void)bGetTicker();\n    mellowmover_calibrate(mm);",
     "    (void)bGetTicker();"),
    ("mm-move-throttle", MMC,
     "    m->Throttle     = d->Throttle;",
     "    m->Throttle     = 0.0f;"),
    ("mm-move-brake", MMC,
     "    m->Brake        = d->Brake;",
     "    m->Brake        = 0.0f;"),
    ("mm-move-ground-effect", MMC,
     "    a->GroundEffect = (float)cs->nWheelsTouchingGround * 0.25f;",
     "    a->GroundEffect = (float)cs->nWheelsTouchingGround * 0.5f;"),
    ("mm-move-steering", MMC,
     "    m->Steering     = d->Steering;",
     "    m->Steering     = 0;"),
    ("mm-move-gear", MMC,
     "    m->DesiredGear  = d->DesiredGear;",
     "    m->DesiredGear  = AUTOMATIC;"),
    ("mm-move-aero-throttle", MMC,
     "    a->Throttle     = d->Throttle;",
     "    a->Throttle     = 0.0f;"),
    ("mm-move-bottom-three", MMC,
     "    for (i = 3; i >= 0; i--)",
     "    for (i = 3; i > 0; i--)"),
    ("mm-move-no-boost", MMC,
     "    mellowmover_set_boost(mm, mm->pCar->State.BoostFactor);",
     "    mellowmover_set_boost(mm, 1.0f);"),
    ("mm-move-steps-truncated", MMC,
     "    n = ee_trunc_w(dt / MaxiMellowTimeStep) + 1;",
     "    n = ee_trunc_w(dt / MaxiMellowTimeStep);"),
    ("mm-move-steps-ceiling", MMC,
     "    n = ee_trunc_w(dt / MaxiMellowTimeStep) + 1;",
     "    n = (int32_t)ceilf(dt / MaxiMellowTimeStep);"),
    ("mm-move-step-maxi", MMC,
     "    step = dt / (float)n;",
     "    step = MaxiMellowTimeStep;"),
    ("mm-move-ugly-frame", MMC,
     "        gUglyTimestepHack = step;",
     "        gUglyTimestepHack = dt;"),
    ("mm-move-no-orthonormalize", MMC,
     "        eOrthonormalizeMatrix(&mm->pBody->State.R, &mm->pBody->State.R);",
     "        (void)0;"),
    ("mm-move-update-step", MMC,
     "    mellowmover_update_car(mm, dt);",
     "    mellowmover_update_car(mm, step);"),
    ("mm-move-returns-step", MMC,
     "    return dt;\n}",
     "    return step;\n}"),

    # -- the tables -------------------------------------------------------------
    ("mm-vt-mv-rf-is-ca", MMC,
     "    { 0, 0, (VtFn)vt_Mellovator_ResolveForces },",
     "    { 0, 0, (VtFn)vt_Mellovator_ComputeAuxiliaries },"),
    ("mm-vt-mv-get-is-set", MMC,
     "    { 0, 0, (VtFn)vt_Mellovator_GetState_Pf },",
     "    { 0, 0, (VtFn)vt_Mellovator_SetState_Pf },"),
    ("mm-vt-mv-ca-is-rf", MMC,
     "    { 0, 0, (VtFn)vt_Mellovator_ComputeAuxiliaries },",
     "    { 0, 0, (VtFn)vt_Mellovator_ResolveForces },"),
    ("mm-vt-vehicle-delta", MMC,
     "#define VEHICLE_DELTA ((int16_t)-(int)offsetof(MellowMover, Vehicle))",
     "#define VEHICLE_DELTA ((int16_t)0)"),
    ("mm-vt-vehicle-ca-is-rf", MMC,
     "    { VEHICLE_DELTA, 0, (VtFn)vt_MellowMover_ComputeAuxiliaries },",
     "    { VEHICLE_DELTA, 0, (VtFn)vt_MellowMover_ResolveForces },"),
    ("mm-vt-vehicle-rf-is-ca", MMC,
     "    { VEHICLE_DELTA, 0, (VtFn)vt_MellowMover_ResolveForces },",
     "    { VEHICLE_DELTA, 0, (VtFn)vt_MellowMover_ComputeAuxiliaries },"),
]

# Each of these changes nothing the shipped code can see, for the reason
# beside it, checked against the image.
EQUIVALENT = {
    "mm-hub-pad":
        "the hub's w lane goes only to bMulMatrixVec3 (0x002427b0), "
        "directly and through eMulVector3, which stores 1.0 over it "
        "(`swc1 $f0,12(sp)`) before the multiply",
    "mm-rf-pad":
        "F's w lane goes only to bMulMatrixVec3, which stores 1.0 over it "
        "before the multiply; WheelForce keeps x and y",
    "mm-gghawp-pad":
        "the hub's w lane goes only to GetElevation (0x0014f418), which "
        "reads x, y and z (`lwc1 0/4/8(s1)`) and hands the vector on to "
        "bBoundingBoxIsInside and SetInterestBBox as a bVector2; the "
        "suspension reads z alone",
    "mm-mv-dtor-vtable-kept":
        "~PhysicsComponent (0x00192438) stores its own vptr over this one "
        "before anything reads it",
    "mm-csf-damping-at-rest":
        "the two tests differ only at v == 0, where v * Damping[k] is a "
        "zero for either k, and a zero of either sign added to f leaves f: "
        "f is RestLoad plus a product, never a negative zero",
}


def mutate_pass(only=None):
    ctis = cti_records()
    base = model(ctis)
    caught = 0
    survived = []
    missing = []
    equivalent = []
    todo = [m for m in MUTATIONS if only is None or m[0] in only]
    if only is not None:
        unknown = sorted(set(only) - {m[0] for m in MUTATIONS})
        if unknown:
            sys.exit("no such mutation: " + " ".join(unknown))

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
    consts = constant_problems()
    for p in consts:
        print("constant: " + p)
    if probs or consts:
        sys.exit(1)

    if args.mutate:
        sys.exit(mutate_pass(args.only.split(",") if args.only else None))

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
