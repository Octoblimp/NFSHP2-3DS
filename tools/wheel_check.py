"""Cross-check 3DS Files/source/wheel.c against a model of Wheel.

Wheel is the seventh slice of task 25, after CarState, Engine, CarTypeInfo,
CarDriver, Steering, RigidBody and Suspension. It is the tyre: the contact
patch, the friction circle the patch can deliver, the spin state of the rim
and the two queries the suspension makes of the ground underneath.

This model is written from the disassembly at 0x00199c40..0x0019b9e8 and
from the `.mdebug` layout, not from the C. The thirteen tuning globals, the
eight curve tables and the whole of Wheel's own literal pool at
0x00321788..0x003217fc are read straight out of `PS2 Files/NFSHP2.ELF`
rather than copied from the header, so a typo in either place shows as a
diff instead of agreeing with itself.

Six things the transcript exists to pin down.

**ExchangeZForces returns zero on every path.** Both arms end `mtc1
zero,$f0` before `jr ra` -- the airborne arm stores a zero into ZForce and
returns the same register, and the loaded arm stores the real force into
ZForce and then clears $f0 on the way out. Suspension::ResolveForces writes
what comes back straight into its GroundForce, so that field is zero on
every frame of the shipped game. The `ex` scenario prints the return
alongside the ZForce it computed, so the two cannot be confused.

**CheckTerrain forwards its terrain out-parameter.** a2 arrives holding
it and nothing before the `jal` touches it; the `move t0,zero` at
0x0019a300 is the fifth argument, GetElevation's `bool *`, which is register
8, not 6. GetElevation writes through a non-NULL pointer (0x0014f714), so
the `lw a1,0(s4)` after the call feeds GetRoadNoise the terrain just
reported. An earlier pass read that `move` as `a2` and ported a NULL, and
the model agreed with it; a re-read of the raw word (rd = 8) caught it. The
harness's
stand-in writes 77 through the pointer, so a port that dropped it would show
the stale terrain instead.

**The slip angle folds twice and both folds use the object's own pi.** The
pool holds 0x40490fd0, which is 3.14159012 -- one ulp below the pi in
bMath's pool and about 2.4e-7 below the real thing. Folding with a rounder
pi moves the last bit of every angle behind the wheel's x axis, so the two
constants are read from the image rather than written down.

**GetPilotFactor blends in double.** fptodp / dpsub / dpmul / dpadd /
dptofp, with the 1.0 built by `ori a0,zero,0xffc0` and `dsll32 a0,a0,14`.
Spelling the same blend in float moves the result on most inputs, which is
what the `pf` sweep is for.

**Two globals ship at values that hide the code reading them.**
gUseNewTireForces is 1, so the old single-curve tyre model is dead code in
the shipped build; gWheelForceFrame is 1, so three of the four ground-force
frames are. Both are .sdata the debug menu moved, so the transcript runs
each of them, which is where those arms actually get pinned.

**A negative slip angle would index behind the load-sensitivity array.**
`slti v0,s1,6` is signed and there is no floor on the index. Every caller
passes an absolute value so it cannot happen in the game; the `lf` sweep
records the shape of the guard rather than adding one.

Usage:

    python tools/wheel_check.py
    python tools/wheel_check.py --mutate
    python tools/wheel_check.py --dump out/wheel
"""
import argparse
import difflib
import math
import os
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hostbuild
import mipsdis
import retail_model
import bmath_check as BM
import bvector_check as BV
import engine_check as EN          # its Table model, not its Engine
import carstate_check as CST       # its CarState, for SetState(CarState *)
import emath_check as EM           # and the eMulMatrix that places a wheel

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

SOURCES = [
    "tools/src/wheel_test.c",
    "3DS Files/source/wheel.c",
    "3DS Files/source/replay.c", "3DS Files/source/p32.c",
    "3DS Files/source/suspension.c",
    "3DS Files/source/steering.c",
    "3DS Files/source/rigidbody.c",
    "3DS Files/source/carstate.c",   # wheel.c's SetState(CarState *, ...)
    "3DS Files/source/emath.c",      # and the eMulMatrix it calls
    "3DS Files/source/bmatrix.c",
    "3DS Files/source/table.c",
    "3DS Files/source/vtable.c",     # rigidbody.c's DoSnapshot
    "3DS Files/source/bvector.c",
    "3DS Files/source/bmath.c",
    "3DS Files/source/bmathtab.c",
]

WH = "3DS Files/source/wheel.h"
TT = "3DS Files/source/terraintype.h"
WC = "3DS Files/source/wheel.c"
TC = "3DS Files/source/table.c"

# The host this runs on, not the handheld. Every PS2 offset below is stated
# in PS2 terms and widened from here, the same way the header's assert does.
PTR = 8
SLACK = PTR - 4

f32 = BV.f32
fmul, fadd, fsub, fdiv, fneg = BV.fmul, BV.fadd, BV.fsub, BV.fdiv, BV.fneg
fsqrt, fabs32 = BV.fsqrt, BV.fabs32
bSinF, bATan = BM.bSinF, BM.bATan

ZERO = f32(0.0)
ONE = f32(1.0)


def g9(x):
    return "%.9g" % x


def fbits(x):
    """The raw word behind a float, for the places the transcript prints a
    serialised record rather than a number."""
    return struct.unpack("<I", struct.pack("<f", x))[0]


def pad(s, n):
    return s + " " * (n - len(s)) if len(s) < n else s


OUT = []


def emit(s):
    OUT.append(s)


def pf(tag, x):
    emit("%s %s" % (tag, g9(x)))


def pint(tag, x):
    emit("%s %d" % (tag, x))


def pv(tag, v):
    emit("%s %s %s %s %s" % (tag, g9(v[0]), g9(v[1]), g9(v[2]), g9(v[3])))


def pm(tag, m):
    flat = [c for row in m for c in row]
    for j in range(16):
        emit("%s[%2d] %s" % (tag, j, g9(flat[j])))


# --------------------------------------------------------- the image's data

def elf_f(addr):
    return struct.unpack("<f", BM.ELF.read(addr, 4))[0]


def elf_i(addr):
    return struct.unpack("<i", BM.ELF.read(addr, 4))[0]


def elf_fs(addr, n):
    return [elf_f(addr + 4 * i) for i in range(n)]


# .sdata. gMaxSlipAngleGlobal at 0x00323d30 sits in the middle of the run
# and is zero in the image -- the static constructor writes it.
G_WHEEL_MOMENT_OF_INERTIA = elf_f(0x00323D18)
G_ROLLING_FRICTION = elf_f(0x00323D2C)
G_MAX_SLIP_ANGLE_IMAGE = elf_f(0x00323D30)
G_MAX_STATIC_SLIP = elf_f(0x00323D34)
G_BRAKING_TORQUE = elf_f(0x00323D38)
G_EBRAKING_TORQUE = elf_f(0x00323D3C)
G_STATIC_TO_DYNAMIC = elf_f(0x00323D40)
G_BRAKE_LOCK_FACTOR = elf_f(0x00323D44)
G_ZFORCE_SCALE = elf_f(0x00323D48)
G_PILOT_FACTOR = elf_f(0x00323D4C)
G_WHEEL_DEBUG_INFO = elf_i(0x00323D50)
G_CORNERING_SCALE = elf_f(0x00323D54)
G_USE_NEW_TIRE_FORCES = elf_i(0x00323D58)
G_NEW_CORNERING_SCALE = elf_f(0x00323D5C)

# Suspension's four, in the same .sdata block and read by Wheel too.
G_LOAD_FACTOR = elf_f(0x00323D60)
G_WHEEL_FORCE_FRAME = elf_i(0x00323D64)
G_TIRE_FORCE_ELLIPSE_RATIO = elf_f(0x00323D68)
G_UGLY_TIMESTEP_HACK = elf_f(0x00323D70)

# Wheel's own literal pool, one contiguous run. Reading it by address is
# what keeps the header honest about the pi that is one ulp low and the
# 1.57079649 that is not a rounded 1.5708f.
K_HALF_PI = elf_f(0x00321788)
K_ROT_FOLD = elf_f(0x0032178C)
K_ROT_GIVE_UP = elf_f(0x00321790)
K_ROT_FOLD_NEG = elf_f(0x00321794)
K_ROT_GIVE_UP_NEG = elf_f(0x00321798)
K_SPIN_EPSILON = elf_f(0x0032179C)
K_SPIN_EPSILON_NEG = elf_f(0x003217A0)
K_ZFORCE_FLOOR = elf_f(0x003217A4)
K_EPSILON = elf_f(0x003217A8)
K_PILOT_SPEED = elf_f(0x003217B0)
K_PILOT_INV_SPAN = elf_f(0x003217B4)
K_BAM_TO_RAD = elf_f(0x003217B8)
K_PI = elf_f(0x003217BC)
K_TWO_PI = elf_f(0x003217C0)
K_REVERSE_DAMP = elf_f(0x003217C8)
K_MPS_TO_MPH = elf_f(0x003217CC)

# Retail's GetDerivative (0x001a46b0) takes off the spin times Damage * 0.1
# after the rolling friction, its 0.1 a literal of its own (gp-29344), read
# out of SLES_507.31.
RETAIL_ELF = mipsdis.Elf(str(retail_model.RETAIL))
K_DAMAGE_DRAG = struct.unpack(
    "<f", RETAIL_ELF.read(retail_model.RETAIL_GP - 29344, 4))[0]
K_RAD_TO_DEG = elf_f(0x003217D4)
K_NO_SURFACE = f32(-100.0)        # `lui at,0xc2c8`, an immediate not a load

# The negated folds and the second copies of pi, two pi and the epsilon are
# separate words in the pool. Asserting they agree is how a differently
# tuned image would be caught rather than quietly modelled with one value.
assert K_ROT_FOLD_NEG == -K_ROT_FOLD
assert K_ROT_GIVE_UP_NEG == -K_ROT_GIVE_UP
assert K_SPIN_EPSILON_NEG == -K_SPIN_EPSILON
assert elf_f(0x003217AC) == K_EPSILON
assert elf_f(0x003217C4) == K_TWO_PI
assert elf_f(0x003217D8) == K_EPSILON
assert elf_f(0x003217DC) == K_EPSILON
assert elf_f(0x003217E0) == K_BAM_TO_RAD
assert elf_f(0x003217E4) == K_PI
assert elf_f(0x003217E8) == K_TWO_PI
assert elf_f(0x003217EC) == K_TWO_PI
assert elf_f(0x003217F0) == K_HALF_PI
assert elf_f(0x003217F4) == K_EPSILON

# The one the static constructor loads and stores into gMaxSlipAngleGlobal.
K_MAX_SLIP_ANGLE = elf_f(0x00321800)

# The two globals whose shipped values hide their own callers. Asserted so
# a retuned image fails here loudly rather than making two sub-passes
# pointless.
assert G_USE_NEW_TIRE_FORCES == 1
assert G_WHEEL_FORCE_FRAME == 1
assert G_MAX_SLIP_ANGLE_IMAGE == 0.0

# .data. The cornering curve has seven entries over [0, MAX_SLIP_ANGLE];
# the seven load curves have six each over [0, 10].
CORNERING_ENTRIES = elf_fs(0x00308E28, 7)
LOAD_ENTRIES = [elf_fs(0x00308E60 + 0x18 * i, 6) for i in range(7)]

# The pointer array GetLateralForce indexes, and the seven Table objects it
# points at. They are 24 bytes apart in the image rather than the 20 a
# packed array of Table would be; nothing reaches them except through this
# array, so the spacing is not observable and the port is free to make
# them a real array.
LOAD_TABLE_PTRS = [struct.unpack("<I", BM.ELF.read(0x00308FB0 + 4 * i, 4))[0]
                   for i in range(7)]
assert LOAD_TABLE_PTRS == [0x00308F08 + 0x18 * i for i in range(7)]

WHEEL_VTABLE = 0x00298F20
PHYSICSCOMPONENT_VTABLE = 0x00298728

NUM_LOAD_TABLES = 7
LOAD_TABLE_ENTRIES = 6
CORNERING_COUNT = 7


# ------------------------------------------------------------------ Table

def make_table(entries, n, lo, hi):
    t = EN.Table()
    EN.table_init(t, [f32(e) for e in entries], n, f32(lo), f32(hi))
    return t


g_max_slip_angle = ZERO
g_cornering = None
g_load = []


def static_init():
    """0x0019b558. The cornering curve's top is MAX_SLIP_ANGLE, which this
    is the only writer of."""
    global g_max_slip_angle, g_cornering, g_load
    g_max_slip_angle = f32(K_MAX_SLIP_ANGLE)
    g_cornering = make_table(CORNERING_ENTRIES, CORNERING_COUNT,
                             0.0, g_max_slip_angle)
    g_load = [make_table(LOAD_ENTRIES[i], LOAD_TABLE_ENTRIES, 0.0, 10.0)
              for i in range(NUM_LOAD_TABLES)]


tv = EN.table_get_value


# -------------------------------------------------------- the VU idioms

def dot3(a, b):
    """vmul.xyz then vaddy.x then vaddz.x -- (x + y) + z, left to right."""
    return fadd(fadd(fmul(a[0], b[0]), fmul(a[1], b[1])), fmul(a[2], b[2]))


def cross3(a, b):
    """vopmula.xyz / vopmsub.xyz: xyz only, so the destination keeps the w
    it already had, which in every use here is a's."""
    return (fsub(fmul(a[1], b[2]), fmul(b[1], a[2])),
            fsub(fmul(a[2], b[0]), fmul(b[2], a[0])),
            fsub(fmul(a[0], b[1]), fmul(b[0], a[1])),
            a[3])


def normalize3(v):
    """vrsqrt then a broadcast vmulx.xyzw -- all four lanes are scaled."""
    inv = fdiv(ONE, fsqrt(dot3(v, v)))
    return tuple(fmul(c, inv) for c in v)


def identity():
    return BV.bIdentity()


def mulvec3(m, v):
    """bMulMatrixVec3 through the 0x00193658 thunk: w forced to 1 going in
    and the product's w written back out, so four lanes come back."""
    return BV.rowmul((v[0], v[1], v[2], ONE), m)


def transpose(m):
    return BV.bTransposeMatrix(m)


# ---------------------------------------------------------------- the seams

class Seams(object):
    """The harness's stand-ins, restated rather than shared."""

    def __init__(self):
        self.on = True
        self.calls = 0
        self.noise_calls = 0
        self.topology_calls = 0
        self.terrain_out_null = None
        self.ret = ZERO
        self.normal = (ZERO, ZERO, ONE, ZERO)
        self.pos = (ZERO, ZERO, ZERO)
        self.noise_ret = ZERO
        self.noise_terrain = 0
        self.noise_xy = (ZERO, ZERO)
        self.topology_hit = False
        # SetState(CarState *, ...) hands the elevation call a real
        # out-parameter and a four-lane position, so it records more than
        # CheckTerrain does.
        self.pos4 = (ZERO, ZERO, ZERO, ZERO)
        self.topology_arg = None


SEAM = Seams()
g_terrain_table = None
g_ugly_timestep = f32(G_UGLY_TIMESTEP_HACK)
g_force_frame = G_WHEEL_FORCE_FRAME
g_use_new = G_USE_NEW_TIRE_FORCES


class TerrainInfo(object):
    def __init__(self, i):
        self.Type = i
        self.StaticFrictionMultiplier = fadd(ONE, fmul(f32(0.25), f32(i)))
        self.DynamicFrictionMultiplier = fsub(f32(0.9), fmul(f32(0.10),
                                                             f32(i)))
        self.RollingFrictionMultiplier = fadd(ONE, fmul(f32(0.50), f32(i)))


TERRAIN = [TerrainInfo(i) for i in range(6)]


def static_mul(w):
    if g_terrain_table is None:
        return ONE
    return g_terrain_table[w.Terrain].StaticFrictionMultiplier


def dynamic_mul(w):
    if g_terrain_table is None:
        return ONE
    return g_terrain_table[w.Terrain].DynamicFrictionMultiplier


def rolling_mul(w):
    if g_terrain_table is None:
        return ONE
    return g_terrain_table[w.Terrain].RollingFrictionMultiplier


# -------------------------------------------------------------- the fixture

class WI(object):
    def __init__(self):
        self.PositionX = f32(1.4)
        self.PositionY = f32(0.78)
        self.PositionZ = f32(-0.35)
        self.Radius = f32(0.32)
        self.Width = f32(0.21)
        self.WheelNumber = 2


class TI(object):
    def __init__(self):
        self.MaxSlipAngle = f32(0.14)
        self.MaxLoad = f32(5200.0)
        self.ForceScale = f32(1.15)
        self.StaticFrictionCoefficient = f32(1.05)
        self.DynamicFrictionCoefficient = f32(0.85)


class CI(object):
    def __init__(self):
        self.Steering = f32(0.6)
        self.Brake = f32(1.3)
        self.EBrake = f32(0.75)


class CS(object):
    def __init__(self):
        self.ForwardSpeed = f32(20.0)
        self.DriverMode = 1


g_wi = WI()
g_ti = TI()
g_ci = CI()
g_cs = CS()


def world_matrix():
    return [(f32(0.936293435), f32(0.351175636), f32(-0.0174524058),
             f32(0.5)),
            (f32(-0.348570138), f32(0.929229140), f32(0.121869341),
             f32(-0.25)),
            (f32(0.0523359589), f32(-0.111618653), f32(0.992403865),
             f32(0.75)),
            (f32(11.5), f32(-3.25), f32(0.44), ONE)]


def car_matrix():
    return [(f32(0.8), f32(0.6), ZERO, ZERO),
            (f32(-0.6), f32(0.8), ZERO, ZERO),
            (ZERO, ZERO, ONE, ZERO),
            (f32(1.4), f32(0.78), f32(-0.03), ONE)]


class Wheel(object):
    """calloc's view of the record: every field zero until something
    writes it, which is what the harness allocates."""

    def __init__(self):
        self.pNext = 0
        self.pPrev = 0
        self.vtable = 0
        self.WI = None
        self.TI = None
        self.CI = None
        self.CS = None
        self.a = ZERO
        self.w = ZERO
        self.MomentOfInertia = ZERO
        self.Matrix = [(ZERO,) * 4 for _ in range(4)]
        self.WorldMatrix = [(ZERO,) * 4 for _ in range(4)]
        self.CarMatrix = [(ZERO,) * 4 for _ in range(4)]
        self.Velocity = (ZERO,) * 4
        self.Slip = [ZERO, ZERO]
        self.AppliedTorque = ZERO
        self.BrakeLocked = 0
        self.LastSign = 0
        self.GroundForce = [ZERO, ZERO]
        self.WorldGroundForce = (ZERO,) * 4
        self.ContactPoint = (ZERO,) * 4
        self.ContactNormal = (ZERO,) * 4
        self.Terrain = 0
        self.Slipping = 0
        self.TouchingGround = 0
        self.NumTimesSkidding = 0
        self.ZForce = ZERO
        self.RoadNoise = ZERO
        self.CurrentSlip = ZERO
        self.OldSlip = ZERO
        self.TractionUsage = ZERO
        self.Damage = ZERO
        self.Brake = ZERO
        self.EBrake = ZERO
        self.TractionBoost = ZERO
        self.CatchupFrictionMultiplier = ZERO
        self.SkidSet = None
        # The four bytes at 284. Nothing in the object reads them; the
        # demo's DoSnapshot moved them as its fourth word and retail's does
        # not, so they have to be somewhere the transcript can print.
        self.Pad2 = 0


# -------------------------------------------------------------- lifetime

def wheel_init(w, wi, ti, ci, cs):
    """0x00199c40. Nine stores and no arithmetic."""
    w.vtable = WHEEL_VTABLE
    w.CS = cs
    w.WI = wi
    w.TI = ti
    w.CI = ci
    w.LastSign = 1
    w.CatchupFrictionMultiplier = ONE
    w.SkidSet = None
    w.TractionBoost = ONE
    w.NumTimesSkidding = 0
    w.OldSlip = ZERO
    w.RoadNoise = ZERO
    return w


def wheel_fini(w):
    w.vtable = PHYSICSCOMPONENT_VTABLE


def calibrate(w):
    """0x0019a068. The load argument is not in the signature at all."""
    w.MomentOfInertia = f32(G_WHEEL_MOMENT_OF_INERTIA)


def fresh():
    w = Wheel()
    wheel_init(w, g_wi, g_ti, g_ci, g_cs)
    calibrate(w)
    w.a = f32(0.75)
    w.w = f32(31.0)
    w.WorldMatrix = world_matrix()
    w.CarMatrix = car_matrix()
    w.Matrix = identity()
    w.Velocity = (f32(12.0), f32(0.5), f32(-0.25), f32(0.75))
    w.ContactNormal = (f32(0.1), f32(-0.2), f32(0.96), f32(0.5))
    w.ContactPoint = (f32(1.5), f32(0.8), f32(-0.4), f32(0.25))
    w.WorldGroundForce = (f32(120.0), f32(-45.0), f32(310.0), f32(7.0))
    w.ZForce = f32(3900.0)
    w.Terrain = 2
    w.TouchingGround = 1
    w.Slipping = 0
    w.BrakeLocked = 0
    w.LastSign = 0
    w.AppliedTorque = f32(260.0)
    w.GroundForce = [f32(140.0), f32(-220.0)]
    w.Slip = [f32(7.5), f32(-8.5)]
    w.TractionBoost = f32(1.25)
    w.CatchupFrictionMultiplier = f32(0.9)
    w.MomentOfInertia = f32(G_WHEEL_MOMENT_OF_INERTIA)
    return w


def dump(tag, w):
    emit("%s vtable %08x" % (tag, w.vtable))
    pf(tag + " State.a", w.a)
    pf(tag + " State.w", w.w)
    pf(tag + " MomentOfInertia", w.MomentOfInertia)
    pm(tag + " Matrix", w.Matrix)
    pm(tag + " WorldMatrix", w.WorldMatrix)
    pm(tag + " CarMatrix", w.CarMatrix)
    pv(tag + " Velocity", w.Velocity)
    pf(tag + " Slip0", w.Slip[0])
    pf(tag + " Slip1", w.Slip[1])
    pf(tag + " AppliedTorque", w.AppliedTorque)
    pint(tag + " BrakeLocked", w.BrakeLocked)
    pint(tag + " LastSign", w.LastSign)
    pf(tag + " GroundForce0", w.GroundForce[0])
    pf(tag + " GroundForce1", w.GroundForce[1])
    pv(tag + " WorldGroundForce", w.WorldGroundForce)
    pv(tag + " ContactPoint", w.ContactPoint)
    pv(tag + " ContactNormal", w.ContactNormal)
    pint(tag + " Terrain", w.Terrain)
    pint(tag + " Slipping", w.Slipping)
    pint(tag + " TouchingGround", w.TouchingGround)
    pint(tag + " NumTimesSkidding", w.NumTimesSkidding)
    pf(tag + " ZForce", w.ZForce)
    pf(tag + " RoadNoise", w.RoadNoise)
    pf(tag + " CurrentSlip", w.CurrentSlip)
    pf(tag + " OldSlip", w.OldSlip)
    pf(tag + " TractionUsage", w.TractionUsage)
    pf(tag + " Damage", w.Damage)
    pf(tag + " Brake", w.Brake)
    pf(tag + " EBrake", w.EBrake)
    pf(tag + " TractionBoost", w.TractionBoost)
    pf(tag + " CatchupFriction", w.CatchupFrictionMultiplier)


# ------------------------------------------------------- ComputeAuxiliaries

def compute_auxiliaries(w):
    """0x0019a078."""
    w.Matrix = identity()
    a = w.a
    c = bSinF(fadd(a, f32(K_HALF_PI)))
    s = bSinF(a)

    m = [list(r) for r in w.Matrix]
    m[2][2] = c
    m[0][2] = fneg(s)
    m[0][0] = c
    m[2][0] = s
    w.Matrix = [tuple(r) for r in m]

    w.GroundForce = [ZERO, ZERO]
    w.AppliedTorque = ZERO
    w.CurrentSlip = ZERO

    fold = f32(K_ROT_FOLD)
    give = f32(K_ROT_GIVE_UP)
    if fold < a:
        v = fsub(a, fold)
        w.a = v
        if give < v:
            w.a = ZERO
    elif a < fneg(fold):
        v = fadd(a, fold)
        w.a = v
        if v < fneg(give):
            w.a = ZERO

    sign = w.LastSign
    if sign == 0:
        if w.w < 0.0:
            w.w = ZERO
    elif sign == 2:
        if 0.0 < w.w:
            w.w = ZERO

    eps = f32(K_SPIN_EPSILON)
    if eps < w.w:
        w.LastSign = 0
    elif w.w < fneg(eps):
        w.LastSign = 2
    else:
        w.LastSign = 1


# ---------------------------------------------------------- ExchangeZForces

def exchange_z_forces(w, touching, z):
    """0x0019a1c8. Returns 0.0 on both paths."""
    w.TouchingGround = touching & 0xFF

    if touching != 0:
        r = fneg(w.WI.Radius)
        t = w.WorldMatrix[3]
        w.ContactPoint = tuple(fadd(fmul(w.ContactNormal[i], r), t[i])
                               for i in range(4))

    if not (0.0 < z):
        w.ZForce = ZERO
        return ZERO

    t = cross3(w.WorldMatrix[1], w.ContactNormal)
    u = cross3(t, w.WorldMatrix[1])
    d = dot3(u, w.ContactNormal)
    d = fmul(d, f32(4.0))
    d = fsub(d, f32(3.0))
    if d < f32(K_ZFORCE_FLOOR):
        d = f32(K_ZFORCE_FLOOR)
    w.ZForce = fmul(z, d)
    return ZERO


# ------------------------------------------------------------- CheckTerrain

def check_terrain(w, pos, r):
    """0x0019a2c8, reached through FindDrivingSurface at 0x0019a2a0, whose
    out-parameters are the wheel's own ContactNormal and Terrain."""
    elev = ZERO
    noise = ZERO

    if SEAM.on:
        SEAM.topology_calls += 1
        SEAM.topology_hit = True
        SEAM.calls += 1
        SEAM.pos = (pos[0], pos[1], pos[2])
        SEAM.terrain_out_null = False    # a2 is the caller's, untouched
        w.ContactNormal = SEAM.normal
        w.Terrain = 77                   # the stand-in's write
        elev = SEAM.ret
        SEAM.noise_calls += 1
        SEAM.noise_xy = (pos[0], pos[1])
        SEAM.noise_terrain = w.Terrain
        noise = SEAM.noise_ret
    else:
        w.ContactNormal = (ZERO, ZERO, ONE, ZERO)

    w.RoadNoise = noise

    n = w.ContactNormal
    probe = (pos[0], pos[1], fadd(elev, noise), ZERO)

    align = dot3(n, r[2])
    if align < f32(K_EPSILON):
        w.Terrain = 0
        return K_NO_SURFACE

    delta = tuple(fsub(probe[i], pos[i]) for i in range(4))
    return fdiv(dot3(n, delta), align)


# ------------------------------------------------------------ GetDerivative

def get_derivative(w, out):
    """Retail's 0x001a46b0 (the demo's 0x0019a3d0). Returns NULL, not the
    buffer."""
    mul = rolling_mul(w)
    out[0] = w.w
    acc = fsub(w.AppliedTorque, fmul(w.GroundForce[0], w.WI.Radius))
    acc = fsub(acc, fmul(fmul(w.w, mul), f32(G_ROLLING_FRICTION)))
    acc = fsub(acc, fmul(w.w, fmul(w.Damage, f32(K_DAMAGE_DRAG))))
    acc = fdiv(acc, w.MomentOfInertia)
    out[1] = acc
    if w.BrakeLocked != 0:
        out[1] = ZERO
    if w.Slipping == 0 and f32(K_EPSILON) < g_ugly_timestep:
        d = fmul(w.WI.Radius, g_ugly_timestep)
        out[1] = fsub(out[1], fdiv(w.CurrentSlip, d))
    return None


# -------------------------------------------------------- CheckForBrakeLock

def check_for_brake_lock(w, v):
    """0x0019a480."""
    t = fadd(fmul(fmul(f32(G_BRAKING_TORQUE), w.Brake), w.CI.Brake),
             fmul(fmul(f32(G_EBRAKING_TORQUE), w.EBrake), w.CI.EBrake))
    threshold = fmul(t, f32(G_STATIC_TO_DYNAMIC))
    demand = fadd(fmul(v, w.WI.Radius),
                  fmul(fabs32(w.w), f32(G_BRAKE_LOCK_FACTOR)))
    if demand < threshold:
        w.BrakeLocked = 1 if 1.0 < threshold else 0
        w.w = ZERO
    else:
        w.BrakeLocked = 0


def get_pilot_factor(w):
    """0x0019a520. The blend is fptodp / dpsub / dpmul / dpadd / dptofp."""
    if w.BrakeLocked != 0:
        return ONE
    if w.w < 0.0:
        return ONE
    if w.WI.WheelNumber < 2:
        return ONE
    t = fmul(fsub(w.CS.ForwardSpeed, f32(K_PILOT_SPEED)),
             f32(K_PILOT_INV_SPAN))
    if 1.0 < t:
        t = ONE
    elif t < 0.0:
        t = ZERO
    p = float(f32(G_PILOT_FACTOR))
    return f32(p + (1.0 - p) * float(t))


# ------------------------------------------------------------- the tyre

def slip_angle(w):
    """The transpose, the atan and the two folds, shared by both passes."""
    t = [list(r) for r in transpose(w.WorldMatrix)]
    t[0][3] = ZERO
    t[1][3] = ZERO
    t[2][3] = ZERO
    t = [tuple(r) for r in t]
    local = mulvec3(t, w.Velocity)

    angle = fmul(f32(float(bATan(local[0], local[1]))), f32(K_BAM_TO_RAD))
    if f32(K_PI) < angle:
        angle = fsub(angle, f32(K_TWO_PI))
    if local[0] < 0.0:
        angle = fadd(angle, f32(K_PI))
        if f32(K_PI) < angle:
            angle = fsub(angle, f32(K_TWO_PI))
    return angle, local


def get_lateral_force(w, zforce, slip):
    """0x0019aa20."""
    if g_use_new == 0:
        v = tv(g_cornering, slip)
        return fmul(fmul(f32(G_CORNERING_SCALE), v),
                    fmul(w.ZForce, f32(G_ZFORCE_SCALE)))

    load = fdiv(fmul(zforce, f32(G_LOAD_FACTOR)), w.TI.MaxLoad)
    scale = fdiv(f32(12.0), w.TI.MaxSlipAngle)     # lui at,0x4140
    index = fmul(fmul(fmul(slip, f32(K_RAD_TO_DEG)), scale), f32(0.5))
    i = int(index)                       # cvt.w.s, toward zero
    frac = fsub(index, f32(float(i)))
    k = fmul(w.TI.ForceScale, f32(G_NEW_CORNERING_SCALE))

    if i < 6:
        a = tv(g_load[i], load)
        b = tv(g_load[i + 1], load)
        return fmul(k, fadd(a, fmul(frac, fsub(b, a))))
    return fmul(k, tv(g_load[6], load))


def guess_ground_force(w):
    """0x0019a638."""
    brake = fmul(fmul(f32(G_BRAKING_TORQUE), w.Brake), w.CI.Brake)
    ebrake_mag = fmul(fmul(f32(G_EBRAKING_TORQUE), w.EBrake), w.CI.EBrake)

    if 0.0 < w.w:
        brake = fneg(brake)
    if w.BrakeLocked == 0:
        w.AppliedTorque = fadd(w.AppliedTorque, brake)

    ebrake = fneg(ebrake_mag) if 0.0 < w.w else ebrake_mag
    if w.BrakeLocked == 0:
        w.AppliedTorque = fadd(w.AppliedTorque, ebrake)

    angle, local = slip_angle(w)
    vx, vy = local[0], local[1]

    slip = fsub(fmul(w.w, w.WI.Radius), vx)
    w.CurrentSlip = slip
    w.OldSlip = slip

    if slip < fneg(f32(G_MAX_STATIC_SLIP)):
        if w.AppliedTorque < 0.0 and ebrake_mag == 0.0:
            w.AppliedTorque = fmul(w.AppliedTorque, f32(K_REVERSE_DAMP))

    slip = w.CurrentSlip
    slipping = 0
    dynamic = ONE                        # $f22, before the two early-outs
    per_mag = ZERO
    mag = fsqrt(fadd(fmul(slip, slip), fmul(vy, vy)))

    reached = True
    if mag == 0.0:
        reached = False
    elif vy == 0.0 and vx == 0.0:
        reached = False

    if reached:
        dynamic = fmul(fmul(w.TI.DynamicFrictionCoefficient,
                            w.CatchupFrictionMultiplier),
                       fmul(w.TractionBoost, dynamic_mul(w)))
        if w.CS.DriverMode == 1:
            dynamic = fmul(dynamic, get_pilot_factor(w))
        max_force = fmul(fmul(f32(G_ZFORCE_SCALE), w.ZForce), dynamic)
        per_mag = fdiv(max_force, mag)
        per_speed = fdiv(max_force,
                         fsqrt(fadd(fmul(vx, vx), fmul(vy, vy))))
        check_for_brake_lock(w, fmul(fabs32(vx), per_speed))

        if f32(G_MAX_STATIC_SLIP) < fabs32(slip):
            slipping = 1
        elif w.TI.MaxSlipAngle < fabs32(angle):
            slipping = 1
        elif w.BrakeLocked != 0:
            slipping = 1

    if slipping:
        fx = fmul(per_mag, slip)
        fy = fmul(fneg(per_mag), vy)
        w.Slipping = 1
        w.GroundForce = [fx, fy]
        if (fmul(w.CS.ForwardSpeed, f32(K_MPS_TO_MPH)) < 1.0
                and f32(0.100000001) < dynamic):
            w.GroundForce[1] = fdiv(fy, dynamic)
            w.GroundForce[0] = fdiv(fx, dynamic)
        w.Slip[1] = vy
        w.Slip[0] = slip
    else:
        w.Slipping = 0
        sign = ONE if 0.0 < vx else f32(-1.0)
        w.GroundForce[0] = fdiv(w.AppliedTorque, w.WI.Radius)
        lateral = get_lateral_force(w, fmul(f32(G_ZFORCE_SCALE), w.ZForce),
                                    fabs32(angle))
        if 0.0 < angle:
            lateral = fneg(lateral)
        w.GroundForce[1] = fmul(sign, lateral)
        w.Slip[1] = ZERO
        w.Slip[0] = ZERO


def modify_ground_force(w, v):
    """0x0019ab80."""
    m = [w.CarMatrix[0], w.CarMatrix[1], w.CarMatrix[2],
         (ZERO, ZERO, ZERO, ONE)]
    out = mulvec3(m, (v[0], v[1], ZERO))

    radius = w.WI.Radius
    moment = w.MomentOfInertia

    spin = fsub(w.AppliedTorque, fmul(w.GroundForce[0], radius))
    spin = fdiv(spin, moment)
    delta = fmul(spin, w.WI.Radius)
    delta = fsub(delta, out[0])
    delta = fmul(delta, w.MomentOfInertia)
    delta = fdiv(delta, w.WI.Radius)
    w.GroundForce[0] = fadd(w.GroundForce[0], delta)


def finalize_ground_force(w):
    """0x0019ac60."""
    ellipsed = False
    if 0.0 < w.AppliedTorque and w.BrakeLocked == 0:
        ellipsed = True
        w.GroundForce[0] = fmul(w.GroundForce[0],
                                f32(G_TIRE_FORCE_ELLIPSE_RATIO))

    mag = fsqrt(fadd(fmul(w.GroundForce[0], w.GroundForce[0]),
                     fmul(w.GroundForce[1], w.GroundForce[1])))

    max_force = fmul(
        fmul(fmul(f32(G_ZFORCE_SCALE), w.CatchupFrictionMultiplier),
             fmul(static_mul(w), w.TI.StaticFrictionCoefficient)),
        fmul(w.ZForce, w.TractionBoost))
    if w.CS.DriverMode == 1:
        max_force = fmul(max_force, get_pilot_factor(w))

    if max_force < mag and f32(K_EPSILON) < mag:
        k = fdiv(max_force, mag)
        w.GroundForce[0] = fmul(w.GroundForce[0], k)
        w.GroundForce[1] = fmul(w.GroundForce[1], k)
    elif ellipsed:
        w.GroundForce[0] = fdiv(w.GroundForce[0],
                                f32(G_TIRE_FORCE_ELLIPSE_RATIO))

    if f32(K_EPSILON) < max_force:
        u = fdiv(mag, max_force)
        w.TractionUsage = ONE if 1.0 < u else u
    else:
        w.TractionUsage = ONE

    if not (w.Slipping == 0 and w.BrakeLocked == 0):
        w.TractionUsage = ONE
    if w.TouchingGround == 0:
        w.TractionUsage = ZERO

    angle, local = slip_angle(w)
    lateral_sin = fmul(bSinF(angle), w.GroundForce[1])

    if 1.0 < fabs32(local[0]):
        w.GroundForce[0] = fsub(w.GroundForce[0],
                                fmul(lateral_sin, f32(0.5)))

    frame = identity()
    if g_force_frame == 1:
        frame = [w.WorldMatrix[0], w.WorldMatrix[1], w.WorldMatrix[2],
                 frame[3]]
    elif g_force_frame == 2:
        n = w.ContactNormal
        d0 = dot3(n, w.WorldMatrix[0])
        d1 = dot3(n, w.WorldMatrix[1])
        r0 = tuple(fadd(fmul(n[i], fneg(d0)), w.WorldMatrix[0][i])
                   for i in range(4))
        r1 = tuple(fadd(fmul(n[i], fneg(d1)), w.WorldMatrix[1][i])
                   for i in range(4))
        frame = [r0[:3] + (ZERO,), r1[:3] + (ZERO,), n[:3] + (ZERO,),
                 frame[3]]
    elif g_force_frame == 3:
        n = w.ContactNormal
        d = dot3(n, w.WorldMatrix[0])
        r0 = tuple(fadd(fmul(n[i], fneg(d)), w.WorldMatrix[0][i])
                   for i in range(4))
        r0 = normalize3(r0)
        r0 = r0[:3] + (ZERO,)
        r2 = n[:3] + (ZERO,)
        r1 = cross3(r2, r0)
        frame = [r0, r1[:3] + (ZERO,), r2, frame[3]]
    elif g_force_frame == 4:
        # Rows 0 and 1 keep WorldMatrix's w; only row 2's is cleared.
        frame = [w.WorldMatrix[0], w.WorldMatrix[1],
                 w.ContactNormal[:3] + (ZERO,), frame[3]]

    world = mulvec3(frame, (w.GroundForce[0], w.GroundForce[1], w.ZForce))
    w.WorldGroundForce = tuple(world)


def horizontal_in(src, fx, fy):
    """0x0019b120 / 0x0019b1a8, the same body over two matrices."""
    m = [src[0], src[1], src[2], (ZERO, ZERO, ZERO, ONE)]
    return mulvec3(m, (fx, fy, ZERO))


def bRotateVector(m, v):
    """0x0019b230. M-transpose times v, three lanes, no translation."""
    out = []
    for c in range(3):
        t = fmul(m[0][c], v[0])
        t = fadd(t, fmul(m[1][c], v[1]))
        t = fadd(t, fmul(m[2][c], v[2]))
        out.append(t)
    return tuple(out)


# ---------------------------------------------------------- DoSnapshot


class Snap(object):
    """A ReplaySnapshot as replay.c's MoveData uses it: one of the four
    modes, the data and its position, and the first level of the section
    stack, which is the only one DoSnapshot opens."""

    def __init__(self, take=0, restore=0, csum=0, data=b""):
        self.take = take
        self.restore = restore
        self.csum = csum
        self.depth = -1
        self.number = 0
        self.data = bytearray(data)
        self.size_of_data = len(data)
        self.pos = 0
        self.sec = None

    def begin(self, name):
        if self.depth == -1:
            self.number = 0
        self.depth += 1
        self.sec = {"name": name, "obj": 0, "num": self.number,
                    "moves": 0, "size": self.pos}
        self.number += 1

    def end(self):
        self.sec["size"] = self.pos - self.sec["size"]
        self.depth -= 1

    def move(self, raw):
        """`raw` is the field's bytes; a restore returns the bytes read."""
        self.sec["moves"] += 1
        n = len(raw)
        if self.take:
            self.data[self.pos:self.pos + n] = raw
            self.pos += n
        elif self.restore:
            if self.size_of_data >= self.pos + n:
                raw = bytes(self.data[self.pos:self.pos + n])
                self.pos += n
        elif self.csum:
            h = 0xffffffff
            for b in raw:
                h = (h * 33 + b) & 0xffffffff
            self.data[self.pos:self.pos + 2] = struct.pack("<H", h & 0xffff)
            self.pos += 2
        return raw


def do_snapshot(w, snap):
    """Retail's 0x001a3f60, the demo's 0x00199c90. BeginNamedSection, three
    MoveData calls, and then bMemSets behind a test of the two flags.

    The demo moved 4-byte, 4-byte, then 16 bytes as four words from
    LastSign, past both GroundForce floats into the alignment pad at 284.
    Retail's third move is MoveData(int *, int) with 4: LastSign alone.

    The reset steps around four live fields. MomentOfInertia at 36 is
    outside the first bMemSet, which starts at 48; LastSign at 272 was just
    moved and is not in the list; RoadNoise at 348 is jumped over -- the
    list runs 344 for four, then 352. The pad at 284 survives for the same
    reason: 276 for eight, then 288. The demo also kept Damage at 364;
    retail's last bMemSet clears it.

    TractionBoost and CatchupFrictionMultiplier go to zero, not to the 1.0
    the constructor gave them, so a wheel restored from a rewind has no grip
    multiplier at all until something outside this object writes one."""
    snap.begin("Wheel")

    w.a = struct.unpack("<f", snap.move(struct.pack("<f", w.a)))[0]
    w.w = struct.unpack("<f", snap.move(struct.pack("<f", w.w)))[0]
    w.LastSign = struct.unpack("<i", snap.move(struct.pack("<i", w.LastSign)))[0]

    if snap.take or snap.restore:
        w.Matrix = [(ZERO,) * 4 for _ in range(4)]
        w.WorldMatrix = [(ZERO,) * 4 for _ in range(4)]
        w.CarMatrix = [(ZERO,) * 4 for _ in range(4)]
        w.Velocity = (ZERO,) * 4
        w.Slip = [ZERO, ZERO]
        w.AppliedTorque = ZERO
        w.BrakeLocked = 0
        w.GroundForce = [ZERO, ZERO]
        w.WorldGroundForce = (ZERO,) * 4
        w.ContactPoint = (ZERO,) * 4
        w.ContactNormal = (ZERO,) * 4
        w.Terrain = 0
        w.Slipping = 0
        w.TouchingGround = 0
        w.NumTimesSkidding = 0
        w.ZForce = ZERO
        w.CurrentSlip = ZERO
        w.OldSlip = ZERO
        w.TractionUsage = ZERO
        w.Brake = ZERO
        w.EBrake = ZERO
        w.TractionBoost = ZERO
        w.CatchupFrictionMultiplier = ZERO
        w.Damage = ZERO

    snap.end()
    return snap


# ------------------------------------ SetState(CarState *, CarTypeInfo *, ..)

def flat(m):
    return [c for row in m for c in row]


def rows(f):
    return [tuple(f[i * 4:i * 4 + 4]) for i in range(4)]


def set_state_from_car_state(w, cs, angle, angvel, steer, susp):
    """0x00199e90, 472 bytes. Writes the wheel's spin into both the wheel
    and the CarState, rebuilds the two matrices from the CarState, places
    the wheel in the world and asks the ground where it is.

    The CarTypeInfo in a2 is never read: a2 is overwritten with a stack
    address before the first use of any argument."""
    n = w.WI.WheelNumber

    w.w = angvel
    w.a = angle

    cs.SteeringAngle = steer
    cs.WheelAngularVelocity[n] = angvel
    cs.WheelAngle[n] = angle
    cs.WheelSuspensionHeight[n] = susp
    CST.calculate_wheel_matrices_one(cs, n)

    # Row 3 is a quadword off Position, so its fourth lane arrives as
    # bVector3::pad and is then overwritten with 1.0 by its own store.
    place = list(cs.BodyMatrix[0:12]) + [cs.Position[0], cs.Position[1],
                                         cs.Position[2], ONE]
    world = EM.emul_matrix(cs.WheelMatrix[n], place)

    w.CarMatrix = rows(cs.WheelMatrix[n])
    w.WorldMatrix = rows(world)

    # Four lanes, so the w is world's row-3 w -- a 1.0 that the placement
    # carried through -- minus Position's pad, not a zero.
    r = (fsub(world[12], cs.Position[0]),
         fsub(world[13], cs.Position[1]),
         fsub(world[14], cs.Position[2]),
         fsub(world[15], cs.Position[3]))

    # r x omega, with r in the first operand: vopmula.xyz ACC,vf01,vf03 then
    # vopmsub.xyz vf01,vf03,vf01. Suspension::GetPointVelocity takes the
    # other order; this one is transcribed as written rather than corrected.
    c = cross3(r, cs.AngularVelocity)

    w.Velocity = (fadd(c[0], cs.Velocity[0]),
                  fadd(c[1], cs.Velocity[1]),
                  fadd(c[2], cs.Velocity[2]),
                  fadd(c[3], cs.Velocity[3]))

    # `addiu a2,sp,192` -- a stack slot, where CheckTerrain forwards the
    # wheel's own field. The topology comes straight out of the CarState.
    pos = (world[12], world[13], world[14], world[15])
    terrain = 0
    if SEAM.on:
        SEAM.calls += 1
        SEAM.pos4 = pos
        SEAM.terrain_out_null = False
        SEAM.topology_arg = cs.pTopologyCoordinate
        elev = SEAM.ret
        normal = SEAM.normal
        terrain = 77
    else:
        elev = ZERO
        normal = (ZERO, ZERO, ONE, ZERO)

    CST.set_wheel_touching_ground(cs, n, 1)
    CST.set_wheel_terrain(cs, n, terrain)

    # sp+172 is never written by this function; the quadword store that
    # follows takes whatever the stack held. A defined zero is the port's
    # choice and the mutation list is what argues it.
    w.ContactPoint = (pos[0], pos[1], elev, ZERO)
    w.ContactNormal = (normal[0], normal[1], normal[2], normal[3])
    w.Terrain = terrain
    # Unconditional. The state being restored already decided this.
    w.TouchingGround = 1


# ------------------------------------------------------------- the layout

WHEEL_OFFSETS = [
    ("Wheel.pNext", 0, 0), ("Wheel.pPrev", 4, 0), ("Wheel._vtable", 8, 0),
    ("Wheel.WI", 12, 1), ("Wheel.TI", 16, 2), ("Wheel.CI", 20, 3),
    ("Wheel.CS", 24, 4), ("Wheel.State", 28, 5),
    ("Wheel.MomentOfInertia", 36, 5), ("Wheel.Matrix", 48, 5),
    ("Wheel.WorldMatrix", 112, 5), ("Wheel.CarMatrix", 176, 5),
    ("Wheel.Velocity", 240, 5), ("Wheel.Slip", 256, 5),
    ("Wheel.AppliedTorque", 264, 5), ("Wheel.BrakeLocked", 268, 5),
    ("Wheel.LastSign", 272, 5), ("Wheel.GroundForce", 276, 5),
    ("Wheel.WorldGroundForce", 288, 5), ("Wheel.ContactPoint", 304, 5),
    ("Wheel.ContactNormal", 320, 5), ("Wheel.Terrain", 336, 5),
    ("Wheel.Slipping", 340, 5), ("Wheel.TouchingGround", 341, 5),
    ("Wheel.NumTimesSkidding", 342, 5), ("Wheel.ZForce", 344, 5),
    ("Wheel.RoadNoise", 348, 5), ("Wheel.CurrentSlip", 352, 5),
    ("Wheel.OldSlip", 356, 5), ("Wheel.TractionUsage", 360, 5),
    ("Wheel.Damage", 364, 5), ("Wheel.Brake", 368, 5),
    ("Wheel.EBrake", 372, 5), ("Wheel.TractionBoost", 376, 5),
    ("Wheel.CatchupFrictionMultiplier", 380, 5),
    ("Wheel.TheSkidMaker", 384, 6),
]

# Nine pointers over retail's 144-byte record -- the name, the skid texture
# and the seven emitter-group names -- and only the skid texture lands four
# bytes past an eight-byte boundary and takes a pad of its own on the way
# past: the slack count climbs 1, 2 to the skid texture, 3 from the skid
# width multiplier at 20, and one more past each emitter group, to 10.
# (The demo's 140 bytes put its first emitter group off the boundary too.)
TERRAIN_OFFSETS = [
    ("TerrainTypeInfo.Name", 0, 0),
    ("TerrainTypeInfo.NameHash", 4, 1),
    ("TerrainTypeInfo.Type", 8, 1),
    ("TerrainTypeInfo.SkidTextureName", 16, 2),
    ("TerrainTypeInfo.SkidWidthMultiplier", 20, 3),
    ("TerrainTypeInfo.RoadNoiseGridSpacingInverse", 24, 3),
    ("TerrainTypeInfo.RoadNoiseScale", 28, 3),
    ("TerrainTypeInfo.StaticFrictionMultiplier", 32, 3),
    ("TerrainTypeInfo.DynamicFrictionMultiplier", 36, 3),
    ("TerrainTypeInfo.RollingFrictionMultiplier", 40, 3),
    ("TerrainTypeInfo.DriveOverEmitterGroup", 60, 3),
    ("TerrainTypeInfo.CollisionScrapeEmitterGroup", 132, 9),
    ("TerrainTypeInfo.CollisionScrapeMaxSpeed", 140, 10),
]


def s_layout():
    emit("[layout]")
    emit("ptr %d" % PTR)
    emit("slack %d" % SLACK)
    # Five host-widened members over a PS2 record of 400 -- WI, TI, CI, CS
    # and the one pointer inside TheSkidMaker -- plus the two pads the host
    # adds, before WI and before TheSkidMaker. Terrain is not one of them:
    # `.mdebug` has it as type#140 at 32 bits and SetTerrain takes
    # `11TerrainType`, a 32-bit enum.
    size = (400 + 5 * SLACK + 2 * SLACK + PTR - 1) // PTR * PTR
    emit("sizeof Wheel %d" % size)
    emit("sizeof expected %d" % size)
    emit("sizeof WheelState 8")
    emit("sizeof SkidMaker %d" % PTR)
    emit("sizeof WheelInfo 32")
    emit("sizeof TireInfo 32")
    emit("sizeof ControlInfo 48")
    tsize = (144 + 10 * SLACK + PTR - 1) // PTR * PTR
    emit("sizeof TerrainTypeInfo %d" % tsize)
    emit("sizeof terraininfo expected %d" % tsize)

    for name, ps2, n in WHEEL_OFFSETS + TERRAIN_OFFSETS:
        emit("off %s %d" % (pad(name, 28), ps2 + n * SLACK))

    # WheelState's own two floats. Every access in the port is by name,
    # so a swapped declaration would move both fields and still read back
    # correctly from the new places; only the offsets catch it.
    emit("off %s %d" % (pad("WheelState.a", 28), 0))
    emit("off %s %d" % (pad("WheelState.w", 28), 4))

    emit("arr Slip 8")
    emit("arr GroundForce 8")
    emit("arr w_pad0 8")
    emit("arr w_pad1 12")
    emit("arr w_pad2 4")

    emit("vtable Wheel %08x" % WHEEL_VTABLE)
    emit("vtable PhysicsComponent %08x" % PHYSICSCOMPONENT_VTABLE)
    emit("state floats 2")
    emit("cornering entries %d" % CORNERING_COUNT)
    emit("load entries %d" % LOAD_TABLE_ENTRIES)
    emit("load tables %d" % NUM_LOAD_TABLES)


def dump_globals(tag):
    """The tuning block, printed under a caller-chosen tag. `constants`
    prints it once at the start; `accessors` prints it again straight after
    SetSliderValue, which is the only way a port that gave that empty
    function a body writing one of these would ever be noticed."""
    pf(tag + " WheelMomentOfInertia", G_WHEEL_MOMENT_OF_INERTIA)
    pf(tag + " RollingFriction", G_ROLLING_FRICTION)
    pf(tag + " MaxStaticSlip", G_MAX_STATIC_SLIP)
    pf(tag + " BrakingTorque", G_BRAKING_TORQUE)
    pf(tag + " EBrakingTorque", G_EBRAKING_TORQUE)
    pf(tag + " StaticToDynamicBrakeForceRatio", G_STATIC_TO_DYNAMIC)
    pf(tag + " BrakeLockAngularVelocityFactor", G_BRAKE_LOCK_FACTOR)
    pf(tag + " ZForceScale", G_ZFORCE_SCALE)
    pf(tag + " PilotFactor", G_PILOT_FACTOR)
    pint(tag + " WheelDebugInfo", G_WHEEL_DEBUG_INFO)
    pf(tag + " CorneringScale", G_CORNERING_SCALE)
    pint(tag + " UseNewTireForces", G_USE_NEW_TIRE_FORCES)
    pf(tag + " NewCorneringScale", G_NEW_CORNERING_SCALE)
    pf(tag + " LoadFactor", G_LOAD_FACTOR)
    pint(tag + " WheelForceFrame", G_WHEEL_FORCE_FRAME)
    pf(tag + " TireForceEllipseRatio", G_TIRE_FORCE_ELLIPSE_RATIO)
    pf(tag + " UglyTimestepHack", G_UGLY_TIMESTEP_HACK)


def s_constants():
    emit("[constants]")
    pf("k PI", K_PI)
    pf("k TWO_PI", K_TWO_PI)
    pf("k HALF_PI", K_HALF_PI)
    pf("k BAM_TO_RAD", K_BAM_TO_RAD)
    pf("k ROT_FOLD", K_ROT_FOLD)
    pf("k ROT_GIVE_UP", K_ROT_GIVE_UP)
    pf("k SPIN_EPSILON", K_SPIN_EPSILON)
    pf("k ZFORCE_FLOOR", K_ZFORCE_FLOOR)
    pf("k EPSILON", K_EPSILON)
    pf("k REVERSE_DAMP", K_REVERSE_DAMP)
    pf("k PILOT_SPEED", K_PILOT_SPEED)
    pf("k PILOT_INV_SPAN", K_PILOT_INV_SPAN)
    pf("k MPS_TO_MPH", K_MPS_TO_MPH)
    pf("k RAD_TO_DEG", K_RAD_TO_DEG)
    pf("k NO_SURFACE", K_NO_SURFACE)

    dump_globals("g")


TABLE_ARGS = [f32(x) for x in
              [-1.0, 0.0, 0.001, 0.05, 0.1117010859, 0.2, 0.223402172,
               0.3, 1.0, 2.5, 5.0, 7.5, 9.999, 10.0, 11.0]]


def s_statics():
    emit("[statics]")
    pf("maxslip", g_max_slip_angle)
    pf("cf min", g_cornering.lo)
    pf("cf max", g_cornering.hi)
    pf("cf mult", g_cornering.mult)
    pint("cf n", g_cornering.n)
    emit("cf same 1")
    for v in CORNERING_ENTRIES:
        pf("cf entry", f32(v))
    for a in TABLE_ARGS:
        pf("cf value", tv(g_cornering, a))

    for t in range(NUM_LOAD_TABLES):
        emit("ls %d same 1" % t)
        pf("ls min", g_load[t].lo)
        pf("ls max", g_load[t].hi)
        pf("ls mult", g_load[t].mult)
        pint("ls n", g_load[t].n)
        for v in LOAD_ENTRIES[t]:
            pf("ls entry", f32(v))
        for a in TABLE_ARGS:
            pf("ls value", tv(g_load[t], a))


def s_lifetime():
    emit("[lifetime]")
    w = Wheel()
    wheel_init(w, g_wi, g_ti, g_ci, g_cs)
    dump("init", w)
    emit("init WI 1")
    emit("init TI 1")
    emit("init CI 1")
    emit("init CS 1")
    emit("init skidset 1")

    calibrate(w)
    pf("calibrate moi", w.MomentOfInertia)

    pint("size", 2)
    emit("getstate 1")

    w.w = f32(-8.5)
    w.a = f32(1.25)
    pf("set2 a", w.a)
    pf("set2 w", w.w)
    w.w = f32(3.75)
    pf("setw a", w.a)
    pf("setw w", w.w)
    pf("getarr 0", w.a)
    pf("getarr 1", w.w)
    w.a = f32(-2.5)
    w.w = f32(17.0)
    pf("setarr a", w.a)
    pf("setarr w", w.w)

    wheel_fini(w)
    emit("fini vtable %08x" % w.vtable)


def s_compute_aux():
    rots = [0.75, 0.0, -0.4, 700.0, 6912.0, -700.0, -6912.0,
            628.317993, 628.318, 629.0, -628.317993]
    spins = [31.0, -31.0, 0.0, 9.99999975e-06, -9.99999975e-06,
             1.0e-05, -1.0e-05]
    signs = [0, 1, 2, 3]

    emit("[compute_aux]")
    for r in range(len(rots)):
        for s in range(len(spins)):
            for g in range(len(signs)):
                w = fresh()
                tag = "ca%d_%d_%d" % (r, s, g)
                w.a = f32(rots[r])
                w.w = f32(spins[s])
                w.LastSign = signs[g]
                compute_auxiliaries(w)
                pf(tag, w.a)
                pf(tag + " w", w.w)
                pint(tag + " sign", w.LastSign)

    w = fresh()
    w.a = f32(0.75)
    w.w = f32(31.0)
    w.LastSign = 1
    w.CurrentSlip = f32(4.5)
    compute_auxiliaries(w)
    dump("ca_full", w)


def s_exchange():
    # -0.0 separates `!(0 < z)` from `z < 0`; see the same list in
    # wheel_test.c.
    zs = [0.0, -0.0, -1.0, 1.0e-30, 4200.0, 12000.0]
    nz = [1.0, 0.99, 0.9, 0.8, 0.5, 0.0, -0.6]

    emit("[exchange]")
    for t in range(2):
        for z in range(len(zs)):
            for n in range(len(nz)):
                w = fresh()
                w.ContactNormal = (ZERO,
                                   f32(math.sqrt(1.0 - nz[n] * nz[n])),
                                   f32(nz[n]), f32(0.5))
                ret = exchange_z_forces(w, t, f32(zs[z]))
                tag = "ex%d_%d_%d" % (t, z, n)
                pf(tag, ret)
                pf(tag + " zf", w.ZForce)
                pint(tag + " tg", w.TouchingGround)
                emit("%s cp %s %s %s %s" % (
                    tag, g9(w.ContactPoint[0]), g9(w.ContactPoint[1]),
                    g9(w.ContactPoint[2]), g9(w.ContactPoint[3])))


def s_check_terrain():
    elevs = [0.0, 0.44, 1.5, -2.0]
    noises = [0.0, 0.03, -0.11]
    # The fourth is inside WHEEL_EPSILON but still positive, so the
    # reject is decided by the epsilon rather than by the sign. The fifth
    # has two huge opposed terms and a small one, which is where the dot
    # product's left-to-right association stops being a detail.
    normals = [(0.0, 0.0, 1.0),
               (0.3, -0.2, 0.9327379),
               (0.9, 0.4358899, 0.0),
               (0.9, 0.42, 0.0),
               (1.91073e8, 8.95907e7, 0.00100765)]

    emit("[check_terrain]")
    SEAM.on = True
    for k in range(5):
        for e in range(len(elevs)):
            for n in range(len(noises)):
                w = fresh()
                SEAM.calls = SEAM.noise_calls = SEAM.topology_calls = 0
                SEAM.terrain_out_null = False
                SEAM.ret = f32(elevs[e])
                SEAM.normal = (f32(normals[k][0]), f32(normals[k][1]),
                               f32(normals[k][2]), f32(0.25))
                SEAM.noise_ret = f32(noises[n])
                pos = (f32(11.5), f32(-3.25), f32(0.44), ONE)

                h = check_terrain(w, pos, world_matrix())
                tag = "ct%d_%d_%d" % (k, e, n)
                pf(tag, h)
                pint(tag + " terrain", w.Terrain)
                pf(tag + " noise", w.RoadNoise)
                emit("%s calls %d %d %d" % (tag, SEAM.calls,
                                            SEAM.noise_calls,
                                            SEAM.topology_calls))
                emit("%s terrain_out_null %d"
                     % (tag, 1 if SEAM.terrain_out_null else 0))
                pint(tag + " noise_terrain", SEAM.noise_terrain)
                emit("%s noise_xy %s %s" % (tag, g9(SEAM.noise_xy[0]),
                                            g9(SEAM.noise_xy[1])))
                emit("%s pos %s %s %s" % (tag, g9(SEAM.pos[0]),
                                          g9(SEAM.pos[1]), g9(SEAM.pos[2])))
                emit("%s topology 1" % tag)
                emit("%s normal %s %s %s %s" % (
                    tag, g9(w.ContactNormal[0]), g9(w.ContactNormal[1]),
                    g9(w.ContactNormal[2]), g9(w.ContactNormal[3])))

    SEAM.on = False
    w = fresh()
    pos = (f32(11.5), f32(-3.25), f32(0.44), ONE)
    h = check_terrain(w, pos, world_matrix())
    pf("ct_null", h)
    pint("ct_null terrain", w.Terrain)
    pf("ct_null noise", w.RoadNoise)
    emit("ct_null normal %s %s %s %s" % (
        g9(w.ContactNormal[0]), g9(w.ContactNormal[1]),
        g9(w.ContactNormal[2]), g9(w.ContactNormal[3])))
    SEAM.on = True


def s_derivative():
    global g_terrain_table, g_ugly_timestep
    spins = [31.0, -31.0, 0.0]
    slips = [0.0, 0.4, -0.9]

    emit("[derivative]")
    for table in range(2):
        g_terrain_table = TERRAIN if table else None
        for s in range(len(spins)):
            for c in range(len(slips)):
                for locked in range(2):
                    for slipping in range(2):
                        w = fresh()
                        out = [f32(-7.0), f32(-7.0)]
                        w.w = f32(spins[s])
                        w.CurrentSlip = f32(slips[c])
                        w.BrakeLocked = locked
                        w.Slipping = slipping
                        w.Terrain = 3
                        r = get_derivative(w, out)
                        tag = "dv%d_%d_%d_%d_%d" % (table, s, c, locked,
                                                    slipping)
                        emit("%s ret %d" % (tag, 1 if r is None else 0))
                        pf(tag, out[0])
                        pf(tag + " d1", out[1])
    g_terrain_table = TERRAIN

    hacks = [1.0, 0.001, 0.0005, 0.0, 2.0]
    saved = g_ugly_timestep
    for h in range(len(hacks)):
        w = fresh()
        out = [ZERO, ZERO]
        g_ugly_timestep = f32(hacks[h])
        w.CurrentSlip = f32(0.4)
        get_derivative(w, out)
        pf("dvh%d" % h, out[1])
    g_ugly_timestep = saved

    # Retail's damage drag: a blown tyre's Damage of 1, and two that are
    # not, each way round.
    dmgs = [1.0, 0.37, -0.5]
    for s in range(len(spins)):
        for d in range(len(dmgs)):
            w = fresh()
            out = [ZERO, ZERO]
            w.w = f32(spins[s])
            w.Damage = f32(dmgs[d])
            w.Terrain = 3
            get_derivative(w, out)
            pf("dvd%d_%d" % (s, d), out[1])


def s_brake_lock():
    vs = [0.0, 1.0, 40.0, 400.0, 4000.0]
    brakes = [0.0, 0.02, 0.25, 1.0]
    spins = [31.0, -31.0, 0.0]

    emit("[brake_lock]")
    for v in range(len(vs)):
        for b in range(len(brakes)):
            for e in range(len(brakes)):
                for s in range(len(spins)):
                    w = fresh()
                    w.Brake = f32(brakes[b])
                    w.EBrake = f32(brakes[e])
                    w.w = f32(spins[s])
                    check_for_brake_lock(w, f32(vs[v]))
                    tag = "bl%d_%d_%d_%d" % (v, b, e, s)
                    pint(tag + " locked", w.BrakeLocked)
                    pf(tag, w.w)


def s_pilot():
    speeds = [0.0, 13.4108181, 13.4229679, 14.0, 20.0, 22.351,
              22.3527927, 30.0, -5.0,
              # the one speed whose t rounds differently in float; see the
              # same list in wheel_test.c
              13.5429182]

    emit("[pilot]")
    for n in range(4):
        for s in range(len(speeds)):
            w = fresh()
            g_wi.WheelNumber = n
            g_cs.ForwardSpeed = f32(speeds[s])
            pf("pf%d_%d" % (n, s), get_pilot_factor(w))
    g_wi.WheelNumber = 2
    g_cs.ForwardSpeed = f32(20.0)

    w = fresh()
    w.BrakeLocked = 1
    pf("pf_locked", get_pilot_factor(w))
    w = fresh()
    w.w = f32(-0.5)
    pf("pf_reverse", get_pilot_factor(w))
    w = fresh()
    w.w = ZERO
    pf("pf_stopped", get_pilot_factor(w))


def s_lateral():
    global g_use_new
    # The first nine walk the index from 0 to just past 6 in steps of
    # about one, which is the only way the i < 6 ceiling, the truncation and
    # the interpolation between two neighbouring curves are reached at all:
    # every angle a car actually produces lands far past the end.
    angles = [0.0, 0.000222, 0.000445, 0.00089, 0.00134, 0.00178,
              0.00222, 0.00245, 0.00266,
              0.01, 0.0223402, 0.05, 0.1, 0.14, 0.2, 0.223402172,
              0.3, 0.5, 1.0]
    zf = [0.0, 1200.0, 5200.0, 9000.0]

    emit("[lateral]")
    saved = g_use_new
    for model in range(2):
        g_use_new = model
        for z in range(len(zf)):
            for a in range(len(angles)):
                w = fresh()
                pf("lf%d_%d_%d" % (model, z, a),
                   get_lateral_force(w, f32(zf[z]), f32(angles[a])))
    g_use_new = saved


def s_guess():
    global g_terrain_table
    vx = [12.0, 0.4, 0.0, -12.0, -0.05]
    vy = [0.5, 0.0, -3.0]
    spins = [37.5, 0.0, -10.0, 1.25]
    brakes = [0.0, 0.4]
    speeds = [20.0, 0.2]

    emit("[guess]")
    g_terrain_table = TERRAIN

    for a in range(len(vx)):
        for b in range(len(vy)):
            for s in range(len(spins)):
                for k in range(2):
                    for e in range(2):
                        for f in range(2):
                            w = fresh()
                            w.WorldMatrix = identity()
                            w.Velocity = (f32(vx[a]), f32(vy[b]), ZERO, ZERO)
                            w.w = f32(spins[s])
                            w.Brake = f32(brakes[k])
                            w.EBrake = f32(brakes[e])
                            g_cs.ForwardSpeed = f32(speeds[f])
                            guess_ground_force(w)
                            tag = "gg%d_%d_%d_%d_%d_%d" % (a, b, s, k, e, f)
                            emit("%s gf %s %s" % (tag, g9(w.GroundForce[0]),
                                                  g9(w.GroundForce[1])))
                            emit("%s slip %s %s" % (tag, g9(w.Slip[0]),
                                                    g9(w.Slip[1])))
                            emit("%s cur %s %s" % (tag, g9(w.CurrentSlip),
                                                   g9(w.OldSlip)))
                            pf(tag + " at", w.AppliedTorque)
                            emit("%s flags %d %d" % (tag, w.Slipping,
                                                     w.BrakeLocked))
                            pf(tag + " spin", w.w)
    g_cs.ForwardSpeed = f32(20.0)

    ats = [-400.0, 400.0, 0.0]
    for t in range(3):
        for eb in range(2):
            w = fresh()
            w.WorldMatrix = identity()
            w.Velocity = (f32(12.0), f32(0.1), ZERO, ZERO)
            w.w = ZERO
            w.AppliedTorque = f32(ats[t])
            w.EBrake = f32(0.5) if eb else ZERO
            guess_ground_force(w)
            tag = "gr%d_%d" % (t, eb)
            pf(tag + " at", w.AppliedTorque)
            emit("%s gf %s %s" % (tag, g9(w.GroundForce[0]),
                                  g9(w.GroundForce[1])))

    # The friction circle small enough to matter. With the fixture's
    # ZForce every demand CheckForBrakeLock sees is thousands of newtons and
    # no brake setting can lock anything, so the whole locked half of this
    # function -- the two torque refusals, the locked slipping trigger and
    # which speed the per-newton scale is taken against -- is unreachable
    # until the wheel is barely loaded.
    #
    # spin 32.5 against vx 12 puts the slip at 10, twenty-five times the
    # road speed, which is where dividing by the slide magnitude instead of
    # by the road speed stops agreeing.
    #
    # This comment used to claim vx 0.4 with spin 1.25 put the slip at
    # exactly zero and so reached the zero-magnitude early-out. It does
    # not: 1.25 * 0.32f is 0.399999976, leaving a slip of -2.98e-08. See
    # the `gm` block below, and the same note in wheel_test.c.
    gvx = [0.4, 12.0]
    gvy = [0.0, -3.0]
    gspin = [1.25, 32.5]
    gzf = [3900.0, 5.0]
    gbk = [0.0, 0.05, 0.4]
    for a in range(2):
        for b in range(2):
            for s in range(2):
                for z in range(2):
                    for k in range(3):
                        for l in range(2):
                            w = fresh()
                            w.WorldMatrix = identity()
                            w.Velocity = (f32(gvx[a]), f32(gvy[b]),
                                          ZERO, ZERO)
                            w.w = f32(gspin[s])
                            w.ZForce = f32(gzf[z])
                            w.Brake = f32(gbk[k])
                            w.EBrake = f32(gbk[k])
                            w.BrakeLocked = l
                            guess_ground_force(w)
                            tag = "gz%d_%d_%d_%d_%d_%d" % (a, b, s, z, k, l)
                            emit("%s gf %s %s" % (tag, g9(w.GroundForce[0]),
                                                  g9(w.GroundForce[1])))
                            emit("%s slip %s %s" % (tag, g9(w.Slip[0]),
                                                    g9(w.Slip[1])))
                            emit("%s cur %s %s" % (tag, g9(w.CurrentSlip),
                                                   g9(w.OldSlip)))
                            pf(tag + " at", w.AppliedTorque)
                            emit("%s flags %d %d" % (tag, w.Slipping,
                                                     w.BrakeLocked))
                            pf(tag + " spin", w.w)

    # mag == 0, the first early-out. 37.5 * 0.32f is 12 exactly, so slip is
    # zero and so is the magnitude, while vx stays 12 and keeps the second
    # early-out out of it. Run loaded-and-free and barely-loaded-and-braked
    # because perMag is read only on the slipping arm; see wheel_test.c.
    mzspin = [37.5, -37.5]
    mzvx   = [12.0, -12.0]
    mzzf   = [3900.0, 5.0]
    mzbk   = [0.0, 0.4]
    for d in range(2):
        for q in range(2):
            w = fresh()
            w.WorldMatrix = identity()
            w.Velocity = (f32(mzvx[d]), ZERO, ZERO, ZERO)
            w.w = f32(mzspin[d])
            w.ZForce = f32(mzzf[q])
            w.Brake = f32(mzbk[q])
            w.EBrake = f32(mzbk[q])
            guess_ground_force(w)
            tag = "gm%d_%d" % (d, q)
            emit("%s gf %s %s" % (tag, g9(w.GroundForce[0]),
                                  g9(w.GroundForce[1])))
            emit("%s slip %s %s" % (tag, g9(w.Slip[0]), g9(w.Slip[1])))
            pf(tag + " cur", w.CurrentSlip)
            emit("%s flags %d %d" % (tag, w.Slipping, w.BrakeLocked))

    # |slip| exactly gMaxStaticSlip with the angle small enough that the
    # trigger is the only thing deciding. 1.75 * 0.32f is 0.560000002 and
    # 0.06f takes it to exactly 0.5; spin 0 against vx 0.5f gives -0.5. The
    # `gs` pair below keeps vx at 0 and vy at -3, which sets Slipping on the
    # angle test whichever way the trigger goes.
    tbspin = [1.75, 0.0]
    tbvx   = [0.06, 0.5]
    for d in range(2):
        w = fresh()
        w.WorldMatrix = identity()
        w.Velocity = (f32(tbvx[d]), ZERO, ZERO, ZERO)
        w.w = f32(tbspin[d])
        w.Brake = ZERO
        w.EBrake = ZERO
        guess_ground_force(w)
        tag = "gt%d" % d
        emit("%s gf %s %s" % (tag, g9(w.GroundForce[0]),
                              g9(w.GroundForce[1])))
        pf(tag + " cur", w.CurrentSlip)
        emit("%s flags %d %d" % (tag, w.Slipping, w.BrakeLocked))

    # |slip| exactly gMaxStaticSlip. 1.5625 * 0.32 is 0.5 with no rounding
    # at all, so the trigger's `<` is decided on equality and nothing else.
    for i, sp in enumerate([1.5625, -1.5625]):
        w = fresh()
        w.WorldMatrix = identity()
        w.Velocity = (ZERO, f32(-3.0), ZERO, ZERO)
        w.w = f32(sp)
        guess_ground_force(w)
        tag = "gs%d" % i
        emit("%s gf %s %s" % (tag, g9(w.GroundForce[0]),
                              g9(w.GroundForce[1])))
        pf(tag + " cur", w.CurrentSlip)
        emit("%s flags %d %d" % (tag, w.Slipping, w.BrakeLocked))

    # The walking-pace divide, with a friction coefficient on each side of
    # the 0.1 floor that guards it. A traction boost of 0.05 takes the
    # product below the floor without touching anything else.
    for i, boost in enumerate([1.25, 0.05]):
        w = fresh()
        w.WorldMatrix = identity()
        w.Velocity = (ZERO, f32(-3.0), ZERO, ZERO)
        w.w = f32(10.0)
        w.TractionBoost = f32(boost)
        g_cs.ForwardSpeed = f32(0.2)
        guess_ground_force(w)
        tag = "gd%d" % i
        emit("%s gf %s %s" % (tag, g9(w.GroundForce[0]),
                              g9(w.GroundForce[1])))
        emit("%s flags %d %d" % (tag, w.Slipping, w.BrakeLocked))
    g_cs.ForwardSpeed = f32(20.0)

    vys = [3.0, -3.0]
    vxs = [9.0, -9.0]
    for i in range(2):
        for j in range(2):
            w = fresh()
            w.Velocity = (f32(vxs[i]), f32(vys[j]), f32(1.5), f32(0.25))
            guess_ground_force(w)
            dump("gw%d_%d" % (i, j), w)

    w = fresh()
    g_terrain_table = None
    w.WorldMatrix = identity()
    w.Velocity = (f32(12.0), f32(0.5), ZERO, ZERO)
    guess_ground_force(w)
    dump("gg_noterrain", w)
    g_terrain_table = TERRAIN


def tilted_matrix():
    return [(f32(0.78), f32(0.55), f32(-0.3), ZERO),
            (f32(-0.61), f32(0.74), f32(0.28), ZERO),
            (f32(0.1), f32(-0.2), f32(0.97), f32(0.3)),
            (f32(2.5), f32(-1.25), f32(0.4), ONE)]


def s_modify():
    xs = [0.0, 2.5, -7.0]
    ys = [0.0, 1.5]

    emit("[modify]")
    for m in range(2):
        for i in range(len(xs)):
            for j in range(len(ys)):
                w = fresh()
                # The fixture's car matrix has (0, 0, 1, 0) for its third
                # row, so whatever goes into the input's z lands only in
                # the output's z, which nothing reads. The tilted one does
                # not, which is what makes that lane observable.
                if m:
                    w.CarMatrix = tilted_matrix()
                modify_ground_force(w, (f32(xs[i]), f32(ys[j])))
                tag = "mg%d_%d_%d" % (m, i, j)
                pf(tag, w.GroundForce[0])
                pf(tag + " gf1", w.GroundForce[1])


def s_finalize():
    global g_force_frame, g_terrain_table
    frames = [0, 1, 2, 3, 4, 5]
    torques = [260.0, -260.0, 0.0]
    gf0 = [140.0, 26000.0, 0.0005]
    zf = [3900.0, 0.0, 0.0002]
    saved = g_force_frame

    emit("[finalize]")
    g_terrain_table = TERRAIN

    for fr in range(len(frames)):
        w = fresh()
        g_force_frame = frames[fr]
        finalize_ground_force(w)
        tag = "fr%d" % fr
        emit("%s wgf %s %s %s %s" % (
            tag, g9(w.WorldGroundForce[0]), g9(w.WorldGroundForce[1]),
            g9(w.WorldGroundForce[2]), g9(w.WorldGroundForce[3])))
        emit("%s gf %s %s" % (tag, g9(w.GroundForce[0]),
                              g9(w.GroundForce[1])))
        pf(tag + " tu", w.TractionUsage)

    # The dot product associates left to right, and float addition is not
    # associative. The row here is nearly parallel to the contact normal,
    # so flattening cancels almost all of it and the residue carries the
    # whole rounding error; frame 3 then normalises the residue. Frame 2
    # comes out the same either way. See the same block in wheel_test.c.
    dn = [0.2512, 0.5665, -0.7848]
    dv = [0.2399223, 0.5410649, -0.7495642]
    for d, fr in enumerate([2, 3]):
        w = fresh()
        g_force_frame = fr
        w.ContactNormal = (f32(dn[0]), f32(dn[1]), f32(dn[2]), f32(0.5))
        w.WorldMatrix = [tuple(r) for r in w.WorldMatrix]
        w.WorldMatrix[0] = (f32(dv[0]), f32(dv[1]), f32(dv[2]), f32(0.25))
        finalize_ground_force(w)
        tag = "fd%d" % d
        emit("%s wgf %s %s %s %s" % (
            tag, g9(w.WorldGroundForce[0]), g9(w.WorldGroundForce[1]),
            g9(w.WorldGroundForce[2]), g9(w.WorldGroundForce[3])))
        emit("%s gf %s %s" % (tag, g9(w.GroundForce[0]),
                              g9(w.GroundForce[1])))
    g_force_frame = saved

    # Both components inside WHEEL_EPSILON. The clamp's second test is
    # the only thing between a tiny force and a scale factor that means
    # nothing at that size; with GroundForce[1] pinned at -220 everywhere
    # else, the magnitude is never small enough for it to decide anything.
    tiny0 = [0.0005, 0.0]
    tiny1 = [0.0002, 0.0]
    tinyz = [0.0, 0.0002, 3900.0]
    for i in range(2):
        for j in range(2):
            for z in range(3):
                w = fresh()
                w.GroundForce = [f32(tiny0[i]), f32(tiny1[j])]
                w.ZForce = f32(tinyz[z])
                finalize_ground_force(w)
                tag = "ft%d_%d_%d" % (i, j, z)
                emit("%s gf %s %s" % (tag, g9(w.GroundForce[0]),
                                      g9(w.GroundForce[1])))
                pf(tag + " tu", w.TractionUsage)
                emit("%s wgf %s %s %s %s" % (
                    tag, g9(w.WorldGroundForce[0]),
                    g9(w.WorldGroundForce[1]),
                    g9(w.WorldGroundForce[2]),
                    g9(w.WorldGroundForce[3])))

    for t in range(len(torques)):
        for g in range(len(gf0)):
            for z in range(len(zf)):
                for locked in range(2):
                    for slipping in range(2):
                        for touching in range(2):
                            w = fresh()
                            w.AppliedTorque = f32(torques[t])
                            w.GroundForce = [f32(gf0[g]), f32(-220.0)]
                            w.ZForce = f32(zf[z])
                            w.BrakeLocked = locked
                            w.Slipping = slipping
                            w.TouchingGround = touching
                            finalize_ground_force(w)
                            tag = "fg%d_%d_%d_%d_%d_%d" % (t, g, z, locked,
                                                           slipping,
                                                           touching)
                            emit("%s gf %s %s" % (tag, g9(w.GroundForce[0]),
                                                  g9(w.GroundForce[1])))
                            pf(tag + " tu", w.TractionUsage)
                            emit("%s wgf %s %s %s %s" % (
                                tag, g9(w.WorldGroundForce[0]),
                                g9(w.WorldGroundForce[1]),
                                g9(w.WorldGroundForce[2]),
                                g9(w.WorldGroundForce[3])))

    vxs = [9.0, -9.0, 0.5, -0.5, 1.0]
    for i in range(len(vxs)):
        w = fresh()
        w.WorldMatrix = identity()
        w.Velocity = (f32(vxs[i]), f32(2.0), ZERO, ZERO)
        finalize_ground_force(w)
        pf("fb%d" % i, w.GroundForce[0])
        pf("fb%d gf1" % i, w.GroundForce[1])

    for k in range(1, 5):
        w = fresh()
        g_force_frame = k
        finalize_ground_force(w)
        dump("ff%d" % k, w)
    g_force_frame = saved

    w = fresh()
    g_terrain_table = None
    finalize_ground_force(w)
    dump("fg_noterrain", w)
    g_terrain_table = TERRAIN


def s_horizontal():
    f0 = [140.0, 0.0, -300.0]
    f1 = [-220.0, 0.0]

    emit("[horizontal]")
    for i in range(len(f0)):
        for j in range(len(f1)):
            w = fresh()
            w.GroundForce = [f32(f0[i]), f32(f1[j])]
            emit("hw%d_%d ret 1" % (i, j))
            o = horizontal_in(w.WorldMatrix, w.GroundForce[0],
                              w.GroundForce[1])
            emit("hw%d_%d %s %s %s %s" % (i, j, g9(o[0]), g9(o[1]),
                                          g9(o[2]), g9(o[3])))
            o = horizontal_in(w.CarMatrix, w.GroundForce[0],
                              w.GroundForce[1])
            emit("hc%d_%d %s %s %s %s" % (i, j, g9(o[0]), g9(o[1]),
                                          g9(o[2]), g9(o[3])))

    w = fresh()
    dump("hooks", w)


def s_accessors():
    emit("[accessors]")
    w = fresh()
    pf("moi", w.MomentOfInertia)
    pf("damage", w.Damage)
    w.Damage = f32(0.37)
    pf("damage2", w.Damage)

    for n in range(4):
        g_wi.WheelNumber = n
        pint("steer%d" % n, 1 if n < 2 else 0)
        pint("drive%d" % n, (1 if n < 2 else 0) ^ 1)
    g_wi.WheelNumber = 2

    w.OldSlip = f32(1.5)
    w.CurrentSlip = f32(-2.5)
    pf("oldslip", w.OldSlip)
    pf("curslip", w.CurrentSlip)

    w.Slipping = 1
    pint("slipping", w.Slipping)
    w.Slipping = 0
    pint("slipping2", w.Slipping)

    w.AppliedTorque = f32(100.0)
    w.BrakeLocked = 0
    w.AppliedTorque = fadd(w.AppliedTorque, f32(25.0))
    pf("torque", w.AppliedTorque)
    w.BrakeLocked = 1
    pf("torque_locked", w.AppliedTorque)
    w.BrakeLocked = 0

    pf("zforce", w.ZForce)
    pf("mass", ONE)
    pf("radius", w.WI.Radius)

    emit("cn 1")
    emit("cp 1")
    emit("gfv 1")
    emit("restpos 1")
    emit("restpos v %s %s %s %s" % (g9(g_wi.PositionX), g9(g_wi.PositionY),
                                    g9(g_wi.PositionZ), g9(g_wi.Radius)))

    w.ContactNormal = (f32(0.2), f32(0.3), f32(0.9), f32(-1.5))
    pv("setcn", w.ContactNormal)
    w.ContactPoint = (f32(4.0), f32(5.0), f32(6.0), f32(7.0))
    pv("setcp", w.ContactPoint)
    w.Velocity = (f32(-1.0), f32(-2.0), f32(-3.0), f32(-4.0))
    pv("setvel", w.Velocity)

    m = identity()
    m[3] = (f32(9.0), ZERO, ZERO, ONE)
    w.CarMatrix = [r for r in m]
    pm("setcar", w.CarMatrix)
    m[3] = (f32(9.0), f32(-9.0), ZERO, ONE)
    w.WorldMatrix = [r for r in m]
    pm("setworld", w.WorldMatrix)

    w.TouchingGround = 1
    pint("tg", w.TouchingGround)
    w.RoadNoise = f32(0.55)
    pf("noise_on", w.RoadNoise)
    w.TouchingGround = 0
    pint("tg2", w.TouchingGround)
    pf("noise_off", ZERO)
    w.TouchingGround = 1

    w.Terrain = 4
    pint("terrain", w.Terrain)

    w.Slip = [f32(3.5), f32(-6.5)]
    w.CurrentSlip = f32(3.5)
    pf("slip0", w.Slip[0])
    pf("slip1", w.Slip[1])
    pf("slipcur", w.CurrentSlip)
    emit("slipptr 1")

    w.TractionUsage = f32(0.62)
    pf("tu", w.TractionUsage)

    pint("mod00", 1)
    pint("mod10", 0)
    pint("mod01", 0)
    pint("mod11", 0)
    w.Slipping = 0
    w.BrakeLocked = 0

    emit("matptr 1")
    emit("carptr 1")
    pf("at", w.AppliedTorque)
    pf("tresp", fdiv(ONE, w.MomentOfInertia))
    pf("angacc", fdiv(fsub(w.AppliedTorque,
                           fmul(w.GroundForce[0], w.WI.Radius)),
                      w.MomentOfInertia))
    pf("angvel", w.w)
    pf("rot", w.a)

    w.CatchupFrictionMultiplier = f32(1.35)
    pf("catchup", w.CatchupFrictionMultiplier)
    w.TractionBoost = fmul(w.TractionBoost, f32(0.5))
    pf("boost", w.TractionBoost)
    w.TractionBoost = f32(2.25)
    pf("boost2", w.TractionBoost)
    w.EBrake = f32(0.8)
    pf("ebrake", w.EBrake)
    w.Brake = f32(0.45)
    pf("brake", w.Brake)

    # SetSliderValue is empty in the image, so the globals are unchanged;
    # printing them here is what makes that checkable. See wheel_test.c.
    dump_globals("slider")

    rm = identity()
    rm[0] = (ZERO, ONE, ZERO, ZERO)
    rm[1] = (f32(-1.0), ZERO, ZERO, ZERO)
    rm[3] = (f32(100.0), f32(200.0), f32(300.0), ONE)
    o = bRotateVector(rm, (f32(2.0), f32(3.0), f32(4.0)))
    emit("rotvec %s %s %s" % (g9(o[0]), g9(o[1]), g9(o[2])))

    dump("acc", w)


def s_snapshot():
    emit("[snapshot]")

    # What a take of another wheel left: State.a 2.5, State.w -6 and
    # LastSign -2.
    was = struct.pack("<ffi", 2.5, -6.0, -2)
    modes = [("sntake", Snap(take=1)),
             ("snrest", Snap(restore=1, data=was)),
             ("snsum", Snap(csum=1)),
             ("snnone", Snap())]
    for tag, snap in modes:
        w = fresh()
        w.Pad2 = 0xa5a5a5a5
        w.LastSign = 3
        w.RoadNoise = f32(0.55)
        w.Damage = f32(0.37)
        w.NumTimesSkidding = 9
        w.SkidSet = 0x777

        do_snapshot(w, snap)

        sec = snap.sec
        emit("%s depth %d sections %d" % (tag, snap.depth, snap.number))
        emit("%s sec %s obj %d num %d moves %d size %d"
             % (tag, sec["name"], sec["obj"], sec["num"], sec["moves"],
                sec["size"]))
        emit("%s pos %d data%s" % (tag, snap.pos, "".join(
            " %02x" % b for b in snap.data[:snap.pos])))
        emit("%s skid %d" % (tag, 1 if w.SkidSet == 0x777 else 0))
        emit("%s pad %08x" % (tag, w.Pad2))
        dump(tag, w)


# ------------------------------------------- SetState(CarState *, ...)

class SWI(object):
    def __init__(self, i):
        self.PositionX = f32(-1.4) if (i & 1) else f32(1.4)
        self.PositionY = f32(0.78) if i < 2 else f32(-0.92)
        self.PositionZ = f32(-0.35)
        self.Radius = fadd(f32(0.32), fmul(f32(0.01), f32(i)))
        self.Width = f32(0.21)
        self.WheelNumber = i
        self.OffsetY = f32(0.03) if (i & 1) else f32(-0.02)


SWI_ALL = [SWI(i) for i in range(4)]
TOPOLOGY = object()


class SetStateCarState(CST.State):
    """carstate_check's State does not carry pTopologyCoordinate, because
    nothing in that slice reads it. Wheel does: the elevation call takes it
    straight out of the record rather than through the seam CheckTerrain
    needs. The field is at 4 in the image; the slot is added here rather
    than in the other model so that model stays the shape its own
    transcript pins."""

    __slots__ = ("pTopologyCoordinate",)


def setstate_state():
    cs = SetStateCarState()
    info = CST.Info()
    info.CenterOfGravity = [f32(0.02), f32(-0.15), f32(0.44), ONE]
    for i in range(4):
        wi = SWI_ALL[i]
        info.Wheels[i] = dict(x=wi.PositionX, y=wi.PositionY,
                              z=wi.PositionZ, r=wi.Radius, oy=wi.OffsetY)
    cs.pCarInfo = info
    cs.pTopologyCoordinate = TOPOLOGY
    cs.ForwardSpeed = f32(20.0)

    cs.BodyMatrix = [
        f32(0.936293435), f32(0.351175636), f32(-0.0174524058), f32(0.125),
        f32(-0.348570138), f32(0.929229140), f32(0.121869341), f32(-0.0625),
        f32(0.0523359589), f32(-0.111618653), f32(0.992403865), f32(0.25),
        f32(77.0), f32(-88.0), f32(99.0), f32(0.5)]

    cs.Position = [f32(120.5), f32(-34.25), f32(6.75), f32(0.375)]
    cs.Velocity = [f32(18.0), f32(-2.5), f32(0.125), f32(-0.75)]
    cs.AngularVelocity = [f32(0.21), f32(-0.34), f32(1.05), f32(0.5)]
    return cs


def s_carstate():
    # Wheel 2 is a rear wheel, so CalculateWheelMatrices leaves the steering
    # out; wheel 0 is a front one, so the same angle turns two matrices.
    # Both are needed -- nothing else in this transcript reaches the
    # steering rotation.
    nums = [2, 0]
    angles = [0.75, -3.5]
    steers = [0, 8192]

    emit("[carstate]")
    cs = setstate_state()
    saved = SEAM.on

    for seam in range(2):
        SEAM.on = bool(seam)
        for a in range(len(nums)):
            for b in range(len(angles)):
                for c in range(len(steers)):
                    w = fresh()
                    n = nums[a]
                    w.WI = SWI_ALL[n]

                    SEAM.calls = 0
                    SEAM.terrain_out_null = None
                    SEAM.topology_arg = None
                    SEAM.pos4 = (ZERO, ZERO, ZERO, ZERO)
                    SEAM.ret = f32(4.5)
                    SEAM.normal = (f32(0.12), f32(-0.3), f32(0.946),
                                   f32(0.625))

                    cs.WheelTouchingGround = [0] * 4
                    cs.WheelTerrain = [0] * 4
                    cs.CrossedWheelTerrain = [0] * 4
                    cs.nWheelsTouchingGround = 0
                    cs.SteeringAngle = 0

                    set_state_from_car_state(w, cs, f32(angles[b]),
                                             f32(-17.5), steers[c],
                                             f32(0.045))

                    tag = "cs%d_%d_%d_%d" % (seam, a, b, c)
                    emit("%s steer %d" % (tag, cs.SteeringAngle))
                    pf(tag + " wav", cs.WheelAngularVelocity[n])
                    pf(tag + " wa", cs.WheelAngle[n])
                    pf(tag + " wsh", cs.WheelSuspensionHeight[n])
                    emit("%s tg %d %d" % (tag, cs.WheelTouchingGround[n],
                                          cs.nWheelsTouchingGround))
                    emit("%s terr %d %d" % (tag, cs.WheelTerrain[n],
                                            cs.CrossedWheelTerrain[n]))
                    pm(tag + " wm", rows(cs.WheelMatrix[n]))
                    pm(tag + " bm", rows(cs.BrakeMatrix[n]))
                    emit("%s elev %d out %d"
                         % (tag, SEAM.calls,
                            0 if SEAM.terrain_out_null is not False else 1))
                    emit("%s epos %s %s %s %s" % (
                        tag, g9(SEAM.pos4[0]), g9(SEAM.pos4[1]),
                        g9(SEAM.pos4[2]), g9(SEAM.pos4[3])))
                    emit("%s etop %d"
                         % (tag, 1 if SEAM.topology_arg is TOPOLOGY else 0))
                    dump(tag, w)

    SEAM.on = saved


def s_seams():
    emit("[seams]")
    emit("before 0 0")
    emit("after 1 1")
    emit("again 1 1")


SCENARIOS = [s_layout, s_constants, s_statics, s_lifetime, s_compute_aux,
             s_exchange, s_check_terrain, s_derivative, s_brake_lock,
             s_pilot, s_lateral, s_guess, s_modify, s_finalize,
             s_horizontal, s_accessors, s_snapshot, s_carstate, s_seams]


def model():
    global g_terrain_table, g_force_frame, g_use_new, g_ugly_timestep
    del OUT[:]
    static_init()
    g_terrain_table = TERRAIN
    g_force_frame = G_WHEEL_FORCE_FRAME
    g_use_new = G_USE_NEW_TIRE_FORCES
    g_ugly_timestep = f32(G_UGLY_TIMESTEP_HACK)
    g_wi.WheelNumber = 2
    g_cs.ForwardSpeed = f32(20.0)
    for s in SCENARIOS:
        s()
    return list(OUT)


# -------------------------------------------------------------- the harness

# A mutation can turn a `for (;;)` into a loop with no exit. With no
# deadline here that mutant spins until something kills it and stalls the
# whole pass rather than being counted; the harness itself runs in well
# under a second.
HARNESS_TIMEOUT = 60
HARNESS_HUNG = -9999


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


def diff(a, b, quiet=False):
    d = list(difflib.unified_diff(a, b, "model", "harness", lineterm="", n=1))
    if d and not quiet:
        for ln in d[:80]:
            print(ln)
        if len(d) > 80:
            print("... %d more diff lines" % (len(d) - 80))
    return len([x for x in d if x.startswith(("+", "-"))
                and not x.startswith(("+++", "---"))])


# ------------------------------------------------------------ the mutations

MUTATIONS = [
    # -- the layout ---------------------------------------------------------
    ("wh-state-swapped", WH,
     "    float a; // 0" + NL + "    float w; // 4",
     "    float w; // 0" + NL + "    float a; // 4"),
    ("wh-terrain-is-pointer", WH,
     "    int32_t   Terrain;                   // 336  TerrainType, a 32-bit enum",
     "    void     *Terrain;                   // 336"),
    ("wh-pad2-gone", WH,
     "    uint8_t   _pad2[4];                  // 284  WorldGroundForce is",
     "    uint8_t   _pad2[0];                  // 284  WorldGroundForce is"),
    ("wh-pad0-short", WH,
     "    uint8_t   _pad0[8];                  //  40  Matrix is 16-aligned",
     "    uint8_t   _pad0[4];                  //  40  Matrix is 16-aligned"),
    ("wh-slip-and-groundforce-swapped", WH,
     "    float     Slip[2];                   // 256" + NL
     + "    float     AppliedTorque;             // 264",
     "    float     AppliedTorque;             // 256" + NL
     + "    float     Slip[2];                   // 260"),
    ("wh-terraininfo-static-dynamic-swapped", TT,
     "    float       StaticFrictionMultiplier;    //  32" + NL
     + "    float       DynamicFrictionMultiplier;   //  36",
     "    float       DynamicFrictionMultiplier;   //  32" + NL
     + "    float       StaticFrictionMultiplier;    //  36"),
    ("wh-terraininfo-no-pad", TT,
     "    uint8_t     _pad0[2];                    //  14",
     "    uint8_t     _pad0[0];                    //  14"),

    # -- the constants ------------------------------------------------------
    ("wh-pi-rounded", WH,
     "#define WHEEL_IMAGE_PI       3.14159012f",
     "#define WHEEL_IMAGE_PI       3.14159274f"),
    ("wh-half-pi-rounded", WH,
     "#define WHEEL_IMAGE_HALF_PI  1.57079649f",
     "#define WHEEL_IMAGE_HALF_PI  1.5708f"),
    ("wh-two-pi-is-2x-pi", WH,
     "#define WHEEL_IMAGE_TWO_PI   6.28318024f",
     "#define WHEEL_IMAGE_TWO_PI   6.28318548f"),
    ("wh-bam-scale", WH,
     "#define WHEEL_BAM_TO_RAD     9.58738019e-05f",
     "#define WHEEL_BAM_TO_RAD     9.58737000e-05f"),
    ("wh-give-up-is-fold", WH,
     "#define WHEEL_ROT_GIVE_UP    6283.17969f",
     "#define WHEEL_ROT_GIVE_UP    628.317993f"),
    ("wh-zforce-floor", WH,
     "#define WHEEL_ZFORCE_FLOOR   0.300000012f",
     "#define WHEEL_ZFORCE_FLOOR   0.0f"),
    ("wh-rad-to-deg", WH,
     "#define WHEEL_RAD_TO_DEG     57.2957764f",
     "#define WHEEL_RAD_TO_DEG     57.2957795f"),
    ("wh-no-surface", WH,
     "#define WHEEL_NO_SURFACE     (-100.0f)",
     "#define WHEEL_NO_SURFACE     (0.0f)"),

    # -- the tuning globals -------------------------------------------------
    ("wh-pilot-factor", WC,
     "float   gPilotFactor                    = 0.850000024f;",
     "float   gPilotFactor                    = 0.800000012f;"),
    ("wh-rolling-friction", WC,
     "float   gRollingFriction                = 0.00200000009f;",
     "float   gRollingFriction                = 0.00300000001f;"),
    ("wh-use-new-tire-forces-off", WC,
     "int32_t gUseNewTireForces               = 1;",
     "int32_t gUseNewTireForces               = 0;"),
    ("wh-max-slip-angle-global", WC,
     "    gMaxSlipAngleGlobal = 0.223402172f;",
     "    gMaxSlipAngleGlobal = 0.25f;"),

    # -- the static constructor --------------------------------------------
    ("wh-cornering-range-is-ten", WC,
     "    table_init(&gCorneringForce, gCorneringForceTable," + NL
     + "               WHEEL_CORNERING_ENTRIES, 0.0f, gMaxSlipAngleGlobal);",
     "    table_init(&gCorneringForce, gCorneringForceTable," + NL
     + "               WHEEL_CORNERING_ENTRIES, 0.0f, 10.0f);"),
    ("wh-load-range-is-slip", WC,
     "        table_init(&gLoadSensitivity[i], entries[i]," + NL
     + "                   WHEEL_LOAD_TABLE_ENTRIES, 0.0f, 10.0f);",
     "        table_init(&gLoadSensitivity[i], entries[i]," + NL
     + "                   WHEEL_LOAD_TABLE_ENTRIES, 0.0f," + NL
     + "                   gMaxSlipAngleGlobal);"),
    ("wh-twelve-degree-entry", WC,
     "    0.0f, 1.89999998f, 3.79999995f, 5.19999981f, 6.30000019f, 7.0999999f",
     "    0.0f, 1.89999998f, 3.79999995f, 5.19999981f, 6.30000019f, 7.19999981f"),
    ("wh-cornering-last-entry-rises", WC,
     "    0.0f, 0.400000006f, 0.800000012f, 1.20000005f, 1.60000002f, 1.75f," + NL
     + "    1.64999998f",
     "    0.0f, 0.400000006f, 0.800000012f, 1.20000005f, 1.60000002f, 1.75f," + NL
     + "    1.85000002f"),

    # -- the VU idioms ------------------------------------------------------
    ("wh-dot3-associates-right", WC,
     "    return (x + y) + z;",
     "    return x + (y + z);"),
    ("wh-dot3-is-four-lane", WC,
     "    float z = a->z * b->z;" + NL + "    return (x + y) + z;",
     "    float z = a->z * b->z;" + NL
     + "    return ((x + y) + z) + a->w * b->w;"),
    ("wh-cross3-w-zeroed", WC,
     "    o->w = a->w;",
     "    o->w = 0.0f;"),
    ("wh-cross3-reversed", WC,
     "    float x = a->y * b->z - b->y * a->z;",
     "    float x = b->y * a->z - a->y * b->z;"),
    ("wh-normalize-skips-w", WC,
     "    v->x *= inv;" + NL + "    v->y *= inv;" + NL + "    v->z *= inv;"
     + NL + "    v->w *= inv;",
     "    v->x *= inv;" + NL + "    v->y *= inv;" + NL + "    v->z *= inv;"),

    # -- lifetime -----------------------------------------------------------
    ("wh-init-lastsign-zero", WC,
     "    w->CI = ci;" + NL + "    w->LastSign = 1;",
     "    w->CI = ci;" + NL + "    w->LastSign = 0;"),
    ("wh-init-boost-zero", WC,
     "    w->TractionBoost = 1.0f;",
     "    w->TractionBoost = 0.0f;"),
    ("wh-init-writes-moi", WC,
     "    w->CatchupFrictionMultiplier = 1.0f;",
     "    w->CatchupFrictionMultiplier = 1.0f;" + NL
     + "    w->MomentOfInertia = gWheelMomentOfInertia;"),
    ("wh-fini-keeps-vtable", WC,
     "void wheel_fini(Wheel *w)" + NL + "{" + NL
     + "    w->_vtable = PHYSICSCOMPONENT_VTABLE;",
     "void wheel_fini(Wheel *w)" + NL + "{" + NL
     + "    w->_vtable = WHEEL_VTABLE;"),
    ("wh-state-array-swapped", WC,
     "    out[0] = w->State.a;" + NL + "    out[1] = w->State.w;",
     "    out[0] = w->State.w;" + NL + "    out[1] = w->State.a;"),

    # -- ComputeAuxiliaries -------------------------------------------------
    ("wh-aux-matrix-sign", WC,
     "    w->Matrix.v0.z = -s;",
     "    w->Matrix.v0.z = s;"),
    ("wh-aux-matrix-cos-is-sin", WC,
     "    c = bSinF(a + WHEEL_IMAGE_HALF_PI);",
     "    c = bSinF(a);"),
    ("wh-aux-keeps-torque", WC,
     "    w->AppliedTorque  = 0.0f;",
     "    w->AppliedTorque  = w->AppliedTorque;"),
    ("wh-aux-keeps-currentslip", WC,
     "    w->CurrentSlip    = 0.0f;",
     "    w->CurrentSlip    = w->CurrentSlip;"),
    ("wh-aux-fold-clamps", WC,
     "        if (WHEEL_ROT_GIVE_UP < f)" + NL + "            w->State.a = 0.0f;",
     "        if (WHEEL_ROT_GIVE_UP < f)" + NL
     + "            w->State.a = WHEEL_ROT_GIVE_UP;"),
    ("wh-aux-fold-inclusive", WC,
     "    if (WHEEL_ROT_FOLD < a) {",
     "    if (WHEEL_ROT_FOLD <= a) {"),
    ("wh-aux-sign-zero-clamps-positive", WC,
     "    if (sign == 0) {" + NL + "        if (w->State.w < 0.0f)",
     "    if (sign == 0) {" + NL + "        if (0.0f < w->State.w)"),
    ("wh-aux-sign-two-is-one", WC,
     "    } else if (sign == 2) {",
     "    } else if (sign == 1) {"),
    ("wh-aux-sign-epsilon-inclusive", WC,
     "    if (WHEEL_SPIN_EPSILON < w->State.w)",
     "    if (WHEEL_SPIN_EPSILON <= w->State.w)"),
    ("wh-aux-sign-stopped-is-zero", WC,
     "    else" + NL + "        w->LastSign = 1;",
     "    else" + NL + "        w->LastSign = 0;"),

    # -- ExchangeZForces ----------------------------------------------------
    ("wh-exchange-returns-zforce", WC,
     "        w->ZForce = z * d;" + NL + "    }" + NL + NL + "    return 0.0f;",
     "        w->ZForce = z * d;" + NL + "    }" + NL + NL
     + "    return w->ZForce;"),
    ("wh-exchange-contact-always", WC,
     "    if (touching != 0) {" + NL + "        float r = -w->WI->Radius;",
     "    if (1) {" + NL + "        float r = -w->WI->Radius;"),
    ("wh-exchange-radius-sign", WC,
     "        float r = -w->WI->Radius;",
     "        float r = w->WI->Radius;"),
    ("wh-exchange-contact-from-v2", WC,
     "        w->ContactPoint.x = w->ContactNormal.x * r + w->WorldMatrix.v3.x;",
     "        w->ContactPoint.x = w->ContactNormal.x * r + w->WorldMatrix.v2.x;"),
    ("wh-exchange-z-inclusive", WC,
     "    if (!(0.0f < z)) {",
     "    if (z < 0.0f) {"),
    ("wh-exchange-affine-shift", WC,
     "        d = d - 3.0f;",
     "        d = d - 2.0f;"),
    ("wh-exchange-affine-scale", WC,
     "        d = d * 4.0f;",
     "        d = d * 3.0f;"),
    ("wh-exchange-cross-order", WC,
     "        cross3(&u, &t, &w->WorldMatrix.v1);",
     "        cross3(&u, &w->WorldMatrix.v1, &t);"),
    ("wh-exchange-uses-v0", WC,
     "        cross3(&t, &w->WorldMatrix.v1, &w->ContactNormal);",
     "        cross3(&t, &w->WorldMatrix.v0, &w->ContactNormal);"),

    # -- CheckTerrain -------------------------------------------------------
    ("wh-terrain-out-null", WC,
     "        elev = gTopologyGetElevationFn(topo, pos, terrainOut, normalOut);",
     "        elev = gTopologyGetElevationFn(topo, pos, NULL, normalOut);"),
    ("wh-noise-not-stored", WC,
     "    w->RoadNoise = noise;",
     "    w->RoadNoise = 0.0f;"),
    ("wh-probe-z-is-elev", WC,
     "    probe.z = elev + noise;",
     "    probe.z = elev;"),
    ("wh-align-uses-v0", WC,
     "    align = (normalOut->x * r->v2.x + normalOut->y * r->v2.y)" + NL
     + "            + normalOut->z * r->v2.z;",
     "    align = (normalOut->x * r->v0.x + normalOut->y * r->v0.y)" + NL
     + "            + normalOut->z * r->v0.z;"),
    ("wh-align-epsilon-is-zero", WC,
     "    if (align < WHEEL_EPSILON) {",
     "    if (align < 0.0f) {"),
    ("wh-reject-keeps-terrain", WC,
     "        *terrainOut = 0;" + NL + "        return WHEEL_NO_SURFACE;",
     "        return WHEEL_NO_SURFACE;"),
    ("wh-delta-not-divided", WC,
     "        return num / align;",
     "        return num;"),
    ("wh-find-passes-contact-point", WC,
     "    return wheel_check_terrain(w, (bVector3 *)&w->ContactNormal, &w->Terrain,",
     "    return wheel_check_terrain(w, (bVector3 *)&w->ContactPoint, &w->Terrain,"),

    # -- GetDerivative ------------------------------------------------------
    ("wh-derivative-returns-out", WC,
     "    return NULL;" + NL + "}" + NL + NL
     + "// 0x0019a078. Called once a frame before the forces are resolved.",
     "    return out;" + NL + "}" + NL + NL
     + "// 0x0019a078. Called once a frame before the forces are resolved."),
    ("wh-derivative-rolling-not-scaled", WC,
     "    acc = acc - (w->State.w * rollingMul) * gRollingFriction;",
     "    acc = acc - w->State.w * gRollingFriction;"),
    ("wh-derivative-locked-not-zero", WC,
     "    if (w->BrakeLocked != 0)" + NL + "        out[1] = 0.0f;",
     "    if (0)" + NL + "        out[1] = 0.0f;"),
    ("wh-derivative-slip-guard-dropped", WC,
     "    if (w->Slipping == 0 && WHEEL_EPSILON < gUglyTimestepHack) {",
     "    if (WHEEL_EPSILON < gUglyTimestepHack) {"),
    ("wh-derivative-slip-added", WC,
     "        out[1] = out[1] - w->CurrentSlip / d;",
     "        out[1] = out[1] + w->CurrentSlip / d;"),
    ("wh-derivative-damage-dropped", WC,
     "    acc = acc - w->State.w * (w->Damage * WHEEL_DAMAGE_DRAG);" + NL,
     ""),
    ("wh-derivative-damage-scale", WC,
     "    acc = acc - w->State.w * (w->Damage * WHEEL_DAMAGE_DRAG);",
     "    acc = acc - w->State.w * (w->Damage * 0.2f);"),
    ("wh-derivative-damage-sign", WC,
     "    acc = acc - w->State.w * (w->Damage * WHEEL_DAMAGE_DRAG);",
     "    acc = acc + w->State.w * (w->Damage * WHEEL_DAMAGE_DRAG);"),
    ("wh-derivative-damage-unspun", WC,
     "    acc = acc - w->State.w * (w->Damage * WHEEL_DAMAGE_DRAG);",
     "    acc = acc - w->Damage * WHEEL_DAMAGE_DRAG;"),
    ("wh-derivative-damage-after", WC,
     "    acc = acc - w->State.w * (w->Damage * WHEEL_DAMAGE_DRAG);" + NL
     + "    acc = acc / w->MomentOfInertia;",
     "    acc = acc / w->MomentOfInertia;" + NL
     + "    acc = acc - w->State.w * (w->Damage * WHEEL_DAMAGE_DRAG);"),
    ("wh-derivative-force-sign", WC,
     "    acc = w->AppliedTorque - w->GroundForce[0] * w->WI->Radius;",
     "    acc = w->AppliedTorque + w->GroundForce[0] * w->WI->Radius;"),

    # -- CheckForBrakeLock and the pilot -----------------------------------
    ("wh-brakelock-threshold-unscaled", WC,
     "    float threshold = torque * gStaticToDynamicBrakeForceRatio;",
     "    float threshold = torque;"),
    ("wh-brakelock-no-spin-term", WC,
     "    float demand = v * w->WI->Radius" + NL
     + "                   + fabsf(w->State.w) * gBrakeLockAngularVelocityFactor;",
     "    float demand = v * w->WI->Radius;"),
    ("wh-brakelock-newton-gate-gone", WC,
     "        w->BrakeLocked = (1.0f < threshold) ? 1 : 0;",
     "        w->BrakeLocked = 1;"),
    ("wh-brakelock-does-not-stop", WC,
     "        w->State.w = 0.0f;" + NL + "    } else {" + NL
     + "        w->BrakeLocked = 0;",
     "    } else {" + NL + "        w->BrakeLocked = 0;"),
    ("wh-pilot-front-wheels", WC,
     "    if (w->WI->WheelNumber < 2)" + NL + "        return 1.0f;",
     "    if (w->WI->WheelNumber >= 2)" + NL + "        return 1.0f;"),
    ("wh-pilot-in-float", WC,
     "    return (float)((double)gPilotFactor" + NL
     + "                   + (1.0 - (double)gPilotFactor) * (double)t);",
     "    return gPilotFactor + (1.0f - gPilotFactor) * t;"),
    ("wh-pilot-no-low-clamp", WC,
     "    else if (t < 0.0f)" + NL + "        t = 0.0f;",
     "    else if (0)" + NL + "        t = 0.0f;"),
    ("wh-pilot-reverse-inclusive", WC,
     "    if (w->State.w < 0.0f)" + NL + "        return 1.0f;",
     "    if (w->State.w <= 0.0f)" + NL + "        return 1.0f;"),

    # -- the slip angle -----------------------------------------------------
    ("wh-slip-angle-no-transpose", WC,
     "    bTransposeMatrix(&t, &w->WorldMatrix);",
     "    t = w->WorldMatrix;"),
    ("wh-slip-angle-keeps-w", WC,
     "    t.v0.w = 0.0f;" + NL + "    t.v1.w = 0.0f;" + NL + "    t.v2.w = 0.0f;",
     "    (void)0;"),
    ("wh-slip-angle-atan-swapped", WC,
     "    angle = (float)bATan(localVel->x, localVel->y) * WHEEL_BAM_TO_RAD;",
     "    angle = (float)bATan(localVel->y, localVel->x) * WHEEL_BAM_TO_RAD;"),
    ("wh-slip-angle-single-fold", WC,
     "    if (localVel->x < 0.0f) {" + NL + "        angle += WHEEL_IMAGE_PI;",
     "    if (0) {" + NL + "        angle += WHEEL_IMAGE_PI;"),
    ("wh-slip-angle-second-fold-gone", WC,
     "        angle += WHEEL_IMAGE_PI;" + NL
     + "        if (WHEEL_IMAGE_PI < angle)" + NL
     + "            angle -= WHEEL_IMAGE_TWO_PI;",
     "        angle += WHEEL_IMAGE_PI;"),

    # -- GetLateralForce ----------------------------------------------------
    ("wh-lateral-index-not-halved", WC,
     "        float index = ((slipAngle * WHEEL_RAD_TO_DEG) * scale) * 0.5f;",
     "        float index = (slipAngle * WHEEL_RAD_TO_DEG) * scale;"),
    ("wh-lateral-scale-is-six", WC,
     "        float scale = 12.0f / ti->MaxSlipAngle;",
     "        float scale = 6.0f / ti->MaxSlipAngle;"),
    # The port had this, and so did the model above it, until
    # physicscar_check ran the shipped GetLateralForce.
    ("wh-lateral-scale-is-eleven", WC,
     "        float scale = 12.0f / ti->MaxSlipAngle;",
     "        float scale = 11.0f / ti->MaxSlipAngle;"),
    ("wh-lateral-load-not-scaled", WC,
     "        float load  = (zforce * gLoadFactor) / ti->MaxLoad;",
     "        float load  = zforce / ti->MaxLoad;"),
    ("wh-lateral-index-ceiling", WC,
     "        if (i < 6) {",
     "        if (i < 5) {"),
    ("wh-lateral-interpolation-reversed", WC,
     "            float v = a + frac * (b - a);",
     "            float v = b + frac * (a - b);"),
    ("wh-lateral-old-uses-zforce-arg", WC,
     "        return (gCorneringScale * f) * (w->ZForce * gZForceScale);",
     "        return (gCorneringScale * f) * (zforce * gZForceScale);"),
    ("wh-lateral-truncates-up", WC,
     "        int32_t i   = (int32_t)index;          // cvt.w.s, toward zero",
     "        int32_t i   = (int32_t)(index + 0.5f);"),

    # -- GuessGroundForce ---------------------------------------------------
    ("wh-guess-brake-sign", WC,
     "    if (0.0f < w->State.w)" + NL + "        brakeTorque = -brakeTorque;",
     "    if (w->State.w < 0.0f)" + NL + "        brakeTorque = -brakeTorque;"),
    ("wh-guess-brake-applies-when-locked", WC,
     "    if (w->BrakeLocked == 0)" + NL
     + "        w->AppliedTorque += brakeTorque;",
     "    w->AppliedTorque += brakeTorque;"),
    ("wh-guess-ebrake-always-positive", WC,
     "    if (0.0f < w->State.w)" + NL + "        ebrakeTorque = -ebrakeTorque;"
     + NL + "    else" + NL + "        ebrakeTorque = +ebrakeTorque;",
     "    ebrakeTorque = +ebrakeTorque;"),
    ("wh-guess-slip-sign", WC,
     "    slip = w->State.w * w->WI->Radius - vx;",
     "    slip = vx - w->State.w * w->WI->Radius;"),
    ("wh-guess-oldslip-not-set", WC,
     "    w->CurrentSlip = slip;" + NL + "    w->OldSlip = slip;",
     "    w->CurrentSlip = slip;"),
    ("wh-guess-reverse-damp-no-ebrake-test", WC,
     "        if (w->AppliedTorque < 0.0f && ebrakeMagnitude == 0.0f)",
     "        if (w->AppliedTorque < 0.0f)"),
    ("wh-guess-reverse-damp-torque-sign", WC,
     "    if (slip < -gMaxStaticSlip) {",
     "    if (gMaxStaticSlip < slip) {"),
    ("wh-guess-mag-uses-vx", WC,
     "    mag = sqrtf(slip * slip + vy * vy);",
     "    mag = sqrtf(slip * slip + vx * vx);"),
    ("wh-guess-zero-mag-not-caught", WC,
     "    if (mag == 0.0f)" + NL + "        goto resolve;",
     "    if (0)" + NL + "        goto resolve;"),
    ("wh-guess-still-car-not-caught", WC,
     "    if (vy == 0.0f && vx == 0.0f)" + NL + "        goto resolve;",
     "    if (0)" + NL + "        goto resolve;"),
    ("wh-guess-pilot-not-applied", WC,
     "        if (((const CarState *)w->CS)->DriverMode == 1)" + NL
     + "            dynamic = dynamic * wheel_get_pilot_factor(w);",
     "        if (0)" + NL
     + "            dynamic = dynamic * wheel_get_pilot_factor(w);"),
    ("wh-guess-perspeed-uses-mag", WC,
     "    perSpeed = maxForce / sqrtf(vx * vx + vy * vy);",
     "    perSpeed = maxForce / mag;"),
    ("wh-guess-brakelock-unsigned-vx", WC,
     "    wheel_check_for_brake_lock(w, fabsf(vx) * perSpeed);",
     "    wheel_check_for_brake_lock(w, vx * perSpeed);"),
    ("wh-guess-slip-trigger-inclusive", WC,
     "    if (gMaxStaticSlip < fabsf(slip))",
     "    if (gMaxStaticSlip <= fabsf(slip))"),
    ("wh-guess-angle-trigger-gone", WC,
     "    else if (w->TI->MaxSlipAngle < fabsf(angle))" + NL
     + "        slipping = 1;",
     "    else if (0)" + NL + "        slipping = 1;"),
    ("wh-guess-locked-trigger-gone", WC,
     "    else if (w->BrakeLocked != 0)" + NL + "        slipping = 1;",
     "    else if (0)" + NL + "        slipping = 1;"),
    ("wh-guess-slide-lateral-sign", WC,
     "        float fy = -perMag * vy;",
     "        float fy = perMag * vy;"),
    ("wh-guess-lowspeed-divide-gone", WC,
     "            w->GroundForce[1] = fy / dynamic;" + NL
     + "            w->GroundForce[0] = fx / dynamic;",
     "            w->GroundForce[1] = fy;" + NL
     + "            w->GroundForce[0] = fx;"),
    ("wh-guess-lowspeed-no-friction-gate", WC,
     "            && 0.100000001f < dynamic) {",
     "            && 1) {"),
    ("wh-guess-grip-longitudinal", WC,
     "        w->GroundForce[0] = w->AppliedTorque / w->WI->Radius;",
     "        w->GroundForce[0] = w->AppliedTorque * w->WI->Radius;"),
    ("wh-guess-grip-sign-default", WC,
     "        float sign = -1.0f;" + NL + NL + "        w->Slipping = 0;",
     "        float sign = 1.0f;" + NL + NL + "        w->Slipping = 0;"),
    ("wh-guess-grip-angle-sign", WC,
     "        if (0.0f < angle)" + NL + "            lateral = -lateral;",
     "        if (angle < 0.0f)" + NL + "            lateral = -lateral;"),
    ("wh-guess-grip-slip-not-cleared", WC,
     "        w->Slip[1] = 0.0f;" + NL + "        w->Slip[0] = 0.0f;",
     "        (void)0;"),

    # -- ModifyGroundForce --------------------------------------------------
    ("wh-modify-uses-world", WC,
     "    m.v0 = w->CarMatrix.v0;" + NL + "    m.v1 = w->CarMatrix.v1;" + NL
     + "    m.v2 = w->CarMatrix.v2;",
     "    m.v0 = w->WorldMatrix.v0;" + NL + "    m.v1 = w->WorldMatrix.v1;"
     + NL + "    m.v2 = w->WorldMatrix.v2;"),
    ("wh-modify-keeps-translation", WC,
     "    m.v3.x = 0.0f;" + NL + "    m.v3.y = 0.0f;" + NL
     + "    m.v3.z = 0.0f;" + NL + "    m.v3.w = 1.0f;" + NL + NL
     + "    in.x = v->x;",
     "    m.v3 = w->CarMatrix.v3;" + NL + NL + "    in.x = v->x;"),
    ("wh-modify-delta-sign", WC,
     "    delta = delta - out.x;",
     "    delta = delta + out.x;"),
    ("wh-modify-no-radius-divide", WC,
     "    delta = delta / w->WI->Radius;",
     "    delta = delta;"),
    ("wh-modify-in-z-nonzero", WC,
     "    in.x = v->x;" + NL + "    in.y = v->y;" + NL + "    in.z = 0.0f;",
     "    in.x = v->x;" + NL + "    in.y = v->y;" + NL + "    in.z = 1.0f;"),

    # -- FinalizeGroundForce ------------------------------------------------
    ("wh-final-ellipse-when-locked", WC,
     "    if (0.0f < w->AppliedTorque && w->BrakeLocked == 0) {",
     "    if (0.0f < w->AppliedTorque) {"),
    ("wh-final-ellipse-not-undone", WC,
     "    } else if (ellipsed) {" + NL
     + "        w->GroundForce[0] = w->GroundForce[0] / gTireForceEllipseRatio;",
     "    } else if (0) {" + NL
     + "        w->GroundForce[0] = w->GroundForce[0] / gTireForceEllipseRatio;"),
    ("wh-final-ellipse-always-undone", WC,
     "    } else if (ellipsed) {",
     "    }" + NL + "    if (ellipsed) {"),
    ("wh-final-clamp-no-epsilon", WC,
     "    if (maxForce < mag && WHEEL_EPSILON < mag) {",
     "    if (maxForce < mag) {"),
    ("wh-final-maxforce-no-boost", WC,
     "                   * (w->ZForce * w->TractionBoost);",
     "                   * w->ZForce;"),
    ("wh-final-maxforce-no-pilot", WC,
     "        if (((const CarState *)w->CS)->DriverMode == 1)" + NL
     + "            maxForce = maxForce * wheel_get_pilot_factor(w);",
     "        if (0)" + NL
     + "            maxForce = maxForce * wheel_get_pilot_factor(w);"),
    ("wh-final-usage-not-clamped", WC,
     "        if (1.0f < u)" + NL + "            w->TractionUsage = 1.0f;",
     "        if (0)" + NL + "            w->TractionUsage = 1.0f;"),
    ("wh-final-usage-tiny-force-is-zero", WC,
     "    } else {" + NL + "        w->TractionUsage = 1.0f;" + NL + "    }"
     + NL + NL + "    // A wheel that is sliding",
     "    } else {" + NL + "        w->TractionUsage = 0.0f;" + NL + "    }"
     + NL + NL + "    // A wheel that is sliding"),
    ("wh-final-usage-slipping-not-full", WC,
     "    if (!(w->Slipping == 0 && w->BrakeLocked == 0))" + NL
     + "        w->TractionUsage = 1.0f;",
     "    if (0)" + NL + "        w->TractionUsage = 1.0f;"),
    ("wh-final-usage-airborne-not-zero", WC,
     "    if (w->TouchingGround == 0)" + NL + "        w->TractionUsage = 0.0f;",
     "    if (0)" + NL + "        w->TractionUsage = 0.0f;"),
    ("wh-final-usage-order-swapped", WC,
     "    if (!(w->Slipping == 0 && w->BrakeLocked == 0))" + NL
     + "        w->TractionUsage = 1.0f;" + NL
     + "    if (w->TouchingGround == 0)" + NL + "        w->TractionUsage = 0.0f;",
     "    if (w->TouchingGround == 0)" + NL + "        w->TractionUsage = 0.0f;"
     + NL + "    if (!(w->Slipping == 0 && w->BrakeLocked == 0))" + NL
     + "        w->TractionUsage = 1.0f;"),
    ("wh-final-bleed-threshold", WC,
     "    if (1.0f < fabsf(localVel.x))",
     "    if (0.0f < fabsf(localVel.x))"),
    ("wh-final-bleed-uses-cos", WC,
     "        w->GroundForce[0] = w->GroundForce[0] - lateralSin * 0.5f;",
     "        w->GroundForce[0] = w->GroundForce[0] - lateralCos * 0.5f;"),
    ("wh-final-bleed-sign", WC,
     "        w->GroundForce[0] = w->GroundForce[0] - lateralSin * 0.5f;",
     "        w->GroundForce[0] = w->GroundForce[0] + lateralSin * 0.5f;"),
    ("wh-final-frame-one-is-car", WC,
     "        frame.v0 = w->WorldMatrix.v0;" + NL
     + "        frame.v1 = w->WorldMatrix.v1;" + NL
     + "        frame.v2 = w->WorldMatrix.v2;",
     "        frame.v0 = w->CarMatrix.v0;" + NL
     + "        frame.v1 = w->CarMatrix.v1;" + NL
     + "        frame.v2 = w->CarMatrix.v2;"),
    ("wh-final-frame-two-sign", WC,
     "        frame.v0.x = w->ContactNormal.x * -d0 + w->WorldMatrix.v0.x;",
     "        frame.v0.x = w->ContactNormal.x * d0 + w->WorldMatrix.v0.x;"),
    ("wh-final-frame-three-no-normalize", WC,
     "        normalize3(&frame.v0);",
     "        (void)0;"),
    ("wh-final-frame-three-cross-order", WC,
     "        cross3(&frame.v1, &frame.v2, &frame.v0);",
     "        cross3(&frame.v1, &frame.v0, &frame.v2);"),
    ("wh-final-frame-four-clears-all-w", WC,
     "        frame.v0 = w->WorldMatrix.v0;" + NL
     + "        frame.v1 = w->WorldMatrix.v1;" + NL
     + "        frame.v2 = w->ContactNormal;" + NL
     + "        frame.v2.w = 0.0f;" + NL + "    }",
     "        frame.v0 = w->WorldMatrix.v0;" + NL
     + "        frame.v0.w = 0.0f;" + NL
     + "        frame.v1 = w->WorldMatrix.v1;" + NL
     + "        frame.v1.w = 0.0f;" + NL
     + "        frame.v2 = w->ContactNormal;" + NL
     + "        frame.v2.w = 0.0f;" + NL + "    }"),
    ("wh-final-force-z-is-zero", WC,
     "    force.z = w->ZForce;",
     "    force.z = 0.0f;"),
    ("wh-final-worldforce-w-zeroed", WC,
     "    w->WorldGroundForce.w = world.pad;",
     "    w->WorldGroundForce.w = 0.0f;"),

    # -- the horizontal forces and the accessors ---------------------------
    ("wh-horizontal-car-is-world", WC,
     "    return ground_force_in(&w->CarMatrix, w->GroundForce[0],",
     "    return ground_force_in(&w->WorldMatrix, w->GroundForce[0],"),
    ("wh-horizontal-keeps-translation", WC,
     "    m.v3.x = 0.0f;" + NL + "    m.v3.y = 0.0f;" + NL
     + "    m.v3.z = 0.0f;" + NL + "    m.v3.w = 1.0f;" + NL + NL
     + "    in.x = fx;",
     "    m.v3 = src->v3;" + NL + NL + "    in.x = fx;"),
    ("wh-smoke-has-a-body", WC,
     "void wheel_maybe_make_smoke(Wheel *w, float v)" + NL + "{" + NL
     + "    (void)w;",
     "void wheel_maybe_make_smoke(Wheel *w, float v)" + NL + "{" + NL
     + "    w->NumTimesSkidding++;" + NL + "    (void)w;"),
    # The first version of this one wrote `lo = hi = value;` -- three dead
    # stores to its own parameters, which no transcript could ever see. It
    # was standing in for "a port gave this empty function a body", so it
    # now writes the global a debug slider plausibly would, and the
    # accessors scenario re-dumps the tuning block right after the call.
    ("wh-slider-has-a-body", WC,
     "void SetSliderValue(int32_t which, float lo, float hi, float value)"
     + NL + "{" + NL + "    (void)which;",
     "void SetSliderValue(int32_t which, float lo, float hi, float value)"
     + NL + "{" + NL + "    gMaxStaticSlip = value;" + NL + "    (void)which;"),
    ("wh-mass-is-moment", WC,
     "float wheel_get_mass(const Wheel *w) { (void)w; return 1.0f; }",
     "float wheel_get_mass(const Wheel *w) { return w->MomentOfInertia; }"),
    ("wh-drive-wheel-not-inverted", WC,
     "    return (w->WI->WheelNumber < 2) ^ 1;",
     "    return w->WI->WheelNumber < 2;"),
    ("wh-road-noise-not-gated", WC,
     "    return w->TouchingGround != 0 ? w->RoadNoise : 0.0f;",
     "    return w->RoadNoise;"),
    ("wh-set-slip-currentslip-from-y", WC,
     "    w->CurrentSlip = v->x;",
     "    w->CurrentSlip = v->y;"),
    ("wh-modifiable-ignores-lock", WC,
     "    return w->BrakeLocked == 0;",
     "    return 1;"),
    ("wh-apply-torque-when-locked", WC,
     "    if (w->BrakeLocked == 0)" + NL
     + "        w->AppliedTorque = w->AppliedTorque + t;",
     "    w->AppliedTorque = w->AppliedTorque + t;"),
    ("wh-rest-position-is-contact", WC,
     "    return (const bVector3 *)w->WI;",
     "    return (const bVector3 *)&w->ContactPoint;"),
    ("wh-rotate-vector-not-transposed", WC,
     "    x = m->v0.x * v->x;" + NL + "    x = x + m->v1.x * v->y;" + NL
     + "    x = x + m->v2.x * v->z;",
     "    x = m->v0.x * v->x;" + NL + "    x = x + m->v0.y * v->y;" + NL
     + "    x = x + m->v0.z * v->z;"),
    ("wh-install-seams-swapped", WC,
     "    gWheelFindDrivingSurfaceFn = wheel_find_driving_surface;",
     "    gWheelFindDrivingSurfaceFn = NULL;"),

    # -- Table, because Wheel is the fourth caller of it --------------------
    ("wh-table-clamps-with-min", TC,
     "    if (arg < t->MinArg)" + NL + "        arg = t->MinArg;" + NL
     + "    else if (t->MaxArg < arg)",
     "    if (arg < t->MinArg)" + NL + "        arg = t->MinArg;" + NL
     + "    if (t->MaxArg < arg)"),
    ("wh-table-last-index-interpolates", TC,
     "    if (i == last)" + NL + "        return t->pTable[i];",
     "    if (0)" + NL + "        return t->pTable[i];"),

    # -- DoSnapshot ---------------------------------------------------------
    ("wh-snap-floats-swapped", WC,
     "    ReplaySnapshot_MoveFloat(s, &w->State.a);" + NL
     + "    ReplaySnapshot_MoveFloat(s, &w->State.w);",
     "    ReplaySnapshot_MoveFloat(s, &w->State.w);" + NL
     + "    ReplaySnapshot_MoveFloat(s, &w->State.a);"),
    ("wh-snap-lastsign-short", WC,
     "    ReplaySnapshot_MoveInt(s, &w->LastSign, 4);",
     "    ReplaySnapshot_MoveInt(s, &w->LastSign, 2);"),
    ("wh-snap-clears-taking-only", WC,
     "    if (s->TakingSnapshotFlag || s->RestoringSnapshotFlag) {",
     "    if (s->TakingSnapshotFlag) {"),
    ("wh-snap-boost-to-one", WC,
     "        w->TractionBoost = 0.0f;",
     "        w->TractionBoost = 1.0f;"),
    ("wh-snap-damage-kept", WC,
     "        w->Damage = 0.0f;" + NL,
     ""),
    ("wh-snap-section-name", WC,
     "    ReplaySnapshot_BeginNamedSection(s, \"Wheel\");",
     "    ReplaySnapshot_BeginNamedSection(s, \"wheel\");"),

    # -- the ones that cannot be seen --------------------------------------
    ("wh-guess-dynamic-init", WC,
     "    float dynamic = 1.0f, maxForce = 0.0f, perSpeed = 0.0f, perMag = 0.0f;",
     "    float dynamic = 0.0f, maxForce = 0.0f, perSpeed = 0.0f, perMag = 0.0f;"),
    ("wh-guess-ebrake-magnitude-signed", WC,
     "        if (w->AppliedTorque < 0.0f && ebrakeMagnitude == 0.0f)",
     "        if (w->AppliedTorque < 0.0f && ebrakeTorque == 0.0f)"),
    ("wh-terrain-probe-w-junk", WC,
     "    probe.w = 0.0f;",
     "    probe.w = 1.0f;"),
    ("wh-final-force-pad-nonzero", WC,
     "    force.pad = 0.0f;",
     "    force.pad = 1.0f;"),
]

# Ten that survive, and every one of them deserves its reason written
# down. An eleventh is discussed here because it looks like it belongs on
# the list and does not.
#
# `wh-guess-dynamic-init`: $f22 is loaded with 1.0 at 0x0019a7e4, before the
# two early-outs, and the port writes the same. Both early-outs leave the
# slipping flag clear, and the gripping arm never reads `dynamic`; the only
# two reads -- the friction-circle radius and the walking-pace divide -- are
# on the slipping arm, which is reachable only through the block that
# assigns it. So the initial value cannot be observed with any input, and
# 1.0 is written because the listing writes it, not because it matters.
#
# `wh-guess-ebrake-magnitude-signed`: the image tests $f22, the unsigned
# handbrake torque, against zero; the port keeps a separate unsigned copy
# for that test. Substituting the signed one is equivalent on every input,
# because the only difference between them is a negation and IEEE 754 makes
# -0.0f == 0.0f true. The two are kept apart in the source because the
# listing keeps them apart, not because a transcript could tell.
#
# `wh-terrain-probe-w-junk` and `wh-final-force-pad-nonzero`: both are the w
# lane of a stack vector the PS2 never initialises -- `lqc2 vf1,0(sp)` over
# a slot the function has not written, and the three-float store in front of
# bMulMatrixVector. The probe's w reaches only a `vmul.xyz`, and
# bMulMatrixVec3 overwrites the input's w with 1.0 before it reads it, so
# neither can affect anything. The port writes a defined zero rather than
# imitating uninitialised stack, and these two mutations are how that claim
# is checked rather than asserted.
#
# `wh-final-ellipse-always-undone`: turning the `else if` into a second `if`
# looks like it should change the clamped case, and it would -- if the clamp
# and the ellipse could both fire. They can: 26000 * 1.5 against a maxForce
# of about 4100 clamps, and the undo would then divide the clamped force by
# 1.5 as well. It is listed as caught, not equivalent; if it ever survives,
# the finalize sweep has lost the case that covers it.
#
# Six more were added after the first full mutation pass reported twelve
# unexplained survivors. Six of those twelve were coverage holes and are
# closed by new scenarios -- the pilot speed whose blend rounds differently,
# the negative-zero z, the two GuessGroundForce boundaries, the nearly
# parallel pair that amplifies the dot's association, and the slider's
# global re-dump. The other six are below, and none of them is a hole.
#
# `wh-cross3-w-zeroed` and `wh-normalize-skips-w`: cross3 has two callers
# and normalize3 one. In ExchangeZForces the two cross products feed a
# dot3, which reads xyz only, so `t.w` and `u.w` are never read at all. In
# force frame 3 both results have their w overwritten by an explicit
# `frame.vN.w = 0.0f` on the very next line. The w each one carries is
# therefore unobservable through every path that exists, and the port
# writes what the VU writes -- `vopmsub.xyz` leaves the destination's w,
# and `vaddq.x` after `vrsqrt` scales all four lanes -- rather than what
# could be checked.
#
# `wh-slip-angle-keeps-w`: the three clears are real instructions, at
# 0x0019a6f4/0x0019a6fc/0x0019a704, storing $f21 to sp+28, sp+44 and sp+60
# against a matrix based at sp+16 (`addiu s0,sp,16` at 0x0019a6d0) -- so
# v0.w, v1.w and v2.w, exactly as the port has them. What they cannot do is
# show: a matrix row's w reaches only the product's w, bMulMatrixVec3 puts
# that in `localVel.pad`, and neither caller reads pad. GuessGroundForce
# takes .x and .y, FinalizeGroundForce takes .x.
#
# `wh-terraininfo-no-pad`: `_pad0[2]` at offset 14 sits in front of a
# pointer, so deleting it changes nothing -- the ABI puts the same two
# bytes back as alignment and every following offset, and the size, come
# out where the assert says. An explicit alignment pad cannot be checked by
# removing it; what pins SkidTextureName at 16 is the offsetof in the
# assert, which other mutations do move.
#
# `wh-table-clamps-with-min`: turning the `else if` into a second `if` can
# only matter when the low clamp fires and the high test then fires too,
# which needs MaxArg < MinArg. Wheel builds eight tables, 0..0.223402172
# and seven of 0..10, so it never happens. A NaN argument fails both
# comparisons in either spelling and falls through unclamped the same way,
# which is the case the two separate branches are actually there for.
#
# `wh-table-last-index-interpolates`: at `i == last` the interpolation
# weight `frac - (float)i` is exactly zero -- checked for every argument in
# g_table_args that reaches it, on both table shapes -- so the mutant
# computes `pTable[last] + (pTable[last + 1] - pTable[last]) * 0.0` and
# gets `pTable[last]` back. The guard is not protecting the arithmetic, it
# is protecting the read: without it the load goes one element past the end
# of the array. The transcript cannot see that and a sanitiser build would.
# The guard stays because the image has it and because the read is real.
EQUIVALENT = [
    "wh-guess-dynamic-init",
    "wh-guess-ebrake-magnitude-signed",
    "wh-terrain-probe-w-junk",
    "wh-final-force-pad-nonzero",
    "wh-cross3-w-zeroed",
    "wh-normalize-skips-w",
    "wh-slip-angle-keeps-w",
    "wh-terraininfo-no-pad",
    "wh-table-clamps-with-min",
    "wh-table-last-index-interpolates",
]
EXPECT_MISSING = []


# The write, its OneDrive retry, and the journal that lets a killed pass be
# recovered from are all hostbuild's.
write_source = hostbuild.write_source


def mutate_pass():
    base = model()
    caught = 0
    survived = []
    equivalent = []
    missing = []

    for name, rel, before, after in MUTATIONS:
        path = ROOT / rel
        text = path.read_text(encoding="utf-8", newline="")
        crlf = "\r\n" in text
        probe = before.replace(NL, "\r\n") if crlf else before
        repl = after.replace(NL, "\r\n") if crlf else after
        if probe not in text:
            missing.append(name)
            print("  %-44s PATTERN NOT FOUND" % name)
            continue
        try:
            write_source(path, text.replace(probe, repl, 1))
            with tempfile.TemporaryDirectory() as tmp:
                try:
                    exe = hostbuild.build(tmp, SOURCES, name="wheel_test")
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
    unexpected = [m for m in missing if m not in EXPECT_MISSING]
    # A pattern that is not found is dropped from the denominator above, so
    # without this the tally line reads clean while a mutation never ran.
    if missing:
        print("%d PATTERN NOT FOUND -- the tally above is over %d of %d"
              % (len(missing), len(real), len(MUTATIONS)))
    print("%d mutations, %d caught, %d equivalent, %d unexplained"
          % (len(real), caught, len(equivalent), len(holes)))
    for name in stale:
        ran = any(m[0] == name for m in MUTATIONS)
        print("  listed as equivalent but %s: %s"
              % ("caught" if ran else "names no mutation", name))
    return 1 if (holes or unexpected or stale) else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mutate", action="store_true")
    ap.add_argument("--dump", metavar="PREFIX")
    args = ap.parse_args()

    if args.mutate:
        sys.exit(mutate_pass())

    lines = model()
    with tempfile.TemporaryDirectory() as tmp:
        exe = hostbuild.build(tmp, SOURCES, name="wheel_test")
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
