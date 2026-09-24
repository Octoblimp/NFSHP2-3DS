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
    3DS Files/source/collisionbody.c     CarCollisionBody's SetupPhysicsPointers
                                         and SetToPhysicsMode.
    3DS Files/source/cardriver.c         NullDriver's five and both driver
                                         tables, called through them.

The oracle and the machinery are mellowmover_check's and physicscar_check's,
imported: the header parse and the check against mdebug, the generated dump
functions, the emulator's stubs for the slot pools, the terrain and the
ticker. What is this slice's is here: the general heap, the stand-ins for
the eight classes task 26 has not ported, the labels, and the scenarios.

**The heap.** Every `new` in the four methods but NullMover's and
MellowMover's is `bMalloc(size, name, 0, 16)`, and every delete is
`__builtin_delete`. Both sides log each one -- the name, the image's size
(the harness maps the four ported records' host sizes back), the flags
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

    python tools/carmode_check.py
    python tools/carmode_check.py --mutate
    python tools/carmode_check.py --dump out/carmode
"""
import argparse
import os
import struct
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hostbuild
import mellowmover_check as mmc
import physicscar_check as pcc
from mipsemu import M32, s32
from physicscar_check import LAYOUT, OFF, fb, hexw

ROOT = pcc.ROOT
NL = pcc.NL
HARNESS = ROOT / "tools" / "src" / "carmode_test.c"
CMC = "3DS Files/source/carmodes.c"
CMH = "3DS Files/source/carmodes.h"
CCC = "3DS Files/source/carcontroller.c"
CBC = "3DS Files/source/collisionbody.c"
CDC = "3DS Files/source/cardriver.c"

SOURCES_PORT = [CMC, CCC, CBC, CDC,
                "3DS Files/source/drivetarget.c",
                "3DS Files/source/trackroute.c",
                "3DS Files/source/trackpath.c",
                "3DS Files/source/quickspline.c",
                "3DS Files/source/bchunk.c"]
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
CAR = {"pCarTypeInfo": 12, "MyDriver": 20, "TheControlMode": 32,
       "TheMovementMode": 36, "pCarController": 40, "pCarDriver": 44,
       "pCarMover": 48, "pDynamicCollisionBody": 52, "State": 64,
       "FrictionBoost": 1092, "DraftFactor": 1096, "RenderingEnabled": 1160}
CB = [("CollisionBody", "Type", 12, 8),
      ("DynamicCollisionBody", "PhysicsMode", 84, 32),
      ("DynamicCollisionBody", "pSystem", 92, 32),
      ("DynamicCollisionBody", "pBody", 96, 32),
      ("CarCollisionBody", "pCar", 256, 32)]
CB_TYPE, CB_MODE, CB_SYSTEM, CB_BODY, CB_CAR = (x[2] for x in CB)
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
    for rec, name, off, bits in CB:
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
}

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
    # The image's sizes for the four records the port allocates itself,
    # which the harness's log shows in place of the host's.
    w("#define CM_IMG_PHYSICSCAR %d" % pcc.PC_SIZE)
    w("#define CM_IMG_NULLCONTROLLER %d" % 12)
    w("#define CM_IMG_NULLDRIVER %d" % DRIVER_SIZE)
    w("#define CM_IMG_REALCONTROLLER %d" % 84)
    w("#define CM_STRAY %d" % STRAY)
    w("#define CM_NORMAL_X 0x%08xu" % pcc.NORMAL[0])
    w("#define CM_NORMAL_Y 0x%08xu" % pcc.NORMAL[1])
    w("#define CM_NORMAL_Z 0x%08xu" % pcc.NORMAL[2])
    w("static const uint32_t CM_TERRAIN[4][3] = {%s};" % ", ".join(
        "{%s}" % pcc.c_u32_list(v) for v in pcc.TERRAIN))
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
    def __init__(self, cti):
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
        self.car = self.car2 = self.ccb = self.ccb2 = 0
        self.di = self.tgt = 0
        e.stub("bMalloc__FiPCcii", self.on_malloc)
        e.stub("__builtin_delete", self.on_free)
        e.stub("bFree__FPv", self.on_free)
        self.install_fakes()
        self.put(pcc.G_USENEWCAL, 1)
        self.put(pcc.G_UGLY, fb(1.0))

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
            o.append(("car", self.car, CAR_SIZE))
            o.append(("car2", self.car2, CAR_SIZE))
            o.append(("ccb", self.ccb, CCB_SIZE))
            o.append(("ccb2", self.ccb2, CCB_SIZE))
            o.append(("cti", self.cti, 1368))
            o.append(("topo", pcc.TOPO, 16))
            o.append(("di", self.di, 20))
            o.append(("tgt", self.tgt, TGT_SIZE))
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
        return self.out


def cti_record():
    return pcc.cti_records()[0]


def model(cti=None):
    return Model(cti or cti_record()).run()


# ================================================================ the build

def build_harness(tmp, cti, name="carmode_test"):
    text = generate(cti) + HARNESS.read_text(encoding="utf-8")
    src = Path(tmp) / "carmode_test.c"
    src.write_text(text, encoding="utf-8", newline=NL)
    return hostbuild.build(tmp, [str(src)] + SOURCES_PORT, name=name)


run_harness = pcc.run_harness
diff = pcc.diff

# ============================================================ the mutations

CCH = "3DS Files/source/carcontroller.h"
CDH = "3DS Files/source/cardriver.h"
MOVE_DTOR = "CARMOVER_VT_DTOR);" + NL + "        ((DtorFn)e->fn)(vt_this(old, e), "
CTRL_DTOR = "CARCONTROLLER_VT_DTOR);" + NL + "        ((DtorFn)e->fn)(vt_this(old, e), "
STPM_SKIP = ("    if (c->TheMovementMode == PHYSICS_MOVEMENT" + NL
             + "        || c->TheMovementMode == MELLOW_MOVEMENT)" + NL
             + "        return;" + NL
             + "    car_set_movement_mode(c, MELLOW_MOVEMENT);")
CC_SKIP = ("    if (mine->TheMovementMode == PHYSICS_MOVEMENT" + NL
           + "        || mine->TheMovementMode == MELLOW_MOVEMENT)")
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
    ("size-trafficcar", CMH, "#define TRAFFICCAR_SIZE       36",
     "#define TRAFFICCAR_SIZE       40"),
    ("size-deliverymover", CMH, "#define DELIVERYMOVER_SIZE   192",
     "#define DELIVERYMOVER_SIZE   196"),
    ("size-copmover", CMH, "#define COPMOVER_SIZE        112",
     "#define COPMOVER_SIZE        116"),
    ("size-beltmover", CMH, "#define BELTMOVER_SIZE        72",
     "#define BELTMOVER_SIZE        76"),
    ("size-realcontroller", CMH,
     "#define REALCONTROLLER_SIZE  ((int)sizeof(RealController))",
     "#define REALCONTROLLER_SIZE  ((int)sizeof(RealController) + 4)"),
    ("size-aidriver", CMH, "#define AIDRIVER_SIZE        720",
     "#define AIDRIVER_SIZE        724"),
    ("size-trafficdriver", CMH, "#define TRAFFICDRIVER_SIZE   720",
     "#define TRAFFICDRIVER_SIZE   724"),
    ("size-copdriver", CMH, "#define COPDRIVER_SIZE        76",
     "#define COPDRIVER_SIZE        80"),
    ("pool-not-16", CMH, "#define CAR_MEMORY_POOL 16",
     "#define CAR_MEMORY_POOL 0"),

    # ---- the null controller and its driver
    ("nc-size", CMC,
     "    ctrl = (NullController *)bMalloc((int)sizeof(NullController),",
     "    ctrl = (NullController *)bMalloc((int)sizeof(NullController) + 4,"),
    ("nc-name", CMC, '"NullController", 0, CAR_MEMORY_POOL);',
     '"NullControl", 0, CAR_MEMORY_POOL);'),
    ("nc-no-base-ctor", CMC, "    carcontroller_init(&ctrl->Base, c);" + NL,
     ""),
    ("nc-no-vptr", CMC,
     "    ctrl->Base._vtable = NULLCONTROLLER_VTABLE;" + NL, ""),
    ("nd-size", CMC, 'bMalloc((int)sizeof(NullDriver), "NullDriver", 0,',
     'bMalloc((int)sizeof(NullDriver) + 4, "NullDriver", 0,'),
    ("nd-no-base-ctor", CMC, "    cardriver_init(&drv->Base);" + NL, ""),
    ("nd-vptr-before-ctor", CMC, moved(
        "    drv->Base._vtable = NULLDRIVER_VTABLE;",
        "    cardriver_init(&drv->Base);", False)),
    ("nc-no-driver", CMC, "    ctrl->Base.Driver = &drv->Base;" + NL, ""),
    ("nd-no-vptr", CMC, "    drv->Base._vtable = NULLDRIVER_VTABLE;" + NL, ""),

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
    ("stpm-physics-not-skipped", CMC, STPM_SKIP,
     "    if (c->TheMovementMode == MELLOW_MOVEMENT)" + NL + "        return;"
     + NL + "    car_set_movement_mode(c, MELLOW_MOVEMENT);"),
    ("stpm-mellow-not-skipped", CMC, STPM_SKIP,
     "    if (c->TheMovementMode == PHYSICS_MOVEMENT)" + NL + "        return;"
     + NL + "    car_set_movement_mode(c, MELLOW_MOVEMENT);"),
    ("stpm-goes-physics", CMC,
     "        return;" + NL + "    car_set_movement_mode(c, MELLOW_MOVEMENT);",
     "        return;" + NL + "    car_set_movement_mode(c, PHYSICS_MOVEMENT);"),
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
     "    if (mine->TheMovementMode == MELLOW_MOVEMENT)"),
    ("cc-stpm-mellow-not-skipped", CCC, CC_SKIP,
     "    if (mine->TheMovementMode == PHYSICS_MOVEMENT)"),
    ("cc-stpm-other-car", CCC,
     "    car_set_movement_mode(mine, MELLOW_MOVEMENT);",
     "    car_set_movement_mode(car, MELLOW_MOVEMENT);"),
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
     "nullcontroller_get_current_route(NullController *c)" + NL + "{" + NL
     + "    (void)c;" + NL + "    return NULL;",
     "nullcontroller_get_current_route(NullController *c)" + NL + "{" + NL
     + "    (void)c;" + NL + "    return (TrackRoute *)c;"),
    ("nc-point-not-null", CCC,
     "_point(NullController *c)" + NL + "{" + NL + "    (void)c;" + NL
     + "    return NULL;",
     "_point(NullController *c)" + NL + "{" + NL + "    (void)c;" + NL
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
    ("ccb-setup-keeps-system", CBC, "    d->pSystem = NULL;" + NL, ""),
    ("ccb-setup-keeps-body", CBC, "    d->pBody = NULL;" + NL, ""),
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
]

EQUIVALENT = {}


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
    print("%d transitions, %d lines, %d differ"
          % (len(MOVE_WALK) + len(CTRL_WALK) - 2, len(harness), n))
    sys.exit(1 if n else 0)


if __name__ == "__main__":
    main()
