"""Cross-check 3DS Files/source/carstate.c against a model of CarState.obj.

CarState.obj (0x001b6170..0x001b6f60) is the car's state record and the
sixteen functions that maintain it: where the car is, how fast, which way it
points, what each wheel is doing, and the cached car-to-world basis that
everything reading the car goes through. It is the seam the rest of the car
systems meet at, which is why it is the first piece of task 25.

This model is written from the disassembly and from the .mdebug layout, not
from the C. The float layer is imported from bvector_check, the sin/cos/atan
layer from bmath_check and the matrix layer from emath_check -- each itself
a model of its own object written from the ELF -- so the chain of custody
for every number here runs back to an address rather than to another port.

Unlike trackroute_check, this model is a record of named fields rather than
a byte image. The reason is that CarState is not loaded by casting: nothing
on the disc is a CarState, the game builds them at runtime, so a field at
the wrong offset is a compile-time question rather than a decode one. It is
answered by the static assert in carstate.h -- which carries the host's
wider pointers as a term so that it still checks the layout on the machine
this script runs on -- and the transcript here is about behaviour instead.

Everything is float32. The EE has no double.

    python tools/carstate_check.py
    python tools/carstate_check.py --mutate     # break the C and re-diff
    python tools/carstate_check.py --dump out/carstate
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
from bvector_check import f32, fadd, fmul, fneg, fsub
import bmath_check
import emath_check

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

SOURCES = [
    "tools/src/carstate_test.c",
    "3DS Files/source/carstate.c",
    "3DS Files/source/replay.c", "3DS Files/source/p32.c",
    "3DS Files/source/bvector.c",
    "3DS Files/source/bmath.c",
    "3DS Files/source/bmathtab.c",
    "3DS Files/source/bmatrix.c",
    "3DS Files/source/emath.c",
]

CS = "3DS Files/source/carstate.c"


def g9(x):
    return "%.9g" % x


def bits(w):
    return struct.unpack("<f", struct.pack("<I", w))[0]


def bitsof(x):
    return struct.unpack("<I", struct.pack("<f", f32(x)))[0]


# ------------------------------------------------------------- the constants
#
# 0x003219e8 .. 0x003219f4, read out of the image. The two scales are
# bit-identical to bMath's; the pi pair is not, and that is the point -- see
# the note in carstate.c. C_PI here is 0x40490fd0 where bmath_check.C_PI is
# 0x40490fdb.

BAM_TO_RAD = bits(0x38c90fdb)
C_PI       = bits(0x40490fd0)
C_2PI      = bits(0x40c90fd0)
RAD_TO_BAM = bits(0x4622f983)

assert BAM_TO_RAD == bmath_check.C_BAM_TO_RAD
assert RAD_TO_BAM == bmath_check.C_RAD_TO_BAM
assert C_PI != bmath_check.C_PI
assert C_2PI != bmath_check.C_2PI

YAW_MIN_SPEED = f32(5.0)   # 0x40a00000


# ----------------------------------------------------------------- matrices
#
# Flat sixteen floats, row-major, the same shape emath_check uses.

def mat_identity():
    return emath_check.mat_identity()


def mat_zero():
    return [f32(0.0)] * 16


def b_transpose(m):
    """bTransposeMatrix, 0x00242808."""
    o = mat_zero()
    for r in range(4):
        for c in range(4):
            o[r * 4 + c] = m[c * 4 + r]
    return o


def b_mul_vec3(m, v):
    """bMulMatrixVec3, 0x002427b0. w is forced to 1, so the translation row
    applies, and the w of the product is written back to the pad."""
    o = [f32(0.0)] * 4
    vv = (v[0], v[1], v[2], f32(1.0))
    for c in range(4):
        acc = fmul(vv[0], m[0 + c])
        acc = fadd(acc, fmul(vv[1], m[4 + c]))
        acc = fadd(acc, fmul(vv[2], m[8 + c]))
        acc = fadd(acc, fmul(vv[3], m[12 + c]))
        o[c] = acc
    return o


def e_mul_vec3(m, v):
    """eMulVector3, 0x0011bb68 -- a tail call into bMulMatrixVec3."""
    return b_mul_vec3(m, v)


# --------------------------------------------------------------- the record


class State(object):
    """CarState, by name. The pads and the two holes are carried because the
    transcript prints them: which slots a function leaves alone is part of
    what it does."""

    __slots__ = (
        "pCarInfo", "hole8", "tail",
        "GeometryPosition", "Position", "Velocity", "Acceleration",
        "BodyMatrix", "AngularVelocity", "AngularAcceleration",
        "WheelMatrix", "BrakeMatrix",
        "WheelAngularVelocity", "WheelAngle", "WheelZForce",
        "WheelRoadNoise", "WheelBottomOutMagnitude",
        "WheelSuspensionHeight", "WheelTouchingGround", "WheelTerrain",
        "CrossedWheelTerrain", "WheelSlip", "WheelTractionUsage",
        "Angle", "SteeringAngle", "Odometer", "TractionUsage",
        "SkidLeft", "SkidRight", "nWheelsTouchingGround", "ForwardSpeed",
        "VelocityMagnitude", "CurrentGear", "Throttle", "RPM",
        "RedLineSyncRPM", "ClutchEngaged", "DriverMode", "BoostFactor",
        "BurnOutState", "BurnOutTime", "BurnOutTraction", "BurnOutAllow",
        "RelCoordMatrix", "MatrixValid",
    )

    def __init__(self):
        self.pCarInfo = None
        self.hole8 = [0] * 8
        self.tail = [0] * 12
        for n in ("GeometryPosition", "Position", "Velocity", "Acceleration",
                  "AngularVelocity", "AngularAcceleration"):
            setattr(self, n, [f32(0.0)] * 4)
        self.BodyMatrix = mat_zero()
        self.RelCoordMatrix = mat_zero()
        self.WheelMatrix = [mat_zero() for _ in range(4)]
        self.BrakeMatrix = [mat_zero() for _ in range(4)]
        for n in ("WheelAngularVelocity", "WheelAngle", "WheelZForce",
                  "WheelRoadNoise", "WheelBottomOutMagnitude",
                  "WheelSuspensionHeight", "WheelTractionUsage"):
            setattr(self, n, [f32(0.0)] * 4)
        self.WheelTouchingGround = [0] * 4
        self.WheelTerrain = [0] * 4
        self.CrossedWheelTerrain = [0] * 4
        self.WheelSlip = [[f32(0.0), f32(0.0)] for _ in range(4)]
        self.Angle = 0
        self.SteeringAngle = 0
        for n in ("Odometer", "TractionUsage", "SkidLeft", "SkidRight",
                  "ForwardSpeed", "VelocityMagnitude", "Throttle", "RPM",
                  "RedLineSyncRPM", "BoostFactor", "BurnOutTime",
                  "BurnOutTraction", "BurnOutAllow"):
            setattr(self, n, f32(0.0))
        for n in ("nWheelsTouchingGround", "CurrentGear", "ClutchEngaged",
                  "DriverMode", "BurnOutState", "MatrixValid"):
            setattr(self, n, 0)


class Info(object):
    """The CarTypeInfo prefix CarState reads: CenterOfGravity at 272 and the
    four 32-byte WheelInfos at 288."""

    def __init__(self):
        self.CenterOfGravity = [f32(0.0)] * 4
        self.Wheels = [dict(x=f32(0.0), y=f32(0.0), z=f32(0.0),
                            r=f32(0.0)) for _ in range(4)]


# ---------------------------------------------------------- the object


def init(s, info):
    """0x001b6170. Two pointers, four scalars, then ResetCar. The three
    empty countdown loops the listing opens with are an inlined do-nothing
    constructor and have no effect. Retail's (0x001c01a8) zeroes one more
    float after Odometer, which the port keeps as the tail's first four
    bytes: DistanceMoved."""
    s.Odometer = f32(0.0)
    s.tail[0:4] = [0, 0, 0, 0]
    s.Position[0] = s.Position[1] = s.Position[2] = f32(0.0)
    s.GeometryPosition[0] = s.GeometryPosition[1] = f32(0.0)
    s.GeometryPosition[2] = f32(0.0)
    s.DriverMode = 0
    s.pCarInfo = info
    reset_car(s)


def reset_car(s):
    """0x001b6570."""
    for n in ("Velocity", "Acceleration", "AngularVelocity",
              "AngularAcceleration"):
        v = getattr(s, n)
        v[0] = v[1] = v[2] = f32(0.0)

    s.BodyMatrix = mat_identity()

    s.Angle = 0
    s.SteeringAngle = 0

    for i in range(4):
        s.WheelAngularVelocity[i]    = f32(0.0)
        s.WheelAngle[i]              = f32(0.0)
        s.WheelZForce[i]             = f32(0.0)
        s.WheelRoadNoise[i]          = f32(0.0)
        s.WheelBottomOutMagnitude[i] = f32(0.0)
        s.WheelSuspensionHeight[i]   = f32(0.0)
        s.WheelTractionUsage[i]      = f32(0.0)
        s.WheelTouchingGround[i]     = 1
        s.WheelTerrain[i]            = 1
        s.CrossedWheelTerrain[i]     = 1
        s.WheelSlip[i][0]            = f32(0.0)
        s.WheelSlip[i][1]            = f32(0.0)

    s.nWheelsTouchingGround = 4

    calculate_wheel_matrices(s)

    s.TractionUsage     = f32(0.0)
    s.SkidLeft          = f32(0.0)
    s.SkidRight         = f32(0.0)
    s.ForwardSpeed      = f32(0.0)
    s.VelocityMagnitude = f32(0.0)
    s.Throttle          = f32(0.0)
    s.BurnOutState      = 0
    s.BurnOutTime       = f32(0.0)

    s.RPM             = f32(1000.0)
    s.RedLineSyncRPM  = f32(-1.0)
    s.ClutchEngaged   = 1
    s.BurnOutTraction = f32(1.0)
    s.CurrentGear     = 1
    s.BoostFactor     = f32(1.0)

    s.RelCoordMatrix = mat_zero()
    s.MatrixValid    = 0


def reset_car_for_sound(s):
    """0x001b6718. ResetCar's wheel loop with WheelRoadNoise left out, plus
    RPM, and none of the body, matrix or drivetrain work."""
    s.RPM = f32(1000.0)

    for i in range(4):
        s.WheelAngularVelocity[i]    = f32(0.0)
        s.WheelAngle[i]              = f32(0.0)
        s.WheelZForce[i]             = f32(0.0)
        s.WheelBottomOutMagnitude[i] = f32(0.0)
        s.WheelSuspensionHeight[i]   = f32(0.0)
        s.WheelTractionUsage[i]      = f32(0.0)
        s.WheelTouchingGround[i]     = 1
        s.WheelTerrain[i]            = 1
        s.CrossedWheelTerrain[i]     = 1
        s.WheelSlip[i][0]            = f32(0.0)
        s.WheelSlip[i][1]            = f32(0.0)

    s.SkidRight             = f32(0.0)
    s.nWheelsTouchingGround = 4
    s.VelocityMagnitude     = f32(0.0)
    s.TractionUsage         = f32(0.0)
    s.SkidLeft              = f32(0.0)


def begin_timestep(s):
    """0x001b67e8. Counts down from wheel 3."""
    for i in (3, 2, 1, 0):
        s.CrossedWheelTerrain[i] = 1


def get_yaw(s):
    """0x001b6820."""
    if s.ForwardSpeed < YAW_MIN_SPEED:
        return f32(0.0)
    return get_yaw_always(s)


def get_yaw_always(s):
    """0x001b6868. bATan(Velocity.x, Velocity.y) is a BAM; the subtraction
    and the mask are BAM arithmetic, and only then does it become radians.
    The fold is one-sided."""
    heading = bmath_check.bATan(s.Velocity[0], s.Velocity[1])
    delta = (s.Angle - heading) & 0xffff
    rad = fmul(f32(float(delta)), BAM_TO_RAD)
    if C_PI < rad:
        rad = fsub(rad, C_2PI)
    return rad


def get_transform_matrix(s):
    """0x001b68d0. Above a squared speed of 1 the basis comes from the
    direction of travel, below it from Angle. Either way it is
    orthonormalized and cached behind MatrixValid."""
    if s.MatrixValid:
        return s.RelCoordMatrix

    v = [s.Velocity[0], s.Velocity[1], s.Velocity[2], s.Velocity[3]]

    if s.ForwardSpeed < f32(0.0):
        # vsub.xyzw against VU0's constant register (0,0,0,1): a subtraction
        # from zero, NOT a negation -- so a zero component comes out +0.0
        # where neg.s would give -0.0.
        v = [fsub(f32(0.0), v[0]), fsub(f32(0.0), v[1]),
             fsub(f32(0.0), v[2]), fsub(f32(1.0), v[3])]

    m = mat_identity()

    # vmul.xyz then vaddy.x then vaddz.x: ((x*x + y*y) + z*z), in that order.
    lensq = fadd(fadd(fmul(v[0], v[0]), fmul(v[1], v[1])), fmul(v[2], v[2]))

    if f32(1.0) < lensq:
        m[0], m[1], m[2], m[3] = v[1], fneg(v[0]), f32(0.0), f32(0.0)
        m[4], m[5], m[6], m[7] = v[0], v[1], f32(0.0), f32(0.0)
    else:
        c = bmath_check.bCosBam(s.Angle)
        n = bmath_check.bSinBam(s.Angle)
        m[0], m[1], m[2], m[3] = n, fneg(c), f32(0.0), f32(0.0)
        m[4], m[5], m[6], m[7] = c, n, f32(0.0), f32(0.0)

    m[8], m[9], m[10], m[11] = f32(0.0), f32(0.0), f32(1.0), f32(0.0)
    m[12], m[13], m[14], m[15] = f32(0.0), f32(0.0), f32(0.0), f32(1.0)

    s.RelCoordMatrix = emath_check.eorthonormalize(m)
    s.MatrixValid = 1
    return s.RelCoordMatrix


def world_to_car2(s, q):
    """0x001b6ab0."""
    t = b_transpose(get_transform_matrix(s))
    d = [fsub(q[0], s.Position[0]), fsub(q[1], s.Position[1]), f32(0.0)]
    r = e_mul_vec3(t, d)
    return [r[0], r[1]]


def world_to_car3(s, q):
    """0x001b6b40. The difference is a whole-quadword subtract, so the pad
    takes part; the result is stored as a quadword too, so the pad that
    comes back is the w of the multiply."""
    t = b_transpose(get_transform_matrix(s))
    d = [fsub(q[0], s.Position[0]), fsub(q[1], s.Position[1]),
         fsub(q[2], s.Position[2]), fsub(q[3], s.Position[3])]
    return e_mul_vec3(t, d)


def car_to_world_unadjusted(s, q):
    """0x001b6bb0."""
    m = get_transform_matrix(s)
    r = e_mul_vec3(m, [q[0], q[1], f32(0.0)])
    return [r[0], r[1]]


def car_to_world(s, q):
    """0x001b6c18."""
    t = car_to_world_unadjusted(s, q)
    return [fadd(t[0], s.Position[0]), fadd(t[1], s.Position[1])]


def set_wheel_touching_ground(s, wheel, on):
    """0x001b6c90. The store happens in the branch's delay slot, so it is
    unconditional; only the count is conditional, and only on a change
    between zero and non-zero."""
    was = s.WheelTouchingGround[wheel]
    s.WheelTouchingGround[wheel] = on
    if was == 0:
        if on != 0:
            s.nWheelsTouchingGround += 1
    else:
        if on == 0:
            s.nWheelsTouchingGround -= 1


def set_wheel_terrain(s, wheel, t):
    """0x001b6ce0. A signed compare, so a terrain below the current crossed
    value leaves it alone."""
    s.WheelTerrain[wheel] = t
    if s.CrossedWheelTerrain[wheel] < t:
        s.CrossedWheelTerrain[wheel] = t


def calculate_wheel_matrices_one(s, wheel):
    """0x001b6d10. The wheel matrix gets spin, steering and the suspension
    lift; the brake matrix gets steering only, at the unlifted hub. Wheels 0
    and 1 steer."""
    wm = emath_check.mat_identity()
    bm = emath_check.mat_identity()

    # cvt.w.s truncates toward zero, then andi takes the low sixteen bits --
    # the same conversion bSinF uses.
    spin = int(f32(fmul(s.WheelAngle[wheel], RAD_TO_BAM))) & 0xffff

    wm = emath_check.erotate_y(wm, spin)

    if wheel < 2:
        wm = emath_check.erotate_z(wm, s.SteeringAngle)
        bm = emath_check.erotate_z(bm, s.SteeringAngle)

    wi = s.pCarInfo.Wheels[wheel]

    bm[12], bm[13], bm[14], bm[15] = wi["x"], wi["y"], wi["z"], f32(1.0)

    wm[12] = wi["x"]
    wm[13] = wi["y"]
    wm[14] = fadd(wi["z"], s.WheelSuspensionHeight[wheel])
    wm[15] = f32(1.0)

    s.WheelMatrix[wheel] = wm
    s.BrakeMatrix[wheel] = bm


def calculate_wheel_matrices(s):
    """0x001b6e58."""
    for i in range(4):
        calculate_wheel_matrices_one(s, i)


def calculate_geometry_position(s):
    """0x001b6ea8. GeometryPosition = Position - (CenterOfGravity *
    BodyMatrix), as a whole-quadword subtract."""
    cog = b_mul_vec3(s.BodyMatrix, s.pCarInfo.CenterOfGravity)
    return [fsub(s.Position[i], cog[i]) for i in range(4)]


# ---------------------------------------------------------------- the dirt
#
# The harness dirties every field before each scenario, by name rather than
# with a byte pattern, because the host's pointers are eight bytes where the
# PS2's are four. These reproduce that exactly.


class Dirt(object):
    def __init__(self):
        self.n = 0

    def f(self):
        self.n += 1
        return f32(-1000.0 - float(self.n))

    def i(self):
        self.n += 1
        return -900 - self.n


def fill_pattern(s):
    d = Dirt()

    s.hole8 = [0xA0 + i for i in range(8)]
    s.tail = [0xD0 + i for i in range(12)]
    s.pCarInfo = None

    for n in ("GeometryPosition", "Position", "Velocity", "Acceleration",
              "AngularVelocity", "AngularAcceleration"):
        setattr(s, n, [d.f() for _ in range(4)])

    s.BodyMatrix = [d.f() for _ in range(16)]
    s.WheelMatrix = [[d.f() for _ in range(16)] for _ in range(4)]
    s.BrakeMatrix = [[d.f() for _ in range(16)] for _ in range(4)]
    s.RelCoordMatrix = [d.f() for _ in range(16)]

    for i in range(4):
        s.WheelAngularVelocity[i]    = d.f()
        s.WheelAngle[i]              = d.f()
        s.WheelZForce[i]             = d.f()
        s.WheelRoadNoise[i]          = d.f()
        s.WheelBottomOutMagnitude[i] = d.f()
        s.WheelSuspensionHeight[i]   = d.f()
        s.WheelTractionUsage[i]      = d.f()
        s.WheelSlip[i][0]            = d.f()
        s.WheelSlip[i][1]            = d.f()
        # int8_t, and 0x50+i is positive so no sign fold is needed.
        s.WheelTouchingGround[i]     = 0x50 + i
        s.WheelTerrain[i]            = d.i()
        s.CrossedWheelTerrain[i]     = d.i()

    s.Angle = 0xBEE1
    s.SteeringAngle = 0xBEE2

    for n in ("Odometer", "TractionUsage", "SkidLeft", "SkidRight",
              "ForwardSpeed", "VelocityMagnitude", "Throttle", "RPM",
              "RedLineSyncRPM", "BoostFactor", "BurnOutTime",
              "BurnOutTraction", "BurnOutAllow"):
        setattr(s, n, d.f())

    for n in ("nWheelsTouchingGround", "CurrentGear", "ClutchEngaged",
              "DriverMode", "BurnOutState", "MatrixValid"):
        setattr(s, n, d.i())


def make_info():
    info = Info()
    px = [f32(1.25), f32(-1.25), f32(1.5), f32(-1.5)]
    py = [f32(2.75), f32(2.75), f32(-2.25), f32(-2.25)]
    pz = [f32(0.375), f32(0.4375), f32(0.5), f32(0.5625)]
    rad = [f32(0.3), f32(0.31), f32(0.32), f32(0.33)]

    info.CenterOfGravity = [f32(0.125), f32(-0.0625), f32(0.75), f32(0.0)]
    for i in range(4):
        info.Wheels[i] = dict(x=px[i], y=py[i], z=pz[i], r=rad[i])
    return info


# ---------------------------------------------------------------- printing

OUT = []


def emit(s):
    OUT.append(s)


def pvec3(tag, v):
    emit("  %-10s %s %s %s pad %08x" % (tag, g9(v[0]), g9(v[1]), g9(v[2]),
                                        bitsof(v[3])))


def pmat(tag, m):
    emit("  %s" % tag)
    for r in range(4):
        emit("    %s %s %s %s" % (g9(m[r * 4 + 0]), g9(m[r * 4 + 1]),
                                  g9(m[r * 4 + 2]), g9(m[r * 4 + 3])))


def pstate(tag, s):
    emit(tag)
    emit("  hole8      " + " ".join("%02x" % b for b in s.hole8))

    pvec3("geompos", s.GeometryPosition)
    pvec3("position", s.Position)
    pvec3("velocity", s.Velocity)
    pvec3("accel", s.Acceleration)
    pmat("bodymatrix", s.BodyMatrix)
    pvec3("angvel", s.AngularVelocity)
    pvec3("angaccel", s.AngularAcceleration)

    for i in range(4):
        pmat("wheelmatrix%d" % i, s.WheelMatrix[i])
    for i in range(4):
        pmat("brakematrix%d" % i, s.BrakeMatrix[i])

    emit("  wangvel    " + " ".join(g9(x) for x in s.WheelAngularVelocity))
    emit("  wangle     " + " ".join(g9(x) for x in s.WheelAngle))
    emit("  wzforce    " + " ".join(g9(x) for x in s.WheelZForce))
    emit("  wroadnoise " + " ".join(g9(x) for x in s.WheelRoadNoise))
    emit("  wbottomout " + " ".join(g9(x) for x in s.WheelBottomOutMagnitude))
    emit("  wsusp      " + " ".join(g9(x) for x in s.WheelSuspensionHeight))
    emit("  wtouch     " + " ".join("%d" % x for x in s.WheelTouchingGround))
    emit("  wterrain   " + " ".join("%d" % x for x in s.WheelTerrain))
    emit("  wcrossed   " + " ".join("%d" % x for x in s.CrossedWheelTerrain))
    emit("  wslip      " + " ".join("(%s %s)" % (g9(w[0]), g9(w[1]))
                                    for w in s.WheelSlip))
    emit("  wtraction  " + " ".join(g9(x) for x in s.WheelTractionUsage))

    emit("  angle %u steer %u odo %s traction %s"
         % (s.Angle, s.SteeringAngle, g9(s.Odometer), g9(s.TractionUsage)))
    emit("  skid %s %s ntouch %d fwdspeed %s velmag %s"
         % (g9(s.SkidLeft), g9(s.SkidRight), s.nWheelsTouchingGround,
            g9(s.ForwardSpeed), g9(s.VelocityMagnitude)))
    emit("  gear %d throttle %s rpm %s redline %s clutch %d"
         % (s.CurrentGear, g9(s.Throttle), g9(s.RPM), g9(s.RedLineSyncRPM),
            s.ClutchEngaged))
    emit("  drivermode %d boost %s burnout %d %s %s %s"
         % (s.DriverMode, g9(s.BoostFactor), s.BurnOutState,
            g9(s.BurnOutTime), g9(s.BurnOutTraction), g9(s.BurnOutAllow)))
    pmat("relcoord", s.RelCoordMatrix)
    emit("  matrixvalid %d" % s.MatrixValid)
    emit("  tail       " + " ".join("%02x" % b for b in s.tail))


def pshort(tag, s):
    emit("%s ntouch %d touch %s terr %s crossed %s"
         % (tag, s.nWheelsTouchingGround,
            " ".join("%d" % x for x in s.WheelTouchingGround),
            " ".join("%d" % x for x in s.WheelTerrain),
            " ".join("%d" % x for x in s.CrossedWheelTerrain)))


# --------------------------------------------------------------- scenarios

INFO = None


def fresh():
    s = State()
    fill_pattern(s)
    s.pCarInfo = INFO
    return s


def s_init():
    emit("== init ==")
    s = State()
    fill_pattern(s)
    init(s, INFO)
    pstate("after ctor", s)


def s_reset():
    emit("== reset ==")
    s = fresh()
    reset_car(s)
    pstate("after reset", s)


def s_reset_for_sound():
    emit("== reset for sound ==")
    s = fresh()
    reset_car(s)

    for i in range(4):
        s.WheelRoadNoise[i] = f32(0.5 + float(i))
    s.CurrentGear     = 4
    s.ClutchEngaged   = 0
    s.BoostFactor     = f32(2.5)
    s.BurnOutState    = 3
    s.BurnOutTime     = f32(1.5)
    s.BurnOutTraction = f32(0.25)
    s.Throttle        = f32(0.75)
    s.ForwardSpeed    = f32(40.0)
    s.RPM             = f32(6500.0)
    s.RedLineSyncRPM  = f32(7000.0)
    s.Odometer        = f32(123.5)
    s.Angle           = 1000
    s.SteeringAngle   = 2000
    s.MatrixValid     = 1
    s.Position[0]     = f32(10.0)

    for i in range(4):
        s.WheelAngularVelocity[i] = f32(9.0 + float(i))
        s.WheelZForce[i]          = f32(3.0)
        s.WheelTouchingGround[i]  = 0
        s.WheelTerrain[i]         = 7
        s.CrossedWheelTerrain[i]  = 9
    s.nWheelsTouchingGround = 0
    s.SkidLeft  = f32(4.0)
    s.SkidRight = f32(5.0)

    reset_car_for_sound(s)
    pstate("after reset for sound", s)


def s_terrain():
    emit("== terrain ==")
    s = fresh()
    reset_car(s)
    pshort("  reset       ", s)

    set_wheel_terrain(s, 0, 5)
    set_wheel_terrain(s, 1, 3)
    pshort("  set 0=5 1=3 ", s)

    set_wheel_terrain(s, 0, 2)
    pshort("  set 0=2     ", s)

    set_wheel_terrain(s, 1, 3)
    pshort("  set 1=3     ", s)

    set_wheel_terrain(s, 2, -4)
    pshort("  set 2=-4    ", s)

    begin_timestep(s)
    pshort("  begin       ", s)

    set_wheel_terrain(s, 3, 8)
    pshort("  set 3=8     ", s)


def s_touching():
    emit("== touching ==")
    s = fresh()
    reset_car(s)
    pshort("  reset       ", s)

    seq = [(0, 0), (0, 0), (1, 0), (1, 1), (1, 1),
           (2, 0), (3, 0), (3, 1), (0, 1), (2, 1)]
    for wheel, val in seq:
        set_wheel_touching_ground(s, wheel, val)
        pshort("  w%d=%d        " % (wheel, val), s)

    set_wheel_touching_ground(s, 1, 0)
    pshort("  w1=0        ", s)
    set_wheel_touching_ground(s, 1, 42)
    pshort("  w1=42       ", s)
    set_wheel_touching_ground(s, 1, -1)
    pshort("  w1=-1       ", s)


def s_yaw():
    emit("== yaw ==")
    vx = [f32(1.0), f32(0.0), f32(-1.0), f32(-1.0), f32(0.5), f32(3.0),
          f32(0.0)]
    vy = [f32(0.0), f32(1.0), f32(0.0), f32(-1.0), f32(0.25), f32(-4.0),
          f32(0.0)]
    ang = [0, 16384, 32768, 49152, 1000, 60000, 12345]
    spd = [f32(10.0), f32(4.99999), f32(5.0), f32(-20.0), f32(0.0),
           f32(100.0), f32(5.0)]

    s = fresh()
    reset_car(s)

    for i in range(len(vx)):
        s.Velocity[0] = vx[i]
        s.Velocity[1] = vy[i]
        for j in range(len(ang)):
            s.Angle = ang[j]
            s.ForwardSpeed = spd[i]
            emit("  v %s %s ang %u spd %s -> yaw %s always %s"
                 % (g9(vx[i]), g9(vy[i]), ang[j], g9(spd[i]),
                    g9(get_yaw(s)), g9(get_yaw_always(s))))


def s_transform():
    emit("== transform ==")
    # Case 6 is the one where z decides: x*x + y*y is 0.5 and does not clear
    # the threshold, but with z*z it is 1.5 and does.
    vx = [f32(3.0), f32(0.5), f32(0.0), f32(-2.0), f32(0.7), f32(0.6),
          f32(0.5)]
    vy = [f32(4.0), f32(0.5), f32(0.0), f32(0.0), f32(0.7), f32(0.8),
          f32(0.5)]
    vz = [f32(0.0), f32(0.0), f32(0.0), f32(1.0), f32(0.0), f32(0.0),
          f32(1.0)]
    spd = [f32(20.0), f32(1.0), f32(0.0), f32(-20.0), f32(1.0), f32(-1.0),
           f32(9.0)]
    ang = [0, 8192, 16384, 40000, 22222, 65535, 3000]

    for i in range(len(vx)):
        s = fresh()
        reset_car(s)

        s.Velocity[0] = vx[i]
        s.Velocity[1] = vy[i]
        s.Velocity[2] = vz[i]
        s.Velocity[3] = f32(0.0)
        s.ForwardSpeed = spd[i]
        s.Angle = ang[i]

        get_transform_matrix(s)
        emit("  case %d v %s %s %s spd %s ang %u"
             % (i, g9(vx[i]), g9(vy[i]), g9(vz[i]), g9(spd[i]), ang[i]))
        pmat("    matrix", s.RelCoordMatrix)
        emit("    valid %d" % s.MatrixValid)

        s.Velocity[0] = f32(999.0)
        s.Angle = 111
        get_transform_matrix(s)
        pmat("    cached", s.RelCoordMatrix)

        s.MatrixValid = 0
        get_transform_matrix(s)
        pmat("    rebuilt", s.RelCoordMatrix)

    s = fresh()
    reset_car(s)
    s.Velocity[0] = f32(2.0)
    s.Velocity[1] = f32(1.0)
    s.Velocity[2] = f32(0.0)
    s.Velocity[3] = f32(7.0)
    s.ForwardSpeed = f32(-3.0)
    get_transform_matrix(s)
    pmat("  pad participates", s.RelCoordMatrix)


def s_spaces():
    emit("== spaces ==")
    px = [f32(0.0), f32(10.0), f32(-5.5)]
    py = [f32(0.0), f32(-3.0), f32(8.25)]
    qx = [f32(1.0), f32(0.0), f32(-2.5), f32(100.0)]
    qy = [f32(0.0), f32(1.0), f32(3.5), f32(-50.0)]

    for i in range(3):
        s = fresh()
        reset_car(s)
        s.Position = [px[i], py[i], f32(1.5), f32(0.0)]
        s.Velocity = [f32(3.0), f32(4.0), f32(0.0), f32(0.0)]
        s.ForwardSpeed = f32(25.0)
        s.Angle = 9000

        emit("  pos %s %s" % (g9(px[i]), g9(py[i])))

        for j in range(4):
            q = [qx[j], qy[j]]
            w2c = world_to_car2(s, q)
            c2w = car_to_world(s, q)
            c2wu = car_to_world_unadjusted(s, q)
            w2c3 = world_to_car3(s, [qx[j], qy[j], f32(2.25), f32(0.0)])

            emit("    q %s %s w2c %s %s c2w %s %s c2wu %s %s"
                 % (g9(qx[j]), g9(qy[j]), g9(w2c[0]), g9(w2c[1]),
                    g9(c2w[0]), g9(c2w[1]), g9(c2wu[0]), g9(c2wu[1])))
            emit("      w2c3 %s %s %s pad %08x"
                 % (g9(w2c3[0]), g9(w2c3[1]), g9(w2c3[2]), bitsof(w2c3[3])))

    s = fresh()
    reset_car(s)
    s.Position = [f32(1.0), f32(2.0), f32(3.0), f32(4.0)]
    s.ForwardSpeed = f32(0.0)
    s.Angle = 0
    out3 = world_to_car3(s, [f32(5.0), f32(6.0), f32(7.0), f32(11.0)])
    emit("  pad subtract -> %s %s %s pad %08x"
         % (g9(out3[0]), g9(out3[1]), g9(out3[2]), bitsof(out3[3])))


def s_wheels():
    emit("== wheels ==")
    wangle = [f32(0.0), f32(1.5), f32(-2.25), f32(1000.0)]
    susp = [f32(0.0), f32(0.125), f32(-0.0625), f32(1.5)]
    steer = [0, 4096, 32768, 65535]

    for k in range(len(steer)):
        s = fresh()
        reset_car(s)

        for i in range(4):
            s.WheelAngle[i] = wangle[i]
            s.WheelSuspensionHeight[i] = susp[i]
        s.SteeringAngle = steer[k]

        calculate_wheel_matrices(s)

        emit("  steer %u" % steer[k])
        for i in range(4):
            pmat("    wheel%d" % i, s.WheelMatrix[i])
            pmat("    brake%d" % i, s.BrakeMatrix[i])

    s = fresh()
    reset_car(s)
    for i in range(4):
        s.WheelAngle[i] = f32(0.5 * float(i + 1))
        s.WheelSuspensionHeight[i] = f32(0.25 * float(i))
    s.SteeringAngle = 8192
    calculate_wheel_matrices_one(s, 2)
    emit("  single wheel 2")
    for i in range(4):
        pmat("    wheel%d" % i, s.WheelMatrix[i])


def s_geometry():
    emit("== geometry ==")
    yaws = [0, 8192, 30000, 65535]

    for k in range(len(yaws)):
        s = fresh()
        reset_car(s)
        s.Position = [f32(12.5), f32(-7.25), f32(3.0), f32(0.0)]

        s.BodyMatrix = emath_check.erotate_z(emath_check.mat_identity(),
                                             yaws[k])
        s.GeometryPosition = calculate_geometry_position(s)

        emit("  yaw %u" % yaws[k])
        pvec3("    geompos", s.GeometryPosition)

    s = fresh()
    reset_car(s)
    s.Position = [f32(0.0)] * 4
    s.BodyMatrix = emath_check.mat_identity()
    s.BodyMatrix[12] = f32(100.0)
    s.BodyMatrix[13] = f32(200.0)
    s.BodyMatrix[14] = f32(300.0)
    s.GeometryPosition = calculate_geometry_position(s)
    pvec3("  translated", s.GeometryPosition)


SCENARIOS = [
    ("init", s_init),
    ("reset", s_reset),
    ("reset_for_sound", s_reset_for_sound),
    ("terrain", s_terrain),
    ("touching", s_touching),
    ("yaw", s_yaw),
    ("transform", s_transform),
    ("spaces", s_spaces),
    ("wheels", s_wheels),
    ("geometry", s_geometry),
]


def model():
    global INFO, OUT
    OUT = []
    INFO = make_info()

    emit("sizes state 1024 wheelinfo 32 infoprefix 416")
    for _, fn in SCENARIOS:
        fn()
    emit("printstate returned")
    return OUT


# --------------------------------------------------------------- the driver


# A mutation can turn a loop into one with no exit. With no deadline here
# that mutant runs until something kills it and stalls the whole pass; the
# harness itself runs in well under a second.
HARNESS_TIMEOUT = 60


def run_harness(exe, out_path):
    try:
        with open(out_path, "w") as fh:
            r = subprocess.run([str(exe)], stdout=fh,
                               stderr=subprocess.PIPE, text=True,
                               timeout=HARNESS_TIMEOUT)
    except subprocess.TimeoutExpired:
        print("harness hung, killed after %d s" % HARNESS_TIMEOUT)
        return -9999
    if r.returncode != 0:
        print("harness exited %d" % r.returncode)
        if r.stderr:
            print(r.stderr[:2000])
    return r.returncode


def diff(model_lines, harness_lines, label, quiet=False):
    d = list(difflib.unified_diff(model_lines, harness_lines,
                                  "model", "harness", lineterm="", n=1))
    if d and not quiet:
        for ln in d[:80]:
            print(ln)
        if len(d) > 80:
            print("... %d more diff lines" % (len(d) - 80))
    return len([x for x in d if x.startswith(("+", "-"))
                and not x.startswith(("+++", "---"))])


# The mutations. Each is (name, file, before, after) and each is applied to
# a copy of the tree, rebuilt and re-diffed. A mutation that does not move a
# line is either an untested rule or an equivalent mutant, and the difference
# has to be argued rather than assumed.
MUTATIONS = [
    # -- the constants -------------------------------------------------
    ("pi-from-library", CS,
     "#define IMAGE_PI    carstate_f32(0x40490fd0u)",
     "#define IMAGE_PI    3.14159274f"),
    ("twopi-from-library", CS,
     "#define IMAGE_TWOPI carstate_f32(0x40c90fd0u)",
     "#define IMAGE_TWOPI 6.28318548f"),
    ("yaw-cutoff", CS,
     "#define YAW_MIN_SPEED 5.0f",
     "#define YAW_MIN_SPEED 4.0f"),

    # -- lifetime ------------------------------------------------------
    ("init-no-odometer", CS,
     "    s->Odometer = 0.0f;" + NL + "    s->DistanceMoved",
     "    s->DistanceMoved"),
    ("init-no-distance", CS,
     "    s->DistanceMoved = 0.0f;" + NL, ""),
    ("init-clears-pad", CS,
     "    s->Position.z = 0.0f;" + NL + NL + "    s->GeometryPosition.x",
     "    s->Position.z = 0.0f;" + NL + "    s->Position.pad = 0.0f;" + NL
     + NL + "    s->GeometryPosition.x"),
    ("init-no-drivermode", CS,
     "    s->DriverMode = 0;" + NL + NL + "    s->pTopologyCoordinate",
     "    s->pTopologyCoordinate"),
    ("reset-rpm", CS, "    s->RPM             = 1000.0f;",
     "    s->RPM             = 1500.0f;"),
    ("reset-redline", CS, "    s->RedLineSyncRPM  = -1.0f;",
     "    s->RedLineSyncRPM  = 0.0f;"),
    ("reset-gear", CS, "    s->CurrentGear     = 1;",
     "    s->CurrentGear     = 0;"),
    ("reset-clutch", CS, "    s->ClutchEngaged   = 1;",
     "    s->ClutchEngaged   = 0;"),
    ("reset-boost", CS, "    s->BoostFactor     = 1.0f;",
     "    s->BoostFactor     = 0.0f;"),
    ("reset-burnout-traction", CS, "    s->BurnOutTraction = 1.0f;",
     "    s->BurnOutTraction = 0.0f;"),
    ("reset-ntouch", CS, "    s->nWheelsTouchingGround = 4;" + NL + NL
     + "    carstate_calculate_wheel_matrices(s);",
     "    s->nWheelsTouchingGround = 0;" + NL + NL
     + "    carstate_calculate_wheel_matrices(s);"),
    ("reset-no-wheel-matrices", CS,
     "    carstate_calculate_wheel_matrices(s);" + NL + NL
     + "    s->TractionUsage   = 0.0f;",
     "    s->TractionUsage   = 0.0f;"),
    ("reset-no-relcoord-clear", CS,
     "    memset(&s->RelCoordMatrix, 0, 64);", "    (void)0;"),
    ("reset-relcoord-identity", CS,
     "    memset(&s->RelCoordMatrix, 0, 64);",
     "    bIdentity(&s->RelCoordMatrix);"),
    ("reset-matrixvalid", CS,
     "    memset(&s->RelCoordMatrix, 0, 64);" + NL + "    s->MatrixValid = 0;",
     "    memset(&s->RelCoordMatrix, 0, 64);" + NL + "    s->MatrixValid = 1;"),

    # -- reset for sound -----------------------------------------------
    ("sound-clears-roadnoise", CS,
     "        s->WheelSuspensionHeight[i]   = 0.0f;" + NL
     + "        s->WheelTractionUsage[i]      = 0.0f;" + NL
     + "        s->WheelTouchingGround[i]     = 1;" + NL
     + "        s->WheelTerrain[i]            = TERRAIN_DEFAULT;" + NL
     + "        s->CrossedWheelTerrain[i]     = TERRAIN_DEFAULT;" + NL
     + "        s->WheelSlip[i].x             = 0.0f;" + NL
     + "        s->WheelSlip[i].y             = 0.0f;" + NL
     + "    }" + NL + NL + "    s->SkidRight             = 0.0f;",
     "        s->WheelSuspensionHeight[i]   = 0.0f;" + NL
     + "        s->WheelTractionUsage[i]      = 0.0f;" + NL
     + "        s->WheelTouchingGround[i]     = 1;" + NL
     + "        s->WheelTerrain[i]            = TERRAIN_DEFAULT;" + NL
     + "        s->CrossedWheelTerrain[i]     = TERRAIN_DEFAULT;" + NL
     + "        s->WheelSlip[i].x             = 0.0f;" + NL
     + "        s->WheelSlip[i].y             = 0.0f;" + NL
     + "        s->WheelRoadNoise[i]          = 0.0f;" + NL
     + "    }" + NL + NL + "    s->SkidRight             = 0.0f;"),
    ("sound-no-rpm", CS, "    s->RPM = 1000.0f;" + NL + NL + "    for (i = 0;",
     "    for (i = 0;"),
    ("sound-resets-gear", CS,
     "    s->SkidRight             = 0.0f;",
     "    s->CurrentGear           = 1;" + NL
     + "    s->SkidRight             = 0.0f;"),
    ("sound-no-ntouch", CS,
     "    s->nWheelsTouchingGround = 4;" + NL
     + "    s->VelocityMagnitude     = 0.0f;",
     "    s->VelocityMagnitude     = 0.0f;"),

    # -- begin timestep -------------------------------------------------
    ("begin-sets-terrain-too", CS,
     "        s->CrossedWheelTerrain[i] = TERRAIN_DEFAULT;",
     "        s->CrossedWheelTerrain[i] = TERRAIN_DEFAULT,"
     " s->WheelTerrain[i] = TERRAIN_DEFAULT;"),
    ("begin-zero-not-one", CS,
     "    for (i = 3; i >= 0; i--)" + NL
     + "        s->CrossedWheelTerrain[i] = TERRAIN_DEFAULT;",
     "    for (i = 3; i >= 0; i--)" + NL
     + "        s->CrossedWheelTerrain[i] = 0;"),
    ("begin-three-wheels", CS,
     "    for (i = 3; i >= 0; i--)", "    for (i = 3; i >= 1; i--)"),

    # -- yaw -------------------------------------------------------------
    ("yaw-no-gate", CS,
     "    if (s->ForwardSpeed < YAW_MIN_SPEED)" + NL + "        return 0.0f;",
     "    if (0)" + NL + "        return 0.0f;"),
    ("yaw-gate-le", CS,
     "    if (s->ForwardSpeed < YAW_MIN_SPEED)",
     "    if (s->ForwardSpeed <= YAW_MIN_SPEED)"),
    ("yaw-atan-swapped", CS,
     "bATan(s->Velocity.x, s->Velocity.y)",
     "bATan(s->Velocity.y, s->Velocity.x)"),
    ("yaw-delta-reversed", CS,
     "(uint16_t)((uint32_t)s->Angle - (uint32_t)heading)",
     "(uint16_t)((uint32_t)heading - (uint32_t)s->Angle)"),
    ("yaw-no-mask", CS,
     "    uint16_t delta   = (uint16_t)((uint32_t)s->Angle"
     " - (uint32_t)heading);" + NL
     + "    float    rad     = (float)(int32_t)delta * BAM_TO_RAD;",
     "    int32_t  delta   = (int32_t)((uint32_t)s->Angle"
     " - (uint32_t)heading);" + NL
     + "    float    rad     = (float)(int32_t)delta * BAM_TO_RAD;"),
    ("yaw-two-sided-fold", CS,
     "    if (IMAGE_PI < rad)" + NL + "        rad -= IMAGE_TWOPI;",
     "    if (IMAGE_PI < rad)" + NL + "        rad -= IMAGE_TWOPI;" + NL
     + "    else if (rad < -IMAGE_PI)" + NL + "        rad += IMAGE_TWOPI;"),
    ("yaw-fold-le", CS, "    if (IMAGE_PI < rad)", "    if (IMAGE_PI <= rad)"),

    # -- the transform cache ---------------------------------------------
    ("transform-no-cache", CS,
     "    if (s->MatrixValid)" + NL + "        return &s->RelCoordMatrix;",
     "    if (0)" + NL + "        return &s->RelCoordMatrix;"),
    ("transform-no-set-valid", CS,
     "    s->MatrixValid = 1;" + NL + "    return &s->RelCoordMatrix;",
     "    return &s->RelCoordMatrix;"),
    ("transform-threshold", CS, "    if (1.0f < lensq) {",
     "    if (0.5f < lensq) {"),
    ("transform-threshold-le", CS, "    if (1.0f < lensq) {",
     "    if (1.0f <= lensq) {"),
    ("transform-lensq-xy-only", CS,
     "    lensq = v.x * v.x + v.y * v.y + v.z * v.z;",
     "    lensq = v.x * v.x + v.y * v.y;"),
    ("transform-no-reverse-flip", CS,
     "    if (s->ForwardSpeed < 0.0f) {", "    if (0) {"),
    ("transform-reverse-uses-neg", CS,
     "        v.x = 0.0f - v.x;" + NL + "        v.y = 0.0f - v.y;" + NL
     + "        v.z = 0.0f - v.z;" + NL + "        v.w = 1.0f - v.w;",
     "        v.x = -v.x;" + NL + "        v.y = -v.y;" + NL
     + "        v.z = -v.z;" + NL + "        v.w = -v.w;"),
    ("transform-rows-swapped", CS,
     "        s->RelCoordMatrix.v0.x =  v.y;" + NL
     + "        s->RelCoordMatrix.v0.y = -v.x;",
     "        s->RelCoordMatrix.v0.x =  v.x;" + NL
     + "        s->RelCoordMatrix.v0.y = -v.y;"),
    ("transform-angle-sin-cos-swap", CS,
     "        s->RelCoordMatrix.v0.x =  n;" + NL
     + "        s->RelCoordMatrix.v0.y = -c;",
     "        s->RelCoordMatrix.v0.x =  c;" + NL
     + "        s->RelCoordMatrix.v0.y = -n;"),
    ("transform-no-orthonormalize", CS,
     "    eOrthonormalizeMatrix(&s->RelCoordMatrix, &s->RelCoordMatrix);",
     "    (void)0;"),
    ("transform-row2-z", CS,
     "    s->RelCoordMatrix.v2.z = 1.0f;",
     "    s->RelCoordMatrix.v2.z = -1.0f;"),

    # -- the spaces --------------------------------------------------------
    ("w2c-no-transpose", CS,
     "    bTransposeMatrix(&t, carstate_get_transform_matrix(s));" + NL + NL
     + "    d.x   = in->x - s->Position.x;" + NL
     + "    d.y   = in->y - s->Position.y;" + NL
     + "    d.z   = 0.0f;",
     "    t = *carstate_get_transform_matrix(s);" + NL + NL
     + "    d.x   = in->x - s->Position.x;" + NL
     + "    d.y   = in->y - s->Position.y;" + NL
     + "    d.z   = 0.0f;"),
    ("w2c-no-translate", CS,
     "    d.x   = in->x - s->Position.x;" + NL
     + "    d.y   = in->y - s->Position.y;" + NL
     + "    d.z   = 0.0f;",
     "    d.x   = in->x;" + NL + "    d.y   = in->y;" + NL
     + "    d.z   = 0.0f;"),
    ("w2c3-no-pad-subtract", CS,
     "    d.pad = in->pad - s->Position.pad;", "    d.pad = in->pad;"),
    ("c2w-no-add", CS,
     "    out->x = t.x + s->Position.x;" + NL
     + "    out->y = t.y + s->Position.y;",
     "    out->x = t.x;" + NL + "    out->y = t.y;"),
    ("c2wu-z-not-zero", CS,
     "    v.x   = in->x;" + NL + "    v.y   = in->y;" + NL
     + "    v.z   = 0.0f;" + NL + "    v.pad = 0.0f;" + NL + NL
     + "    eMulVector3(&r, m, &v);",
     "    v.x   = in->x;" + NL + "    v.y   = in->y;" + NL
     + "    v.z   = 1.0f;" + NL + "    v.pad = 0.0f;" + NL + NL
     + "    eMulVector3(&r, m, &v);"),

    # -- the wheels ---------------------------------------------------------
    ("touch-always-counts", CS,
     "    if (was == 0) {" + NL + "        if (on != 0)" + NL
     + "            s->nWheelsTouchingGround++;" + NL + "    } else {" + NL
     + "        if (on == 0)" + NL + "            s->nWheelsTouchingGround--;"
     + NL + "    }",
     "    if (on != 0)" + NL + "        s->nWheelsTouchingGround++;" + NL
     + "    else" + NL + "        s->nWheelsTouchingGround--;"),
    ("touch-no-store", CS,
     "    s->WheelTouchingGround[wheel] = on;", "    (void)on;"),
    ("terrain-ge", CS, "    if (s->CrossedWheelTerrain[wheel] < t)",
     "    if (s->CrossedWheelTerrain[wheel] <= t)"),
    ("terrain-always-raises", CS,
     "    if (s->CrossedWheelTerrain[wheel] < t)" + NL
     + "        s->CrossedWheelTerrain[wheel] = t;",
     "    s->CrossedWheelTerrain[wheel] = t;"),
    ("terrain-crossed-only", CS,
     "    s->WheelTerrain[wheel] = t;", "    (void)0;"),
    ("wheel-spin-rounds", CS,
     "    spin = (uint16_t)((int32_t)(s->WheelAngle[wheel] * RAD_TO_BAM)"
     " & 0xffff);",
     "    spin = (uint16_t)((int32_t)(s->WheelAngle[wheel] * RAD_TO_BAM"
     " + 0.5f) & 0xffff);"),
    ("wheel-steer-all-four", CS, "    if (wheel < 2) {", "    if (1) {"),
    ("wheel-steer-rear-pair", CS, "    if (wheel < 2) {",
     "    if (wheel >= 2) {"),
    ("wheel-brake-gets-spin", CS,
     "    eRotateY(&wm, &wm, spin);",
     "    eRotateY(&wm, &wm, spin);" + NL + "    eRotateY(&bm, &bm, spin);"),
    ("wheel-susp-on-brake", CS,
     "    bm.v3.z = wi->PositionZ;",
     "    bm.v3.z = wi->PositionZ + s->WheelSuspensionHeight[wheel];"),
    ("wheel-no-susp", CS,
     "    wm.v3.z = wi->PositionZ + s->WheelSuspensionHeight[wheel];",
     "    wm.v3.z = wi->PositionZ;"),
    ("wheel-w-is-radius", CS,
     "    wm.v3.w = 1.0f;" + NL + NL + "    s->WheelMatrix[wheel] = wm;",
     "    wm.v3.w = wi->Radius;" + NL + NL + "    s->WheelMatrix[wheel] = wm;"),
    ("wheel-one-does-all", CS,
     "    for (i = 0; i < 4; i++)" + NL
     + "        carstate_calculate_wheel_matrices_one(s, i);",
     "    for (i = 3; i >= 0; i--)" + NL
     + "        carstate_calculate_wheel_matrices_one(s, i);"),

    # -- geometry ------------------------------------------------------------
    ("geom-adds-not-subtracts", CS,
     "    s->GeometryPosition.x   = s->Position.x   - cog.x;" + NL
     + "    s->GeometryPosition.y   = s->Position.y   - cog.y;" + NL
     + "    s->GeometryPosition.z   = s->Position.z   - cog.z;",
     "    s->GeometryPosition.x   = s->Position.x   + cog.x;" + NL
     + "    s->GeometryPosition.y   = s->Position.y   + cog.y;" + NL
     + "    s->GeometryPosition.z   = s->Position.z   + cog.z;"),
    ("geom-no-pad", CS,
     "    s->GeometryPosition.pad = s->Position.pad - cog.pad;",
     "    (void)0;"),
    ("geom-wrong-matrix", CS,
     "    bMulMatrixVec3(&cog, &s->BodyMatrix, &s->pCarInfo->CenterOfGravity);",
     "    bMulMatrixVec3(&cog, &s->RelCoordMatrix,"
     " &s->pCarInfo->CenterOfGravity);"),
]

# Mutants that cannot move a line. Each one is an argument, not an excuse.
#
#   yaw-two-sided-fold -- GetYawAlways masks the BAM difference to sixteen
#   bits before scaling, so rad is in [0, 2pi) and is never negative. A
#   second fold for rad < -pi is unreachable. The object only needs the one
#   branch because the mask has already done the other half of the job.
#
#   yaw-fold-le -- < and <= differ only at rad == IMAGE_PI exactly, and no
#   BAM difference produces it: over all 65536 values of delta the products
#   step straight past IMAGE_PI, which sits in a 402-ulp gap, 11 ulps below
#   the product at delta == 32768. That gap is the whole reason the object
#   carries 0x40490fd0 instead of bMath's 0x40490fdb -- with bMath's value
#   the half-turn lands exactly on the boundary and stops folding, which is
#   what pi-from-library catches.
#
#   transform-row2-z -- eOrthonormalizeMatrix rebuilds row 2 as
#   normalize(row0 cross row1) and never reads the incoming row 2, so the
#   store is dead. It is kept because the object stores it.
#
#   w2c3-no-pad-subtract -- the quadword subtract includes the pad, but
#   eMulVector3 forces w to 1 before the multiply, so the subtracted pad
#   cannot reach the result; the pad that comes back is the w of the
#   product. The subtract is a free consequence of doing it in one VU op,
#   not a decision, and nothing downstream can see it.
#
#   c2wu-z-not-zero -- in both branches the two basis rows are built with
#   z == 0, so the orthonormalized row 2 is (0, 0, +-1) and m[8] and m[9]
#   are zero. The z lane cannot reach the x and y that the function
#   returns, whatever is put in it.
#
#   terrain-ge -- < and <= differ only when CrossedWheelTerrain[wheel] is
#   already equal to t, and the store then writes the value that is there.
#
#   wheel-one-does-all -- the four per-wheel calls are independent: each
#   writes only its own WheelMatrix and BrakeMatrix and reads nothing any
#   other call writes, so the order is not observable.
EQUIVALENT = [
    "yaw-two-sided-fold",
    "yaw-fold-le",
    "transform-row2-z",
    "w2c3-no-pad-subtract",
    "c2wu-z-not-zero",
    "terrain-ge",
    "wheel-one-does-all",
]
EXPECT_MISSING = []


# The write, its OneDrive retry, and the journal that lets a killed pass be
# recovered from are all hostbuild's.
write_source = hostbuild.write_source


def mutate_pass(quiet=False):
    import shutil

    base_model = model()
    survived = []
    equivalent = []
    missing = []
    caught = 0

    src_path = ROOT / CS
    original = src_path.read_text(encoding="utf-8", newline="")

    with tempfile.TemporaryDirectory() as tmp:
        exe = hostbuild.build(tmp, SOURCES, name="carstate_test")
        out = Path(tmp) / "base.txt"
        run_harness(exe, out)
        base_lines = out.read_text().splitlines()
        if diff(base_model, base_lines, "base", quiet=True):
            print("base already differs -- fix that before mutating")
            return 1

    for name, rel, before, after in MUTATIONS:
        path = ROOT / rel
        text = path.read_text(encoding="utf-8", newline="")
        # The ported sources are CRLF and the tools are LF, so a multi-line
        # pattern written with bare newlines misses every time against a
        # source file -- silently, as a pattern that is not found rather
        # than as a mutant that survived.
        crlf = (chr(13) + NL) in text
        probe = before.replace(NL, chr(13) + NL) if crlf else before
        repl = after.replace(NL, chr(13) + NL) if crlf else after

        if probe not in text:
            missing.append(name)
            if name not in EXPECT_MISSING:
                print("  %-30s PATTERN NOT FOUND" % name)
            continue
        try:
            write_source(path, text.replace(probe, repl, 1))
            with tempfile.TemporaryDirectory() as tmp:
                try:
                    exe = hostbuild.build(tmp, SOURCES, name="carstate_test")
                except SystemExit:
                    print("  %-30s did not compile (caught)" % name)
                    caught += 1
                    continue
                out = Path(tmp) / "m.txt"
                rc = run_harness(exe, out)
                if rc != 0:
                    print("  %-30s crashed the harness (caught)" % name)
                    caught += 1
                    continue
                lines = out.read_text().splitlines()
                n = diff(base_model, lines, name, quiet=True)
                if n:
                    print("  %-30s caught, %d lines" % (name, n))
                    caught += 1
                elif name in EQUIVALENT:
                    print("  %-30s survived, equivalent by construction"
                          % name)
                    equivalent.append(name)
                else:
                    print("  %-30s SURVIVED" % name)
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
    return 1 if (holes or stale) else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mutate", action="store_true")
    ap.add_argument("--dump", metavar="DIR")
    args = ap.parse_args()

    if args.mutate:
        sys.exit(mutate_pass())

    lines = model()

    with tempfile.TemporaryDirectory() as tmp:
        exe = hostbuild.build(tmp, SOURCES, name="carstate_test")
        out = Path(tmp) / "harness.txt"
        run_harness(exe, out)
        harness = out.read_text().splitlines()

        if args.dump:
            d = Path(args.dump)
            d.mkdir(parents=True, exist_ok=True)
            (d / "model.txt").write_text(NL.join(lines) + NL)
            (d / "harness.txt").write_text(NL.join(harness) + NL)
            print("wrote %s" % d)

    n = diff(lines, harness, "carstate")
    print("%d scenarios, %d lines, %d differ"
          % (len(SCENARIOS), len(lines), n))
    sys.exit(1 if n else 0)


if __name__ == "__main__":
    main()
