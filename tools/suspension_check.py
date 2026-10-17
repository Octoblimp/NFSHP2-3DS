"""Cross-check 3DS Files/source/suspension.c against a model of Suspension.

Suspension is the sixth slice of task 25, after CarState, Engine,
CarTypeInfo, CarDriver, Steering and RigidBody. One corner of the car: a
spring and a damper along the wheel's z axis, a sway bar tying it to the
corner opposite, and the bookkeeping that turns the result into a wheel
matrix and a force on the body.

This model is written from the disassembly at 0x0019bc58 and from the
`.mdebug` layout, not from the C. The ten tuning globals and the two
`.lit4` constants are read straight out of `PS2 Files/NFSHP2.ELF` rather
than copied from the header, so a typo in either place shows as a diff
instead of agreeing with itself.

Five things the transcript exists to pin down.

**The state does not integrate.** GetDerivative (0x0019c170) writes two
zeroes and returns. ComputeAuxiliaries recomputes z from the ground every
frame and differences it against the previous z for v, so the record keeps
the old z only long enough to subtract it. Every case therefore sets a
previous z.

**Neither bump-stop comparison is strict.** `BumpStop[0] < surface` takes
the compression branch and `surface < BumpStop[1]` the airborne one, so a
wheel sitting exactly on the droop stop falls through to the else and
still counts as touching the ground. Both boundaries are in the table, and
both are reachable exactly: 0.32 is within a factor of two of each stop,
so `stop - 0.32` is exact by Sterbenz and adding 0.32 back lands on the
stop to the bit.

**A penetration bigger than gMaxGroundPenetration is discarded, not
clamped.** It is a sanity check on the terrain query, and the excess goes
to zero rather than to the limit.

**Two globals ship at values that hide the code reading them.**
gGroundPenaltyForce is 0.0, so the penetration multiplies by nothing and
`bottomed` and `deep` come out with the same Force to the bit; and
gUglyTimestepHack is 1.0, so the velocity divide divides by one and the
epsilon guard never takes its false arm. Both are .sdata the debug menu
moved, so the transcript runs the same height again with each moved --
which is where the penetration arithmetic, the divide and the guard
actually get pinned.

**Three of the four vector expressions carry a junk w lane, and the port
keeps all of them.** Calibrate subtracts a whole quadword off the front of
WheelInfo, whose fourth float is Radius rather than a w, so RestPosition.w
is `Radius - CoG.w`. The point velocity's cross product is
`vopmula`/`vopmsub`, which writes xyz and leaves the destination's w, so
the add that follows carries `v.w + w.w`. bMulMatrixVec3 forces w to 1
going in and writes the product's w back out. The transcript prints w
everywhere for that reason.

Usage:

    python tools/suspension_check.py
    python tools/suspension_check.py --mutate
    python tools/suspension_check.py --dump out/suspension
"""
import argparse
import difflib
import os
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hostbuild
import bmath_check as BM
import bvector_check as BV
import rigidbody_check as RBC
import steering_check as ST

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

SOURCES = [
    "tools/src/suspension_test.c",
    "3DS Files/source/suspension.c",
    "3DS Files/source/vtable.c",
    "3DS Files/source/replay.c", "3DS Files/source/p32.c",
    "3DS Files/source/wheel.c",
    "3DS Files/source/steering.c",
    "3DS Files/source/rigidbody.c",
    "3DS Files/source/carstate.c",   # wheel.c's SetState(CarState *, ...)
    "3DS Files/source/emath.c",      # and the eMulMatrix it calls
    "3DS Files/source/bmatrix.c",
    "3DS Files/source/table.c",
    "3DS Files/source/bvector.c",
    "3DS Files/source/bmath.c",
    "3DS Files/source/bmathtab.c",
]

SH = "3DS Files/source/suspension.h"
SC = "3DS Files/source/suspension.c"
CTI = "3DS Files/source/cartypeinfo.h"   # SuspensionInfo and WheelInfo live here
WH = "3DS Files/source/wheel.h"

# The host this runs on, not the handheld. Every PS2 offset below is
# stated in PS2 terms and widened from here, the same way the header's
# assert does it.
PTR = 8
SLACK = PTR - 4

f32 = BV.f32
fmul, fadd, fsub, fdiv, fneg = BV.fmul, BV.fadd, BV.fsub, BV.fdiv, BV.fneg
bSinF = BM.bSinF
cross3 = RBC.cross3

ZERO = f32(0.0)


def fbits(x):
    return struct.unpack("<I", struct.pack("<f", f32(x)))[0]


def g9(x):
    return "%.9g" % x


def pad(s, n):
    return s + " " * (n - len(s)) if len(s) < n else s


OUT = []


def emit(s):
    OUT.append(s)


def pf(tag, x):
    emit("%s %s" % (tag, g9(x)))


def pv(tag, v):
    emit("%s %s %s %s %s" % (tag, g9(v[0]), g9(v[1]), g9(v[2]), g9(v[3])))


def pm(tag, m):
    flat = [c for row in m for c in row]
    for j in range(16):
        emit("%s[%2d] %s" % (tag, j, g9(flat[j])))


# --------------------------------------------------------- the image's data
#
# Read out of the ELF rather than copied from the header: .sdata for the
# tuning set, .lit4 for the two words ComputeAuxiliaries reaches for.

def elf_f(addr):
    return struct.unpack("<f", BM.ELF.read(addr, 4))[0]


def elf_i(addr):
    return struct.unpack("<i", BM.ELF.read(addr, 4))[0]


G_LOAD_FACTOR = elf_f(0x00323D60)
G_WHEEL_FORCE_FRAME = elf_i(0x00323D64)
G_TIRE_FORCE_ELLIPSE_RATIO = elf_f(0x00323D68)
G_NO_SLIP_CORRECTION_FACTOR = elf_f(0x00323D6C)
G_UGLY_TIMESTEP_HACK = elf_f(0x00323D70)
G_GROUND_PENALTY_IMPULSE = elf_f(0x00323D74)
G_GROUND_PENALTY_FORCE = elf_f(0x00323D78)
G_MAX_GROUND_PENETRATION = elf_f(0x00323D7C)
G_PROGRESSIVE_DAMPING_FACTOR = elf_f(0x00323D80)
G_NO_WHEELS = elf_i(0x00323D84)

# gp-29660 and gp-29656, which `lwc1 $f0,-29660(gp)` and `lwc1
# $f12,-29656(gp)` name. The second is the quarter turn that turns bSinF
# into a cosine, and reading it here rather than trusting the header is
# what caught the header calling it 1.5708f: the word is 0x3fc90fdc, the
# one-ulp-high pi/2 Steering loads out of the same pool, and a rounded
# 1.5708f would have been 0x3fc90ff9 -- 30 ulps away.
C_EPSILON = elf_f(0x00321814)
C_HALF_PI = elf_f(0x00321818)

SUSPENSION_VTABLE = 0x00298FB0
PHYSICSCOMPONENT_VTABLE = 0x00298728

# The two globals that hide their own callers. Asserted rather than
# commented, so a differently tuned image fails here loudly instead of
# quietly making the two sub-passes below pointless.
assert G_GROUND_PENALTY_FORCE == 0.0
assert G_UGLY_TIMESTEP_HACK == 1.0

# Mutable, because two sub-passes move them the way the debug menu would.
g_penalty_force = f32(G_GROUND_PENALTY_FORCE)
g_timestep = f32(G_UGLY_TIMESTEP_HACK)


# ------------------------------------------------------------------ helpers

def identity():
    return BV.bIdentity()


def mat_from_flat(flat):
    return [tuple(f32(x) for x in flat[i * 4:i * 4 + 4]) for i in range(4)]


def mulmatvec3(v, m):
    """bMulMatrixVec3: w forced to 1 going in, four lanes written out."""
    return BV.rowmul((v[0], v[1], v[2], f32(1.0)), m)


def mulmat(m1, m2):
    """The C bMulMatrix(&o, &m1, &m2), which is o = m2 * m1."""
    return BV.bMulMatrix(m1, m2)


def vadd4(a, b):
    return tuple(fadd(a[i], b[i]) for i in range(4))


def vsub4(a, b):
    return tuple(fsub(a[i], b[i]) for i in range(4))


# ------------------------------------------------------------- the fixtures
#
# The same values the harness sets by hand, restated here rather than
# shared: a fixture read from one place would make the two readings one
# reading.

class SI(object):
    def __init__(self):
        self.Progression = f32(0.35)
        self.Stiffness = f32(42000.0)
        self.Damping = [f32(2600.0), f32(4100.0)]   # [0] v > 0, [1] v <= 0
        self.SwayBarStiffness = f32(900.0)
        # -0.25 and not a rounder -0.22, because `on-droop` has to land
        # on the stop exactly and -0.22f cannot be reached -- see the
        # note over the table below.
        self.BumpStop = [f32(0.18), f32(-0.25)]     # compression, droop
        self.MaxRenderingCompression = f32(0.12)


class WI(object):
    def __init__(self):
        self.PositionX = f32(1.4)
        self.PositionY = f32(0.78)
        self.PositionZ = f32(-0.35)
        self.Radius = f32(0.32)
        self.Width = f32(0.21)
        self.WheelNumber = 1


class Wheel(object):
    def __init__(self, wi):
        self.WI = wi
        self.a = f32(0.75)
        self.w = f32(31.0)
        self.Damage = ZERO
        self.ContactPoint = (f32(1.5), f32(0.8), f32(-0.4), f32(0.25))
        self.ContactNormal = (f32(0.1), f32(-0.2), f32(0.96), f32(0.5))
        self.WorldGroundForce = (f32(120.0), f32(-45.0), f32(310.0), f32(7.0))
        self.Velocity = (ZERO,) * 4
        self.CarMatrix = identity()
        self.WorldMatrix = identity()


class Body(object):
    """Only the RigidBody fields Suspension reads, plus the four
    accumulators the two force paths reach. RigidBody has a checker of its
    own; this one needs its fields to be known, not to be derived."""

    def __init__(self, rotated):
        self.X = (f32(10.0), f32(-4.0), f32(2.5), f32(0.125))

        r = [list(row) for row in identity()]
        if rotated:
            # A yaw of about 0.3 rad, written out rather than composed.
            r[0][0] = f32(0.955336489)
            r[0][1] = f32(0.295520207)
            r[1][0] = f32(-0.295520207)
            r[1][1] = f32(0.955336489)
        self.R = [tuple(row) for row in r]

        m = [list(row) for row in identity()]
        m[0][0] = f32(0.8)
        m[1][1] = f32(0.9)
        m[2][2] = f32(1.1)
        m[3][0] = f32(10.0)
        m[3][1] = f32(-4.0)
        m[3][2] = f32(2.5)
        self.Matrix = [tuple(row) for row in m]

        self.Velocity = (f32(12.0), f32(0.5), f32(-0.25), f32(0.75))
        self.AngularVelocity = (f32(0.05), f32(-0.12), f32(0.9), f32(0.4))
        self.CenterOfGravity = (f32(0.05), ZERO, f32(0.18), f32(0.5))
        self.Mass = f32(1450.0)
        self.massinv = f32(1.0 / 1450.0)

        # rigidbody_check's names, because its ApplyForce and ApplyImpulse
        # are reused rather than re-modelled.
        self.FA = (ZERO,) * 4
        self.MA = (ZERO,) * 4
        self.P = (ZERO,) * 4
        self.L = (ZERO,) * 4


class Susp(object):
    """calloc's view of the record: every field zero until something
    writes it, which is what the harness allocates."""

    def __init__(self):
        self.SI = None
        self.pSwayBar = None
        self.z = ZERO
        self.v = ZERO
        self.Force = ZERO
        self.Position = (ZERO,) * 4
        self.Matrix = identity()
        self.TouchingGround = 0
        self.MagicForce = ZERO
        self.RestLoad = ZERO
        self.RestPosition = (ZERO,) * 4
        self.pWheel = None
        self.pBody = None
        self.pSteering = None
        self.WheelPosition = 0
        self.GroundForce = ZERO
        self.vtable = 0


# -------------------------------------------------------------- the methods

def susp_init(s, wheelpos, body, wheel, steering, si):
    """0x0019bc58. Nine stores, no arithmetic, and everything else left as
    the allocation found it."""
    s.WheelPosition = wheelpos
    s.pBody = body
    s.vtable = SUSPENSION_VTABLE
    s.pWheel = wheel
    s.pSteering = steering
    s.SI = si
    s.pSwayBar = None
    return s


def calibrate(s, load):
    """0x0019bd40. A quadword subtract off the front of WheelInfo, whose
    fourth float is Radius and not a w."""
    wi = s.pWheel.WI
    cog = s.pBody.CenterOfGravity
    s.RestLoad = f32(load)
    s.RestPosition = (fsub(wi.PositionX, cog[0]),
                      fsub(wi.PositionY, cog[1]),
                      fsub(wi.PositionZ, cog[2]),
                      fsub(wi.Radius, cog[3]))


def point_velocity(v, w, r):
    """0x0019c180. v + w x r, with the cross product's surviving w lane
    carried into the four-lane add."""
    return vadd4(v, cross3(w, r, w[3]))


def compute_aux(s, surface_return, seam=True):
    """0x0019bd78, 872 bytes and the whole of the object's arithmetic."""
    body = s.pBody
    wheel = s.pWheel
    si = s.SI

    # Where the wheel would sit with no travel: the rest position rotated
    # into the world and offset by the body.
    world = vadd4(mulmatvec3(s.RestPosition, body.R), body.X)

    surface = f32(surface_return) if seam else ZERO

    oldz = s.z
    surface = fadd(surface, wheel.WI.Radius)

    penetration = ZERO
    if si.BumpStop[0] < surface:
        # Past the stop: the height clamps and the excess is a
        # penetration, unless it is too big to believe.
        penetration = fsub(surface, si.BumpStop[0])
        s.z = si.BumpStop[0]
        s.TouchingGround = 1
        if G_MAX_GROUND_PENETRATION < penetration:
            penetration = ZERO
    elif surface < si.BumpStop[1]:
        s.z = si.BumpStop[1]
        s.TouchingGround = 0
    else:
        s.z = surface
        s.TouchingGround = 1

    if C_EPSILON < g_timestep:
        s.v = fdiv(fsub(s.z, oldz), g_timestep)

    # The wheel centre is the rest position lifted by the travel, and the
    # matrix is that as a pure translation.
    pos = list(s.RestPosition)
    pos[2] = fadd(pos[2], s.z)
    s.Position = tuple(pos)

    m = [list(row) for row in identity()]
    m[3] = list(s.Position)
    m[3][3] = f32(1.0)
    s.Matrix = [tuple(row) for row in m]

    if s.pSteering is not None:
        m = mulmat(s.Matrix, s.pSteering[s.WheelPosition])
    else:
        m = [tuple(row) for row in s.Matrix]

    # A damaged wheel wobbles about z, the damage as the amplitude and the
    # wheel's own rotation as the phase.
    if wheel.Damage != ZERO:
        angle = fmul(wheel.Damage, bSinF(wheel.a))
        c = bSinF(fadd(angle, C_HALF_PI))
        sn = bSinF(angle)
        spin = [list(row) for row in identity()]
        spin[0][0] = c
        spin[0][1] = sn
        spin[1][0] = fneg(sn)
        spin[1][1] = c
        m = mulmat(m, [tuple(row) for row in spin])

    wheel.CarMatrix = [tuple(row) for row in m]

    r = mulmatvec3(s.Position, body.R)
    wheel.Velocity = point_velocity(body.Velocity, body.AngularVelocity, r)

    m = mulmat(body.Matrix, m)
    wheel.WorldMatrix = [tuple(row) for row in m]

    if not s.TouchingGround:
        s.Force = ZERO
        return world

    z = s.z
    v = s.v

    # z * (max(z, 0) * Progression * Stiffness + Stiffness): the
    # progression only stiffens the spring in compression, but the whole
    # product is then scaled by a z that can be either sign.
    spring = fmul(fmul(z if z > ZERO else ZERO, si.Progression), si.Stiffness)
    spring = fadd(spring, si.Stiffness)
    spring = fmul(spring, z)

    damping = fmul(v, si.Damping[1] if v <= ZERO else si.Damping[0])

    f = fadd(fadd(s.RestLoad, spring), damping)
    f = fadd(f, fmul(si.SwayBarStiffness, fsub(z, s.pSwayBar.z)))
    f = fadd(f, fmul(penetration, g_penalty_force))

    s.Force = ZERO if f < ZERO else f
    return world


def exchange_stub(z):
    """The harness's stand-in for Wheel::ExchangeZForces: z * 0.75 - 1.5."""
    return fsub(fmul(z, f32(0.75)), f32(1.5))


def resolve_forces(s, extra, seam=True):
    """0x0019c0e0. The extra is skipped in the air; Force is passed either
    way."""
    z = s.Force
    if s.TouchingGround:
        z = fadd(z, f32(extra))
    s.GroundForce = exchange_stub(z) if seam else ZERO
    return z


def resolve_more_forces(s, nowheels):
    """0x0019c120. The offset is computed before the flag is tested, so
    gNoWheels skips the force and not the arithmetic."""
    if not s.TouchingGround:
        return
    at = vsub4(s.pWheel.ContactPoint, s.pBody.X)
    if nowheels:
        return
    RBC.apply_force(s.pBody, s.pWheel.WorldGroundForce, at)


def penalty_impulse(s, nowheels):
    """0x0019c1b8. Returns the magnitude applied -- and still returns it
    when gNoWheels has skipped the ApplyImpulse."""
    at = mulmatvec3(s.Position, s.pBody.R)
    pvel = point_velocity(s.pBody.Velocity, s.pBody.AngularVelocity, at)
    n = s.pWheel.ContactNormal

    # vmul.xyz then two vadd lanes into x -- a three-lane dot product, so
    # the w lanes the cross product left behind never reach it.
    d = fadd(fadd(fmul(pvel[0], n[0]), fmul(pvel[1], n[1])),
             fmul(pvel[2], n[2]))
    approach = fneg(d)
    if approach < ZERO:
        return ZERO

    j = fmul(fmul(approach, G_GROUND_PENALTY_IMPULSE), s.pBody.Mass)
    impulse = tuple(fmul(n[i], j) for i in range(4))
    if nowheels:
        return j
    RBC.apply_impulse(s.pBody, impulse, at)
    return j


# ----------------------------------------------------------- the accessors

def get_damping(s):
    return s.SI.Damping[1] if s.v <= ZERO else s.SI.Damping[0]


def hack_offset(s):
    mx = s.SI.MaxRenderingCompression
    return ZERO if s.z < mx else fsub(mx, s.z)


def bottomed(s):
    return 1 if s.z == s.SI.BumpStop[0] else 0


# ------------------------------------------------------------ the scribble
#
# `0xA5 ^ (i * 7)` down the whole record, so a field the constructor is
# supposed to leave alone is visible as itself.

def scribble_bytes(off, n):
    return bytes(((0xA5 ^ ((off + i) * 7)) & 0xFF) for i in range(n))


def scribble_u32(off):
    return struct.unpack("<I", scribble_bytes(off, 4))[0]


def scribble_i32(off):
    return struct.unpack("<i", scribble_bytes(off, 4))[0]


def scribble_f32(off):
    return struct.unpack("<f", scribble_bytes(off, 4))[0]


# ----------------------------------------------------------- the scenarios

# PS2 offset, and how many pointer-widenings precede it on a 64-bit host.
# The multiplier climbs 1, 2, 3 across the front, sits at 3 for the whole
# span from State to RestPosition, then climbs 4, 5, 6, 7 through the four
# pointers at the back.
SUSP_OFFSETS = [
    ("pNext", 0, 0), ("pPrev", 4, 0), ("_vtable", 8, 0),
    ("SI", 12, 1), ("pSwayBar", 16, 2),
    ("State", 20, 3), ("Force", 28, 3), ("Position", 32, 3),
    ("Matrix", 48, 3), ("TouchingGround", 112, 3), ("MagicForce", 116, 3),
    ("RestLoad", 120, 3), ("RestPosition", 128, 3),
    ("pWheel", 144, 4), ("pBody", 148, 5), ("pSteering", 152, 6),
    ("WheelPosition", 156, 7), ("GroundForce", 160, 7),
]

# Wheel is a layout claim only -- see the note at the top of wheel.h --
# and every offset here is one an instruction pins independently.
#
# The shift is NOT uniform, and the reason is worth writing down. The host
# inserts two alignment pads the PS2 does not need, in front of WI and in
# front of TheSkidMaker, and the PS2 has one the host does not: a quadword
# gap between GroundForce[2] and WorldGroundForce, which the header leaves
# implicit because nothing sits in it. So the multiplier is 5 from State
# through Velocity, drops to 4 across the three contact vectors where the
# PS2 pad has been handed back, and returns to 5 from Damage on.
WHEEL_OFFSETS = [
    ("WI", 12, 1), ("State", 28, 5), ("WorldMatrix", 112, 5),
    ("CarMatrix", 176, 5), ("Velocity", 240, 5), ("WorldGroundForce", 288, 5),
    ("ContactPoint", 304, 5), ("ContactNormal", 320, 5), ("Damage", 364, 5),
]

STATE_OFF = 20 + 3 * SLACK
TOUCHING_OFF = 112 + 3 * SLACK


def s_layout():
    emit("[layout]")
    emit("ptr %d" % PTR)
    emit("slack %d" % SLACK)
    size = (176 + 7 * SLACK + PTR - 1) // PTR * PTR
    emit("sizeof Suspension %d" % size)
    emit("sizeof expected %d" % size)
    emit("sizeof SuspensionState 8")
    emit("sizeof SuspensionInfo 32")
    emit("sizeof WheelInfo 32")
    emit("sizeof bVector4 16")
    emit("sizeof bMatrix4 64")

    for name, ps2, n in SUSP_OFFSETS:
        emit("off %s %d" % (pad("Suspension." + name, 24), ps2 + n * SLACK))
    emit("off %s 0" % pad("SuspensionState.z", 24))
    emit("off %s 4" % pad("SuspensionState.v", 24))

    # The extents, because offsets do not pin them: an array can be
    # shortened and padded behind without moving anything after it.
    emit("arr Damping 8")
    emit("arr BumpStop 8")
    emit("arr _pad0 4")
    emit("arr _pad1 12")

    # Five host-widened members in Wheel over a PS2 record of 400 -- WI,
    # TI, CI, CS and the one pointer inside TheSkidMaker -- plus the two
    # pads the host's own alignment adds, before WI and before
    # TheSkidMaker, then rounded up to the pointer.
    #
    # Terrain is NOT one of them. `.mdebug` gives Wheel::Terrain as
    # type#140 at offset=2688 bits=32, and SetTerrain takes `11TerrainType`
    # -- a 32-bit enum, four bytes on both toolchains. An earlier draft of
    # wheel.h had it as a bare `void *`, which cost a slack of its own and
    # a pad in front of it and pushed everything from Damage on by eight;
    # GetTerrain loads it with `lw` and GetDerivative multiplies it by 140
    # to index the terrain table, so it was never a pointer.
    #
    # The PS2's quadword gap before WorldGroundForce is NOT subtracted here,
    # which is the correction the ARM build forced: wheel.h writes that gap
    # out as _pad2 now, because this port's bVector4 is four-byte aligned
    # and would otherwise close it on the handheld, where the record has to
    # be 400 bytes exactly.
    wheel_bytes = 400 + 5 * SLACK + 2 * SLACK
    emit("sizeof Wheel %d" % ((wheel_bytes + PTR - 1) // PTR * PTR))
    for name, ps2, n in WHEEL_OFFSETS:
        emit("woff %s %d" % (pad(name, 20), ps2 + n * SLACK))
    emit("arr w_pad2 4")

    emit("vtable Suspension %08x" % SUSPENSION_VTABLE)
    emit("vtable PhysicsComponent %08x" % PHYSICSCOMPONENT_VTABLE)
    emit("state floats 2")

    emit("g LoadFactor %08x" % fbits(G_LOAD_FACTOR))
    emit("g WheelForceFrame %d" % G_WHEEL_FORCE_FRAME)
    emit("g TireForceEllipseRatio %08x" % fbits(G_TIRE_FORCE_ELLIPSE_RATIO))
    emit("g NoSlipCorrectionFactor %08x" % fbits(G_NO_SLIP_CORRECTION_FACTOR))
    emit("g UglyTimestepHack %08x" % fbits(G_UGLY_TIMESTEP_HACK))
    emit("g GroundPenaltyImpulse %08x" % fbits(G_GROUND_PENALTY_IMPULSE))
    emit("g GroundPenaltyForce %08x" % fbits(G_GROUND_PENALTY_FORCE))
    emit("g MaxGroundPenetration %08x" % fbits(G_MAX_GROUND_PENETRATION))
    emit("g ProgressiveDampingFactor %08x"
         % fbits(G_PROGRESSIVE_DAMPING_FACTOR))
    emit("g NoWheels %d" % G_NO_WHEELS)
    emit("const epsilon %08x" % fbits(C_EPSILON))
    emit("const halfpi  %08x" % fbits(C_HALF_PI))
    emit("true  halfpi  %08x" % fbits(1.57079632679489661923))


def s_init():
    emit("[init]")
    s = susp_init(Susp(), 2, Body(0), Wheel(WI()), None, SI())

    emit("vtable %08x" % s.vtable)
    emit("wheelpos %d" % s.WheelPosition)
    emit("swaybar_null %d" % (1 if s.pSwayBar is None else 0))
    # The four pointers the constructor stores; identity, so all 1.
    emit("body_match 1")
    emit("wheel_match 1")
    emit("steering_null 1")
    emit("si_match 1")
    # Untouched by the constructor, so still the scribble.
    emit("scribble touching %d" % scribble_i32(TOUCHING_OFF))
    emit("scribble links %08x %08x" % (scribble_u32(0), scribble_u32(4)))
    pf("scribble z", scribble_f32(STATE_OFF))
    emit("after fini vtable %08x" % PHYSICSCOMPONENT_VTABLE)


def s_calibrate():
    emit("[calibrate]")
    loads = [0.0, 3400.0, -125.5]
    si, wi = SI(), WI()
    w = Wheel(wi)
    for i in range(3):
        b = Body(1 if i == 2 else 0)
        s = susp_init(Susp(), 0, b, w, None, si)
        calibrate(s, loads[i])
        emit("case %d" % i)
        pf("  RestLoad", s.RestLoad)
        pv("  RestPosition", s.RestPosition)
        # The w lane is Radius minus the body's w, not a zero.
        pf("  wi_radius", wi.Radius)
        pf("  cog_w", b.CenterOfGravity[3])


def s_state():
    emit("[state]")
    inputs = [(0.0, 0.0), (0.125, -3.5), (-0.5, 12.25), (1e-7, 1e7)]
    s = Susp()
    s.SI = SI()
    emit("size 2")
    emit("state_ptr_offset %d" % STATE_OFF)
    for i, (z, v) in enumerate(inputs):
        s.z, s.v = f32(z), f32(v)
        emit("case %d" % i)
        pf("  z", s.z)
        pf("  v", s.v)
        # Only two floats move; the third is the guard.
        pf("  guard", f32(-999.0))
        pf("  dz", ZERO)
        pf("  dv", ZERO)
        pf("  dguard", f32(-999.0))
    pf("cleared z", ZERO)
    pf("cleared v", ZERO)


def s_accessors():
    emit("[accessors]")
    # Velocities either side of zero -- including a negative zero, which
    # the `v <= 0` test takes -- and heights around both the bump stop and
    # the rendering limit.
    vs = [-3.0, -0.0, 0.0, 1e-20, 7.5]
    zs = [-0.3, 0.0, 0.11, 0.12, 0.13, 0.18]
    si = SI()
    s = Susp()
    s.SI = si
    s.WheelPosition = 3

    pf("progression", si.Progression)
    pf("stiffness", si.Stiffness)
    pf("swaybar", si.SwayBarStiffness)
    emit("wheelpos 3")
    emit("rest_off %d" % (128 + 3 * SLACK))
    emit("matrix_off %d" % (48 + 3 * SLACK))

    for i, v in enumerate(vs):
        s.v = f32(v)
        emit("damping %d %s %s" % (i, g9(s.v), g9(get_damping(s))))

    for i, z in enumerate(zs):
        s.z = f32(z)
        emit("hack %d %s %s bottomed %d"
             % (i, g9(s.z), g9(hack_offset(s)), bottomed(s)))

    s.z, s.v = f32(0.055), f32(-1.25)
    pf("height", s.z)
    pf("velocity", s.v)
    s.MagicForce = f32(812.5)
    pf("magic", s.MagicForce)
    emit("swaybar_set 1")


def s_point_velocity():
    emit("[point-velocity]")
    V = [(1.0, 2.0, 3.0, 0.5), (0.0, 0.0, 0.0, 0.0),
         (-12.5, 3.25, 0.125, -2.0)]
    W = [(0.1, 0.2, 0.3, 9.0), (1.0, 0.0, 0.0, -1.0), (0.0, 0.0, 2.0, 0.25)]
    R = [(1.5, -0.5, 0.25, 100.0), (0.0, 1.0, 0.0, 50.0), (2.0, 2.0, 2.0, 0.0)]
    for i in range(3):
        v = tuple(f32(x) for x in V[i])
        w = tuple(f32(x) for x in W[i])
        r = tuple(f32(x) for x in R[i])
        emit("case %d" % i)
        pv("  out", point_velocity(v, w, r))


# What the driving-surface stand-in returns is the raw height --
# ComputeAuxiliaries adds WheelInfo::Radius (0.32) to it before either
# bump stop is consulted. The table below gives the height each case is
# aiming for, and surf() takes the radius back off it the way the harness
# writes `0.18f - R_`: in float32, not in Python's doubles, because the
# two differ in the last bit and the whole point of the two stop cases is
# that they land on the stop exactly.
#
# For the compression stop it works: 0.18 and 0.32 are within a factor
# of two and both positive, so the subtraction is exact by Sterbenz and
# adding the radius back returns 0.18f to the bit.
#
# For a *negative* stop it does not, and that is why the droop limit in
# the fixture is -0.25 rather than a rounder -0.22. The magnitudes add
# instead of cancelling, and at 0.57 the ulp is twice the ulp at 0.22, so
# the sum can only land on every other float near the stop. -0.22f is
# 0xbe6147ae, an odd mantissa, and no float the stand-in can return
# reaches it -- checked by walking the neighbourhood a bit at a time, not
# assumed. -0.25 is reachable, because 0.25 + 0.32f is exact.
#
# name, target height, oldz, rotated, steered, damage, restload, swayz
R_ = 0.32
AUX = [
    ("mid",              0.05, 0.01, 0, 0, 0.0,  3400.0,   0.03),
    ("bottomed",         0.25, 0.17, 0, 0, 0.0,  3400.0,   0.03),
    ("deep",             0.40, 0.17, 0, 0, 0.0,  3400.0,   0.03),
    ("airborne",        -0.50, 0.05, 0, 0, 0.0,  3400.0,   0.03),
    # A rest load big enough that the spring sum would come out positive
    # if the airborne branch fell through instead of returning. At 3400
    # it comes out near -7200 and floors back to the zero the branch has
    # already written, which hides the early return completely.
    ("airborne-loaded", -0.50, 0.05, 0, 0, 0.0, 50000.0,   0.03),
    ("on-bump",          0.18, 0.10, 0, 0, 0.0,  3400.0,   0.03),
    ("on-droop",        -0.25, 0.10, 0, 0, 0.0,  3400.0,   0.03),
    ("rotated",          0.05, 0.01, 1, 0, 0.0,  3400.0,   0.03),
    ("steered",          0.05, 0.01, 1, 1, 0.0,  3400.0,   0.03),
    ("damaged",          0.05, 0.01, 0, 0, 0.35, 3400.0,   0.03),
    ("damaged-rot",      0.05, 0.01, 1, 1, -0.9, 3400.0,   0.03),
    ("extending",        0.05, 0.09, 0, 0, 0.0,  3400.0,   0.03),
    # 8000 rather than 3400 for the same reason: at 3400 the floor takes
    # the total to zero and whether the progression was clamped away
    # stops being visible.
    ("negative-z",      -0.10, 0.01, 0, 0, 0.0,  8000.0,  -0.05),
    ("force-floor",      0.05, 0.01, 0, 0, 0.0, -90000.0,  4.0),
]


def surf(target):
    """`target - R_` as the harness spells it, in float32."""
    return fsub(f32(target), f32(R_))

STEER_GX = [1.40, 1.35, -1.30, -1.25]
STEER_GY = [0.78, -0.78, 0.80, -0.80]
STEER_BAM = 0x0A00


def steering_matrices():
    """What ackerman_set_steering(0x0a00) leaves in AckermanMatrix[0..1].
    Reused from the Steering model rather than re-derived."""
    gx = [f32(v) for v in STEER_GX]
    gy = [f32(v) for v in STEER_GY]
    m0, m1 = ST.set_steering(gx, gy, STEER_BAM)
    return [mat_from_flat(m0), mat_from_flat(m1)]


def make_aux(oldz, rotated, steered, damage, restload, swayz, preset_v=True):
    si, wi = SI(), WI()
    w, b = Wheel(wi), Body(rotated)
    w.Damage = f32(damage)
    s = susp_init(Susp(), 1, b, w,
                  steering_matrices() if steered else None, si)
    calibrate(s, restload)
    s.z = f32(oldz)
    if preset_v:
        s.v = f32(-123.0)      # overwritten by the difference
    sway = Susp()
    sway.z = f32(swayz)
    s.pSwayBar = sway
    return s, b, w


def s_compute_aux():
    global g_penalty_force, g_timestep
    emit("[compute-aux]")

    for (name, target, oldz, rotated, steered, damage, restload,
         swayz) in AUX:
        s, b, w = make_aux(oldz, rotated, steered, damage, restload, swayz)
        world = compute_aux(s, surf(target))
        emit("case %s" % name)
        emit("  surface_calls 1")
        pv("  surface_pos", world)
        pf("  surface_r0x", b.R[0][0])
        emit("  touching %d" % s.TouchingGround)
        pf("  z", s.z)
        pf("  v", s.v)
        pf("  Force", s.Force)
        pv("  Position", s.Position)
        pm("  Matrix", s.Matrix)
        pm("  CarMatrix", w.CarMatrix)
        pm("  WorldMatrix", w.WorldMatrix)
        pv("  WheelVelocity", w.Velocity)
        emit("  bottomed %d" % bottomed(s))
        pf("  hack", hack_offset(s))

    # The penetration term, with the global off its shipped zero.
    g_penalty_force = f32(800.0)
    for name, target in (("pen-none", 0.05), ("pen-small", 0.25),
                         ("pen-huge", 0.40)):
        s, b, w = make_aux(0.17, 0, 0, 0.0, 3400.0, 0.03, preset_v=False)
        compute_aux(s, surf(target))
        emit("case %s" % name)
        pf("  z", s.z)
        pf("  v", s.v)
        pf("  Force", s.Force)
    g_penalty_force = f32(G_GROUND_PENALTY_FORCE)

    # The divide and the epsilon guard, likewise. The third value is below
    # the epsilon, so v is left exactly as the scenario set it.
    for name, hack in (("hack-half", 0.5), ("hack-two", 2.0),
                       ("hack-tiny", 0.00005)):
        s, b, w = make_aux(0.01, 0, 0, 0.0, 3400.0, 0.03)
        g_timestep = f32(hack)
        compute_aux(s, surf(0.05))
        emit("case %s" % name)
        pf("  z", s.z)
        pf("  v", s.v)
        pf("  Force", s.Force)
    g_timestep = f32(G_UGLY_TIMESTEP_HACK)

    # And once with the seam left NULL, which is the state the handheld is
    # in until the Wheel slice lands.
    s = susp_init(Susp(), 1, Body(0), Wheel(WI()), None, SI())
    calibrate(s, 3400.0)
    s.pSwayBar = Susp()
    compute_aux(s, 0.0, seam=False)
    emit("case null-seam")
    emit("  touching %d" % s.TouchingGround)
    pf("  z", s.z)
    pf("  v", s.v)
    pf("  Force", s.Force)


def s_resolve():
    emit("[resolve-forces]")
    extras = [0.0, 250.0, -80.0]
    si, wi = SI(), WI()
    for touching in range(2):
        for i in range(3):
            s = susp_init(Susp(), 1, Body(0), Wheel(wi), None, si)
            s.Force = f32(5200.0)
            s.TouchingGround = touching
            passed = resolve_forces(s, extras[i])
            emit("case %d %d" % (touching, i))
            emit("  calls 1")
            emit("  passed_touching %d" % touching)
            pf("  passed_z", passed)
            pf("  GroundForce", s.GroundForce)

    s = susp_init(Susp(), 1, Body(0), Wheel(wi), None, si)
    s.Force = f32(5200.0)
    s.TouchingGround = 1
    resolve_forces(s, 10.0, seam=False)
    emit("case null-seam")
    pf("  GroundForce", s.GroundForce)


def s_resolve_more():
    emit("[resolve-more-forces]")
    si, wi = SI(), WI()
    for touching in range(2):
        for nowheels in range(2):
            b = Body(0)
            s = susp_init(Susp(), 1, b, Wheel(wi), None, si)
            s.TouchingGround = touching
            resolve_more_forces(s, nowheels)
            emit("case %d %d" % (touching, nowheels))
            pv("  ForceAccumulator", b.FA)
            pv("  MomentAccumulator", b.MA)


# The contact normal decides the sign of the approach, and the first
# draft of this scenario varied only the z lane -- with the body velocity
# what it is, every one of those normals came out approaching away from
# the surface, so all four cases took the early return and the whole body
# of the function went unexercised. Five mutations survived on that alone
# and nothing in the transcript showed the gap. The whole normal varies
# now.
#
# name, nx, ny, nz, rotated
PEN = [
    ("away",     0.1, -0.2,  0.96, 0),
    ("into",    -0.1,  0.2, -0.96, 0),
    ("flat",    -0.1,  0.2,  0.0,  0),
    # A zero normal: the three-lane dot is +0 and the approach is its
    # negation, -0. `-0 < 0` is false, so this falls through the guard
    # and applies a zero impulse, and the returned -0 is what tells a
    # `<=` apart from a `<`.
    ("grazing",  0.0,  0.0,  0.0,  0),
    ("rotated", -0.1,  0.2,  0.5,  1),
]


def s_penalty():
    emit("[penalty]")
    si, wi = SI(), WI()
    for name, nx, ny, nz, rotated in PEN:
        for nowheels in range(2):
            b, w = Body(rotated), Wheel(wi)
            s = susp_init(Susp(), 1, b, w, None, si)
            calibrate(s, 3400.0)
            pos = list(s.RestPosition)
            pos[2] = fadd(pos[2], f32(0.04))
            s.Position = tuple(pos)
            w.ContactNormal = (f32(nx), f32(ny), f32(nz), w.ContactNormal[3])
            j = penalty_impulse(s, nowheels)
            emit("case %s %d" % (name, nowheels))
            pf("  j", j)
            pv("  P", b.P)
            pv("  L", b.L)


SCENARIOS = [s_layout, s_init, s_calibrate, s_state, s_accessors,
             s_point_velocity, s_compute_aux, s_resolve, s_resolve_more,
             s_penalty]


def model():
    del OUT[:]
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
    ("su-state-swapped", SH,
     "    float z; // 0" + NL + "    float v; // 4",
     "    float v; // 0" + NL + "    float z; // 4"),
    ("su-force-before-state", SH,
     "    SuspensionState State;            //  20" + NL
     + "    float     Force;                  //  28",
     "    float     Force;                  //  20" + NL
     + "    SuspensionState State;            //  24"),
    ("su-pad0-gone", SH,
     "    uint8_t   _pad0[4];               // 124  RestPosition is 16-aligned",
     "    uint8_t   _pad0[1];               // 124"),
    ("su-pad1-short", SH,
     "    uint8_t   _pad1[12];              // 164  tail padding to 176",
     "    uint8_t   _pad1[8];               // 164"),
    # The gap wheel.h writes out by hand because this port's bVector4 is
    # four-byte aligned where the PS2's was sixteen. Shortening it moves
    # every vector behind it, and on the handheld it also takes the record
    # under 400 -- which is how the ARM build found it missing entirely.
    ("su-wheel-pad2-short", WH,
     "    uint8_t   _pad2[4];                  // 284  WorldGroundForce is",
     "    uint8_t   _pad2[1];                  // 284  WorldGroundForce is"),
    ("su-bumpstop-single", CTI,
     "    float BumpStop[2];             // 20",
     "    float BumpStop[1];             // 20" + NL + "    float _bspad;"),
    ("su-damping-single", CTI,
     "    float Damping[2];              //  8",
     "    float Damping[1];              //  8" + NL + "    float _dpad;"),
    ("su-restload-magic-swapped", SH,
     "    float     MagicForce;             // 116" + NL
     + "    float     RestLoad;               // 120",
     "    float     RestLoad;               // 116" + NL
     + "    float     MagicForce;             // 120"),
    ("su-getsize-1", SH,
     "#define SUSPENSION_STATE_FLOATS 2",
     "#define SUSPENSION_STATE_FLOATS 1"),
    ("su-vtable-off-by-16", SH,
     "#define SUSPENSION_VTABLE 0x00298fb0u",
     "#define SUSPENSION_VTABLE 0x00298fa0u"),

    # -- the two constants --------------------------------------------------
    # The bug this slice actually had: 1.5708f is thirty ulps off the
    # word the image loads, and it stood in the header until the model
    # read gp-29656 out of the ELF instead of trusting it.
    ("su-halfpi-rounded", SH,
     "#define SUSPENSION_IMAGE_HALF_PI    1.57079649f  // 0x3fc90fdc",
     "#define SUSPENSION_IMAGE_HALF_PI    1.5708f"),
    ("su-halfpi-exact", SH,
     "#define SUSPENSION_IMAGE_HALF_PI    1.57079649f  // 0x3fc90fdc",
     "#define SUSPENSION_IMAGE_HALF_PI    1.57079637f"),
    ("su-epsilon-one", SH,
     "#define SUSPENSION_TIMESTEP_EPSILON 0.0001f",
     "#define SUSPENSION_TIMESTEP_EPSILON 1.0f"),

    # -- the tuning set -----------------------------------------------------
    ("su-maxpen-quarter", SC,
     "float   gMaxGroundPenetration     = 0.15f;",
     "float   gMaxGroundPenetration     = 0.25f;"),
    ("su-penalty-impulse-half", SC,
     "float   gGroundPenaltyImpulse     = 0.2f;",
     "float   gGroundPenaltyImpulse     = 0.5f;"),
    ("su-timestep-ships-half", SC,
     "float   gUglyTimestepHack         = 1.0f;",
     "float   gUglyTimestepHack         = 0.5f;"),
    ("su-penalty-force-ships-set", SC,
     "float   gGroundPenaltyForce       = 0.0f;",
     "float   gGroundPenaltyForce       = 1.0f;"),

    # -- the lifetime -------------------------------------------------------
    ("su-init-keeps-swaybar", SC,
     "    s->pSwayBar = NULL;" + NL + "    return s;",
     "    return s;"),
    ("su-fini-keeps-vtable", SC,
     "    s->_vtable = PHYSICSCOMPONENT_VTABLE;",
     "    s->_vtable = SUSPENSION_VTABLE;"),
    ("su-calibrate-w-zeroed", SC,
     "    s->RestPosition.w = wi->Radius - cog->w;",
     "    s->RestPosition.w = 0.0f;"),
    ("su-calibrate-z-from-y", SC,
     "    s->RestPosition.z = wi->PositionZ - cog->z;",
     "    s->RestPosition.z = wi->PositionY - cog->z;"),

    # -- the height ---------------------------------------------------------
    ("su-no-radius", SC,
     "    surface += wheel->WI->Radius;",
     "    surface += 0.0f;"),
    ("su-radius-subtracted", SC,
     "    surface += wheel->WI->Radius;",
     "    surface -= wheel->WI->Radius;"),
    ("su-bumpstop-inclusive", SC,
     "    if (si->BumpStop[0] < surface) {",
     "    if (si->BumpStop[0] <= surface) {"),
    ("su-droop-inclusive", SC,
     "    } else if (surface < si->BumpStop[1]) {",
     "    } else if (surface <= si->BumpStop[1]) {"),
    ("su-droop-touches-ground", SC,
     "        s->State.z = si->BumpStop[1];" + NL
     + "        s->TouchingGround = 0;",
     "        s->State.z = si->BumpStop[1];" + NL
     + "        s->TouchingGround = 1;"),
    ("su-penetration-clamped", SC,
     "        if (gMaxGroundPenetration < penetration)" + NL
     + "            penetration = 0.0f;",
     "        if (gMaxGroundPenetration < penetration)" + NL
     + "            penetration = gMaxGroundPenetration;"),
    ("su-penetration-from-droop", SC,
     "        penetration = surface - si->BumpStop[0];",
     "        penetration = surface - si->BumpStop[1];"),
    ("su-velocity-not-divided", SC,
     "        s->State.v = (s->State.z - oldZ) / gUglyTimestepHack;",
     "        s->State.v = (s->State.z - oldZ);"),
    ("su-velocity-backwards", SC,
     "        s->State.v = (s->State.z - oldZ) / gUglyTimestepHack;",
     "        s->State.v = (oldZ - s->State.z) / gUglyTimestepHack;"),
    ("su-oldz-read-late", SC,
     "    oldZ = s->State.z;" + NL + "    surface += wheel->WI->Radius;",
     "    surface += wheel->WI->Radius;" + NL + "    oldZ = 0.0f;"),

    # -- the matrices -------------------------------------------------------
    ("su-position-z-assigned", SC,
     "    s->Position.z += s->State.z;",
     "    s->Position.z = s->State.z;"),
    ("su-matrix-w-left-alone", SC,
     "    s->Matrix.v3 = s->Position;" + NL + "    s->Matrix.v3.w = 1.0f;",
     "    s->Matrix.v3 = s->Position;"),
    ("su-steer-order-reversed", SC,
     "        bMulMatrix(&m, &s->Matrix," + NL
     + "                   &s->pSteering->SteeringMatrix[s->WheelPosition]);",
     "        bMulMatrix(&m," + NL
     + "                   &s->pSteering->SteeringMatrix[s->WheelPosition],"
     + NL + "                   &s->Matrix);"),
    ("su-steer-index-zero", SC,
     "                   &s->pSteering->SteeringMatrix[s->WheelPosition]);",
     "                   &s->pSteering->SteeringMatrix[0]);"),
    ("su-world-order-reversed", SC,
     "    bMulMatrix(&m, &body->Matrix, &m);",
     "    bMulMatrix(&m, &m, &body->Matrix);"),
    ("su-carmatrix-taken-late", SC,
     "    wheel->CarMatrix = m;" + NL,
     ""),
    ("su-damage-phase-is-spin", SC,
     "        float angle = wheel->Damage * bSinF(wheel->State.a);",
     "        float angle = wheel->Damage * bSinF(wheel->State.w);"),
    ("su-damage-cosine-is-sine", SC,
     "        float c = bSinF(angle + SUSPENSION_IMAGE_HALF_PI);",
     "        float c = bSinF(angle);"),
    ("su-spin-sign-flipped", SC,
     "        spin.v0.y = sn;" + NL + "        spin.v1.x = -sn;",
     "        spin.v0.y = -sn;" + NL + "        spin.v1.x = sn;"),
    ("su-damage-always-runs", SC,
     "    if (wheel->Damage != 0.0f) {",
     "    if (1) {"),
    ("su-pointvel-from-restposition", SC,
     "    bMulMatrixVec3((bVector3 *)&r, &body->State.R," + NL
     + "                   (const bVector3 *)&s->Position);",
     "    bMulMatrixVec3((bVector3 *)&r, &body->State.R," + NL
     + "                   (const bVector3 *)&s->RestPosition);"),

    # -- the point velocity -------------------------------------------------
    ("su-crossw-zeroed", SC,
     "    c.w = w->w;",
     "    c.w = 0.0f;"),
    ("su-cross-operands-swapped", SC,
     "    c.x = w->y * r->z - w->z * r->y;" + NL
     + "    c.y = w->z * r->x - w->x * r->z;" + NL
     + "    c.z = w->x * r->y - w->y * r->x;",
     "    c.x = r->y * w->z - r->z * w->y;" + NL
     + "    c.y = r->z * w->x - r->x * w->z;" + NL
     + "    c.z = r->x * w->y - r->y * w->x;"),

    # -- the force ----------------------------------------------------------
    ("su-airborne-still-springs", SC,
     "        s->Force = 0.0f;" + NL + "        return;",
     "        s->Force = 0.0f;"),
    ("su-progression-unclamped", SC,
     "        spring = max_s(z, 0.0f) * si->Progression * si->Stiffness;",
     "        spring = z * si->Progression * si->Stiffness;"),
    ("su-spring-not-scaled", SC,
     "        spring *= z;",
     "        spring *= 1.0f;"),
    ("su-damping-swapped", SC,
     "        damping = v * (v <= 0.0f ? si->Damping[1] : si->Damping[0]);",
     "        damping = v * (v <= 0.0f ? si->Damping[0] : si->Damping[1]);"),
    ("su-swaybar-sign", SC,
     "        f += si->SwayBarStiffness * (z - s->pSwayBar->State.z);",
     "        f += si->SwayBarStiffness * (s->pSwayBar->State.z - z);"),
    ("su-swaybar-reads-own-z", SC,
     "        f += si->SwayBarStiffness * (z - s->pSwayBar->State.z);",
     "        f += si->SwayBarStiffness * (z - s->State.z);"),
    ("su-penetration-not-added", SC,
     "        f += penetration * gGroundPenaltyForce;",
     "        f += 0.0f;"),
    ("su-force-floor-gone", SC,
     "        s->Force = f < 0.0f ? 0.0f : f;",
     "        s->Force = f;"),

    # -- the force paths ----------------------------------------------------
    ("su-resolve-always-adds", SC,
     "    if (s->TouchingGround)" + NL + "        z += extra;",
     "    z += extra;"),
    ("su-resolve-never-adds", SC,
     "    if (s->TouchingGround)" + NL + "        z += extra;",
     "    if (0)" + NL + "        z += extra;"),
    ("su-more-forces-runs-airborne", SC,
     "    if (!s->TouchingGround)" + NL + "        return;",
     "    if (0)" + NL + "        return;"),
    ("su-more-forces-at-is-contact", SC,
     "    at.x = s->pWheel->ContactPoint.x - s->pBody->State.X.x;",
     "    at.x = s->pWheel->ContactPoint.x;"),
    ("su-penalty-approach-unsigned", SC,
     "    approach = -(pv.x * n.x + pv.y * n.y + pv.z * n.z);",
     "    approach = (pv.x * n.x + pv.y * n.y + pv.z * n.z);"),
    ("su-penalty-dot-is-four-lane", SC,
     "    approach = -(pv.x * n.x + pv.y * n.y + pv.z * n.z);",
     "    approach = -(pv.x * n.x + pv.y * n.y + pv.z * n.z + pv.w * n.w);"),
    ("su-penalty-approach-inclusive", SC,
     "    if (approach < 0.0f)" + NL + "        return 0.0f;",
     "    if (approach <= 0.0f)" + NL + "        return 0.0f;"),
    ("su-penalty-no-mass", SC,
     "    j = approach * gGroundPenaltyImpulse * s->pBody->Mass;",
     "    j = approach * gGroundPenaltyImpulse;"),
    ("su-penalty-nowheels-returns-zero", SC,
     "    if (gNoWheels)" + NL + "        return j;",
     "    if (gNoWheels)" + NL + "        return 0.0f;"),
    ("su-penalty-impulse-w-zeroed", SC,
     "    impulse.w = n.w * j;",
     "    impulse.w = 0.0f;"),

    # -- the accessors ------------------------------------------------------
    ("su-get-damping-strict", SC,
     "    return s->State.v <= 0.0f ? s->SI->Damping[1] : s->SI->Damping[0];",
     "    return s->State.v < 0.0f ? s->SI->Damping[1] : s->SI->Damping[0];"),
    ("su-hack-sign", SC,
     "    return max - s->State.z;",
     "    return s->State.z - max;"),
    ("su-hack-returns-max", SC,
     "    if (s->State.z < max)" + NL + "        return 0.0f;",
     "    if (s->State.z < max)" + NL + "        return max;"),
    ("su-bottomed-on-droop", SC,
     "    return s->State.z == s->SI->BumpStop[0] ? 1 : 0;",
     "    return s->State.z == s->SI->BumpStop[1] ? 1 : 0;"),
    ("su-height-is-velocity", SC,
     "float suspension_get_height(const Suspension *s)" + NL + "{" + NL
     + "    return s->State.z;",
     "float suspension_get_height(const Suspension *s)" + NL + "{" + NL
     + "    return s->State.v;"),

    # -- the one that cannot be seen ---------------------------------------
    ("su-more-forces-flag-first", SC,
     "    at.x = s->pWheel->ContactPoint.x - s->pBody->State.X.x;",
     "    if (gNoWheels)" + NL + "        return;" + NL
     + "    at.x = s->pWheel->ContactPoint.x - s->pBody->State.X.x;"),
]

# Two that survive, and both deserve their reasons written down.
#
# `su-more-forces-flag-first`: `at` is a local the gNoWheels path drops on
# the floor, so moving the flag test in front of the subtraction changes
# nothing any transcript can see. The image computes the vector first and
# the port follows, but that is a claim about the listing rather than
# about behaviour.
#
# `su-bumpstop-inclusive`: making the *compression* test non-strict is
# equivalent on every input, not merely on the ones here. At
# `surface == BumpStop[0]` the strict path falls to the else and writes
# `z = surface`; the non-strict one writes `z = BumpStop[0]`, which is the
# same number. Both set TouchingGround, and the penetration the extra
# branch computes is `surface - BumpStop[0]`, which is zero -- the same
# value the variable was initialised to. The clamp is idempotent at its
# own boundary, so there is nothing to see.
#
# Note the contrast with the droop test one line down, where the same
# change is caught on sight: there the two arms disagree about
# TouchingGround, and a wheel exactly on the droop stop is on the ground
# under one reading and in the air under the other.
EQUIVALENT = ["su-more-forces-flag-first", "su-bumpstop-inclusive"]
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
            print("  %-36s PATTERN NOT FOUND" % name)
            continue
        try:
            write_source(path, text.replace(probe, repl, 1))
            with tempfile.TemporaryDirectory() as tmp:
                try:
                    exe = hostbuild.build(tmp, SOURCES, name="suspension_test")
                except SystemExit:
                    print("  %-36s did not compile (caught)" % name)
                    caught += 1
                    continue
                out = Path(tmp) / "m.txt"
                if run_harness(exe, out) != 0:
                    print("  %-36s crashed the harness (caught)" % name)
                    caught += 1
                    continue
                n = diff(base, out.read_text().splitlines(), quiet=True)
                if n:
                    print("  %-36s caught, %d lines" % (name, n))
                    caught += 1
                elif name in EQUIVALENT:
                    print("  %-36s survived, equivalent by construction" % name)
                    equivalent.append(name)
                else:
                    print("  %-36s SURVIVED" % name)
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
        exe = hostbuild.build(tmp, SOURCES, name="suspension_test")
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
