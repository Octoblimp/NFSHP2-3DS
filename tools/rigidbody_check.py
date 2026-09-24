"""Cross-check 3DS Files/source/rigidbody.c against a model of RigidBody.

RigidBody is the sixth slice of task 25, and a prerequisite the task list
never named: Suspension, PhysicsCar and Car all hold one or point at one.

It is a Baraff-style rigid body. The integrated state is position,
orientation, linear momentum and angular momentum; velocity, angular
velocity and the world transform are auxiliaries recomputed from it.

Six things this transcript exists to pin down.

**The w lane is load-bearing, and not consistently.** Every quadword op
in this object is `lqc2`/`sqc2`, so copies and adds move all four lanes,
but the cross products are `vopmula`/`vopmsub`, which write xyz only --
so a moment's w lane comes from the *position* vector that happened to
be in the destination register. The constructor clears xyz and leaves w.
The transcript prints w everywhere for that reason.

**ApplyForce clamps the force but takes the moment from the unclamped
one.** `lqc2 vf1,0(a1)` reloads the caller's vector after the clamped
copy has already gone into the accumulator. ApplyImpulse does the
opposite -- its cross product reads the clamped stack copy. The two look
identical at a glance and are not.

**SetState rebuilds the body tensor from three reciprocals.** It
inverts only the diagonal of I_body_inv rather than calling
bInvertMatrix, so a tensor with off-diagonal terms does not round-trip.
One scenario feeds it one anyway.

**GetDerivative's speed limiter reads the slope off R.** R.v0.z is how
steeply the body is pointed up or down; uphill scales the limit down to
0.9, downhill up to 1.1, and the brake it applies is a *negative* force
along the body's own x axis, clamped at -0.5.

**The MaxMomentZ clamp reads the accumulator, not the derivative it
writes.** Both damping terms have already been added to Ldot by then and
the comparison does not see them.

**GetSize answers 32, not 29.** The integrator is told the state is a
whole RigidBodyState; the three floats past MotionDampingFactor are its
tail padding, and GetState/SetState never move them. (IntegrateEuler
writes them in place; see physicssystem.c.)

The float layer and the matrix routines are imported from bvector_check
-- itself a model of bVector.obj and bMatrix.obj written from the ELF --
and the Table from engine_check, so neither is being checked against
itself here.

    python tools/rigidbody_check.py
    python tools/rigidbody_check.py --mutate
    python tools/rigidbody_check.py --dump out/rigidbody
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
import engine_check as EN

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

SOURCES = [
    "tools/src/rigidbody_test.c",
    "3DS Files/source/rigidbody.c",
    "3DS Files/source/bmatrix.c",
    "3DS Files/source/table.c",
    "3DS Files/source/bvector.c",
    "3DS Files/source/bmath.c",
    "3DS Files/source/bmathtab.c",
]

RH = "3DS Files/source/rigidbody.h"
RC = "3DS Files/source/rigidbody.c"

PTR = 8
SLACK = PTR - 4

f32 = BV.f32
fmul, fadd, fsub, fdiv, fneg, fsqrt = (BV.fmul, BV.fadd, BV.fsub,
                                       BV.fdiv, BV.fneg, BV.fsqrt)


def bits(w):
    return struct.unpack("<f", struct.pack("<I", w))[0]


def fbits(x):
    return struct.unpack("<I", struct.pack("<f", f32(x)))[0]


def g9(x):
    return "%.9g" % x


def pad(s, n):
    return s + " " * (n - len(s)) if len(s) < n else s


OUT = []


def emit(s):
    OUT.append(s)


def pv(tag, v):
    emit("%s %s %s %s %s" % (tag, g9(v[0]), g9(v[1]), g9(v[2]), g9(v[3])))


def pm(tag, m):
    for i in range(4):
        emit("%s[%d] %s %s %s %s"
             % (tag, i, g9(m[i][0]), g9(m[i][1]), g9(m[i][2]), g9(m[i][3])))


def pf(tag, x):
    emit("%s %s" % (tag, g9(x)))


# ------------------------------------------------------------- the image

C_GRAVITY = bits(0x411ccccd)      # gp-20544
C_LIMIT_BASE = bits(0x3ff33333)   # gp-29996
C_SPEED_SCALE = bits(0x400f1b08)  # gp-29992
C_HP_BONUS = bits(0x3f83d70a)     # gp-20488
C_UPHILL_CLAMP = bits(0x3e99999a)    # gp-20524
C_UPHILL_FLOOR = bits(0x3f666666)    # gp-20528
C_DOWNHILL_CLAMP = bits(0x3e99999a)  # gp-20532
C_DOWNHILL_CEIL = bits(0x3f8ccccd)   # gp-20536
C_BRAKE_GAIN = bits(0x40a00000)      # gp-20516
C_BRAKE_FLOOR = bits(0xbf000000)     # gp-20520
C_DAMP_SPEED_DIV = bits(0x40800000)  # gp-20512
C_DAMP_SPIN_DIV = bits(0x40000000)   # gp-20508
C_DAMP_RISE = bits(0x3dcccccd)       # gp-20496
C_DAMP_FALL = bits(0x41200000)       # gp-20492
C_DAMP_L_GAIN = bits(0x40000000)     # gp-20500
C_DAMP_P_GAIN = bits(0x41000000)     # gp-20504

C_MAX_FORCE = bits(0x44960000)
C_MAX_MOMENT = bits(0x42c80000)
C_MAX_IMPULSE = bits(0x447a0000)
C_MAX_ANG_IMPULSE = bits(0x41200000)

VT_RIGIDBODY = 0x002987e8
VT_PHYSICSCOMPONENT = 0x00298728

# The gp pool the two functions read, checked against the ELF so a
# fat-fingered constant fails loudly rather than printing 800 wrong lines.
_pool = struct.unpack("<15I", BM.ELF.read(0x00323bb0, 60))
assert _pool[0] == 0x411ccccd and _pool[-1] == 0x3f83d70a, _pool
assert struct.unpack("<2I", BM.ELF.read(0x003216c4, 8)) \
    == (0x3ff33333, 0x400f1b08)

# _GLOBAL_$I$__9RigidBodyP13RigidBodyInfo, 0x00193d20: two Tables over
# the value arrays at 0x00308cf0 (6 entries) and 0x00308d20 (8).
ANGDAMP_VALUES = list(struct.unpack("<6f", BM.ELF.read(0x00308cf0, 24)))
MOTION_VALUES = list(struct.unpack("<8f", BM.ELF.read(0x00308d20, 32)))

ANGDAMP = EN.Table()
EN.table_init(ANGDAMP, ANGDAMP_VALUES, 6, f32(0.0), f32(10.0))
MOTION = EN.Table()
EN.table_init(MOTION, MOTION_VALUES, 8, f32(0.0), f32(1.0))

# -------------------------------------------------------------- the layout

PS2_RB = [("pNext", 0), ("pPrev", 4), ("_vtable", 8), ("RBI", 12),
          ("State", 16), ("Velocity", 144), ("AngularVelocity", 160),
          ("Matrix", 176), ("ForceAccumulator", 240),
          ("MomentAccumulator", 256), ("MotionDamping", 272), ("IsHP", 276),
          ("Mass", 280), ("Mass_inv", 284), ("I_body_inv", 288),
          ("CenterOfGravity", 352), ("MaxMomentZ", 368),
          ("SpeedLimiter", 372), ("CatchUpMultiplier", 376)]
PS2_STATE = [("X", 0), ("R", 16), ("P", 80), ("L", 96),
             ("MotionDampingFactor", 112)]
PS2_INFO = [("Mass", 0), ("Xdim", 4), ("Ydim", 8), ("Zdim", 12),
            ("InertiaTensor", 16)]


def s_layout():
    emit("[layout]")
    emit("sizeof_host RigidBody %d" % (384 + 2 * SLACK))
    emit("sizeof RigidBodyState 128")
    emit("sizeof RigidBodyInfo 80")
    emit("slack %d" % SLACK)

    # RBI moves by one slack term -- the wider pointer needs eight-byte
    # alignment, so four bytes of padding go in front of it. Everything
    # after it has both that padding and the extra pointer width in front.
    for name, off in PS2_RB:
        emit("off %s %d" % (pad(name, 24),
                            off + (SLACK if off == 12 else
                                   2 * SLACK if off > 12 else 0)))
    for name, off in PS2_STATE:
        emit("off %s %d" % (pad(name, 24), off))
    for name, off in PS2_INFO:
        emit("off %s %d" % (pad(name, 24), off))

    emit("width links 4 4")
    emit("width MotionDamping 4")
    emit("width IsHP 4")
    emit("signed MotionDamping -1")
    emit("signed IsHP -1")

    for name, w in (("gravity  ", 0x411ccccd), ("limitbase", 0x3ff33333),
                    ("spdscale ", 0x400f1b08), ("hpbonus  ", 0x3f83d70a),
                    ("upclamp  ", 0x3e99999a), ("upfloor  ", 0x3f666666),
                    ("dnclamp  ", 0x3e99999a), ("dnceil   ", 0x3f8ccccd),
                    ("brakegain", 0x40a00000)):
        emit("const %s %08x" % (name, w))
    emit("const brakefloor %08x" % 0xbf000000)
    emit("const maxforce  %08x" % 0x44960000)
    emit("const maxmoment %08x" % 0x42c80000)
    emit("const maximpulse %08x" % 0x447a0000)
    emit("const maxangimp %08x" % 0x41200000)
    emit("vtable RigidBody %08x" % VT_RIGIDBODY)
    emit("vtable PhysicsComponent %08x" % VT_PHYSICSCOMPONENT)

    for name, t in (("angdamp", ANGDAMP), ("motion", MOTION)):
        emit("table %s n=%d lo=%s hi=%s mult=%s"
             % (name, t.n, g9(t.lo), g9(t.hi), g9(t.mult)))
        for j in range(t.n):
            emit("table %s [%d] %s" % (name, j, g9(t.entries[j])))


# --------------------------------------------------------------- the model


def vec(b):
    return (f32(b), f32(b + 1.0), f32(b + 2.0), f32(b + 3.0))


def mat(b):
    return [tuple(f32(b + i * 4.0 + c) for c in range(4)) for i in range(4)]


def identity():
    return BV.bIdentity()


def setrow(m, i, r):
    m = list(m)
    m[i] = tuple(r)
    return m


class RB(object):
    """Everything the object holds, as Python floats already rounded."""

    def __init__(self):
        z = f32(0.0)
        self.links = (0, 0)
        self.vtable = 0
        self.rbi = None
        self.X = (z, z, z, z)
        self.R = identity()
        self.P = (z, z, z, z)
        self.L = (z, z, z, z)
        self.mdf = z
        self.V = (z, z, z, z)
        self.W = (z, z, z, z)
        self.M = identity()
        self.FA = (z, z, z, z)
        self.MA = (z, z, z, z)
        self.md = 0
        self.ishp = 0
        self.mass = z
        self.massinv = z
        self.Ibi = identity()
        self.cog = (z, z, z, z)
        self.maxmz = z
        self.speedlim = z
        self.catchup = z


def make_info(mass, ix, iy, iz, offdiag):
    t = identity()
    t = setrow(t, 0, (f32(ix), f32(offdiag), t[0][2], t[0][3]))
    t = setrow(t, 1, (t[1][0], f32(iy), f32(offdiag * 0.5), t[1][3]))
    t = setrow(t, 2, (t[2][0], t[2][1], f32(iz), t[2][3]))
    return {"mass": f32(mass), "x": f32(1.75), "y": f32(4.25),
            "z": f32(1.25), "I": t}


def dirty(rb, b):
    rb.links = (0xaaaa1111, 0xbbbb2222)
    rb.vtable = 0xcccc3333
    rb.rbi = None
    rb.X = vec(b + 10.0)
    rb.R = mat(b + 100.0)
    rb.P = vec(b + 20.0)
    rb.L = vec(b + 30.0)
    rb.mdf = f32(b + 40.0)
    rb.V = vec(b + 50.0)
    rb.W = vec(b + 60.0)
    rb.M = mat(b + 200.0)
    rb.FA = vec(b + 70.0)
    rb.MA = vec(b + 80.0)
    rb.md = 7
    rb.ishp = 9
    rb.mass = f32(b + 90.0)
    rb.massinv = f32(b + 91.0)
    rb.Ibi = mat(b + 300.0)
    rb.cog = vec(b + 400.0)
    rb.maxmz = f32(b + 500.0)
    rb.speedlim = f32(b + 501.0)
    rb.catchup = f32(b + 502.0)


def dump(p, rb):
    emit("%s.links %08x %08x" % (p, rb.links[0], rb.links[1]))
    emit("%s.vtable %08x" % (p, rb.vtable))
    emit("%s.rbi_null %d" % (p, 1 if rb.rbi is None else 0))
    pv(p + ".X", rb.X)
    pm(p + ".R", rb.R)
    pv(p + ".P", rb.P)
    pv(p + ".L", rb.L)
    pf(p + ".mdf", rb.mdf)
    pv(p + ".V", rb.V)
    pv(p + ".W", rb.W)
    pm(p + ".M", rb.M)
    pv(p + ".FA", rb.FA)
    pv(p + ".MA", rb.MA)
    emit("%s.md %d" % (p, rb.md))
    emit("%s.ishp %d" % (p, rb.ishp))
    pf(p + ".mass", rb.mass)
    pf(p + ".massinv", rb.massinv)
    pm(p + ".Ibi", rb.Ibi)
    pv(p + ".cog", rb.cog)
    pf(p + ".maxmz", rb.maxmz)
    pf(p + ".speedlim", rb.speedlim)
    pf(p + ".catchup", rb.catchup)


# --------------------------------------------------------------- VU idioms

def len3(v):
    """vmul.xyz then vaddy.x then vaddz.x: ((xx + yy) + zz), that order."""
    return fsqrt(fadd(fadd(fmul(v[0], v[0]), fmul(v[1], v[1])),
                      fmul(v[2], v[2])))


def dot3(a, b):
    return fadd(fadd(fmul(a[0], b[0]), fmul(a[1], b[1])), fmul(a[2], b[2]))


def clamp3(v, cap):
    ln = len3(v)
    if cap < ln:
        s = fdiv(cap, ln)
        return tuple(fmul(v[i], s) for i in range(4))
    return v


def cross3(a, b, keep_w):
    """vopmula/vopmsub: xyz only, so the destination's w survives."""
    return (fsub(fmul(a[1], b[2]), fmul(a[2], b[1])),
            fsub(fmul(a[2], b[0]), fmul(a[0], b[2])),
            fsub(fmul(a[0], b[1]), fmul(a[1], b[0])),
            keep_w)


def scale4(v, s):
    return tuple(fmul(v[i], s) for i in range(4))


def add4(a, b):
    return tuple(fadd(a[i], b[i]) for i in range(4))


def mulmv3(m, v):
    """bMulMatrixVec3: w forced to 1 going in, and the product's w comes
    back out into the destination's fourth lane -- it writes four floats,
    not three, so the w lane is a computed value and not a leftover."""
    return BV.rowmul((v[0], v[1], v[2], f32(1.0)), m)


# -------------------------------------------------------------- the object

def calculate_inertia_tensor(rb):
    rb.mass = rb.rbi["mass"]
    rb.massinv = fdiv(f32(1.0), rb.rbi["mass"])
    rb.Ibi = BV.bInvertMatrix(rb.rbi["I"])


def rb_init(rb, ri):
    z = f32(0.0)
    rb.vtable = VT_RIGIDBODY
    rb.X = (z, z, z, rb.X[3])
    rb.rbi = ri
    rb.R = identity()
    rb.P = (z, z, z, rb.P[3])
    rb.L = (z, z, z, rb.L[3])
    rb.mdf = z
    rb.V = (z, z, z, rb.V[3])
    rb.W = (z, z, z, rb.W[3])
    rb.FA = (z, z, z, rb.FA[3])
    rb.MA = (z, z, z, rb.MA[3])
    rb.maxmz = z
    rb.speedlim = z
    rb.ishp = 0
    rb.catchup = f32(1.0)
    rb.md = 1
    calculate_inertia_tensor(rb)


def apply_force(rb, f, at):
    v = clamp3(f, C_MAX_FORCE)
    rb.FA = add4(rb.FA, v)
    # The moment is taken from the *unclamped* force.
    m = clamp3(cross3(at, f, at[3]), C_MAX_MOMENT)
    rb.MA = add4(rb.MA, m)


def apply_impulse(rb, j, at, scale=None):
    v = clamp3(j, C_MAX_IMPULSE)
    rb.P = add4(rb.P, v)
    # ...and here from the clamped one.
    m = clamp3(cross3(at, v, at[3]), C_MAX_ANG_IMPULSE)
    if scale is not None:
        m = scale4(m, scale)
    rb.L = add4(rb.L, m)


def world_inertia_inv(rb):
    rt = BV.bTransposeMatrix(rb.R)
    t1 = BV.bMulMatrix(rb.R, rb.Ibi)
    return BV.bMulMatrix(t1, rt)


def set_state(rb, x, r, p, omega):
    rb.X = x
    rb.R = [tuple(row) for row in r]
    rb.P = scale4(p, rb.mass)

    ib = identity()
    ib = setrow(ib, 0, (fdiv(f32(1.0), rb.Ibi[0][0]),) + ib[0][1:])
    ib = setrow(ib, 1, (ib[1][0], fdiv(f32(1.0), rb.Ibi[1][1])) + ib[1][2:])
    ib = setrow(ib, 2, ib[2][:2] + (fdiv(f32(1.0), rb.Ibi[2][2]), ib[2][3]))

    rt = BV.bTransposeMatrix(rb.R)
    t1 = BV.bMulMatrix(rb.R, ib)
    t2 = BV.bMulMatrix(t1, rt)
    rb.L = mulmv3(t2, omega)


def star_matrix(w, m):
    o = []
    for i in range(3):
        u = m[i]
        o.append((fadd(fmul(fneg(w[2]), u[1]), fmul(w[1], u[2])),
                  fsub(fmul(w[2], u[0]), fmul(w[0], u[2])),
                  fadd(fmul(fneg(w[1]), u[0]), fmul(w[0], u[1])),
                  f32(0.0)))
    o.append((f32(0.0), f32(0.0), f32(0.0), f32(1.0)))
    return o


def compute_auxiliaries(rb):
    rb.V = scale4(rb.P, rb.massinv)
    iw = world_inertia_inv(rb)
    rb.W = mulmv3(iw, rb.L)
    if rb.mdf < 0.0:
        rb.mdf = f32(0.0)
    rb.M = [rb.R[0], rb.R[1], rb.R[2], rb.X[:3] + (f32(1.0),)]
    z = f32(0.0)
    rb.FA = (z, z, z, z)
    rb.MA = (z, z, z, z)
    grav = (z, z, fmul(fneg(C_GRAVITY), rb.mass), z)
    apply_force(rb, grav, (z, z, z, z))


def get_derivative(rb, out):
    out = list(out)
    slope = f32(0.0)

    if rb.speedlim != 0.0:
        limit = fadd(fmul(rb.speedlim, rb.catchup), C_LIMIT_BASE)
        if rb.ishp != 0:
            limit = fmul(limit, C_HP_BONUS)

        slope = rb.R[0][2]
        if 0.0 < slope:
            if C_UPHILL_CLAMP < slope:
                slope = C_UPHILL_CLAMP
            k = fsub(f32(1.0),
                     fdiv(fmul(fsub(f32(1.0), C_UPHILL_FLOOR), slope),
                          C_UPHILL_CLAMP))
            limit = fmul(limit, k)
        else:
            slope = fneg(slope)
            if C_DOWNHILL_CLAMP < slope:
                slope = C_DOWNHILL_CLAMP
            k = fadd(fdiv(fmul(fsub(C_DOWNHILL_CEIL, f32(1.0)), slope),
                          C_DOWNHILL_CLAMP), f32(1.0))
            limit = fmul(limit, k)

        planar = fmul(fsqrt(fadd(fmul(rb.V[0], rb.V[0]),
                                 fmul(rb.V[1], rb.V[1]))), C_SPEED_SCALE)

        if limit < planar and 0.0 < dot3(rb.R[0], rb.FA):
            rt = BV.bTransposeMatrix(rb.R)
            local = list(mulmv3(rt, rb.FA))
            brake = fmul(fneg(slope), C_BRAKE_GAIN)
            if C_BRAKE_FLOOR < brake:
                brake = C_BRAKE_FLOOR
            local[0] = brake
            rb.FA = mulmv3(rb.R, tuple(local))

    for i in range(4):
        out[0 + i] = rb.V[i]
    rd = star_matrix(rb.W, rb.R)
    for r in range(4):
        for c in range(4):
            out[4 + r * 4 + c] = rd[r][c]
    for i in range(4):
        out[20 + i] = rb.FA[i]
    for i in range(4):
        out[24 + i] = rb.MA[i]

    spin = len3(rb.W)
    d = fneg(EN.table_get_value(ANGDAMP, spin))
    t = scale4(rb.L, d)
    for i in range(4):
        out[24 + i] = fadd(out[24 + i], t[i])

    speed = len3(rb.V)
    damp = fdiv(speed, C_DAMP_SPEED_DIV)
    spin = fdiv(spin, C_DAMP_SPIN_DIV)
    if damp < spin:
        damp = spin
    damp = EN.table_get_value(MOTION, damp)
    out[28] = C_DAMP_RISE if rb.mdf < damp else fneg(C_DAMP_FALL)

    if rb.md != 0:
        t = scale4(rb.L, fmul(fneg(C_DAMP_L_GAIN), rb.mdf))
        for i in range(4):
            out[24 + i] = fadd(out[24 + i], t[i])
        t = scale4(rb.P, fmul(fneg(C_DAMP_P_GAIN), rb.mdf))
        for i in range(4):
            out[20 + i] = fadd(out[20 + i], t[i])

    # Reads MomentAccumulator.z, not the Ldot.z it has been writing.
    if rb.maxmz != 0.0:
        mz = rb.MA[2]
        if rb.maxmz < mz:
            out[26] = rb.maxmz
        else:
            lo = fneg(rb.maxmz)
            if mz < lo:
                out[26] = lo

    return out


# ------------------------------------------------------------- scenarios

def s_ctor():
    emit("[ctor]")
    ri = make_info(1450.0, 900.0, 3200.0, 3600.0, 0.0)
    rb = RB()
    for k in range(2):
        dirty(rb, 1000.0 if k else 0.0)
        rb_init(rb, ri)
        emit("run %d returns this 1" % k)
        emit("run %d rbi 1" % k)
        dump("b" if k else "a", rb)

    emit("pc init vtable %08x" % VT_PHYSICSCOMPONENT)
    emit("pc fini vtable %08x" % VT_PHYSICSCOMPONENT)
    emit("rb fini vtable %08x" % VT_PHYSICSCOMPONENT)
    emit("rb fini rbi 1")


def s_inertia():
    emit("[inertia]")
    M = [1450.0, 1.0, 2.5]
    OD = [0.0, 0.0, 120.0]
    for k in range(3):
        ri = make_info(M[k], 900.0 + 10.0 * k, 3200.0, 3600.0, OD[k])
        rb = RB()
        dirty(rb, 0.0)
        rb.rbi = ri
        calculate_inertia_tensor(rb)
        emit("case %d" % k)
        pf("mass", rb.mass)
        pf("massinv", rb.massinv)
        pm("Ibi", rb.Ibi)
        pf("moiz", fdiv(f32(1.0), rb.Ibi[2][2]))
        pv("cog-after-null", rb.cog)
        rb.cog = vec(3.5 + k)
        pv("cog-after-set", rb.cog)


def fresh(mass, ix, iy, iz):
    ri = make_info(mass, ix, iy, iz, 0.0)
    rb = RB()
    rb_init(rb, ri)
    return rb


def s_setstate():
    emit("[setstate]")
    ANG = [(0.0, 0.0, 0.0, 0.0), (0.25, -0.5, 1.5, 99.0),
           (-3.0, 2.0, -1.0, -99.0)]
    for k in range(3):
        rb = fresh(1450.0, 900.0, 3200.0, 3600.0)
        x = vec(5.0 + k)
        p = vec(-2.0 + k)
        w = tuple(f32(v) for v in ANG[k])
        r = identity()
        r = setrow(r, 0, (f32(0.8),
                          fadd(f32(0.6), fmul(f32(0.1), f32(k))),
                          r[0][2], r[0][3]))
        r = setrow(r, 1, (f32(-0.6), f32(0.8), r[1][2], r[1][3]))
        r = setrow(r, 2, r[2][:2]
                   + (fadd(f32(1.0), fmul(f32(0.25), f32(k))),
                      r[2][3]))
        r = setrow(r, 3, (f32(7.0), f32(-3.0), f32(2.0), r[3][3]))
        set_state(rb, x, r, p, w)
        emit("case %d" % k)
        pv("X", rb.X)
        pm("R", rb.R)
        pv("P", rb.P)
        pv("L", rb.L)


FC = [
    ((10.0, -20.0, 30.0, 0.5), (1.0, 2.0, -0.5, 0.25)),
    ((900.0, 800.0, 700.0, -1.5), (0.1, 0.2, 0.3, -2.0)),
    ((0.0, 0.0, 0.0, 3.0), (4.0, 5.0, 6.0, 7.0)),
    ((-5.0, 0.5, 0.0, 0.0), (0.0, 0.0, 0.0, 0.0)),
    ((2000.0, -3000.0, 500.0, 9.0), (-3.0, 8.0, -2.5, 1.0)),
    # 4096 squared is exactly 2^24, so the other two squares straddle the
    # last representable unit and the two bracketings of the sum of squares
    # differ by two ulps. This is what makes len3's association visible.
    ((4096.0, 1.0, 1.5, 0.5), (2.0, -1.0, 0.5, 1.0)),
]


def s_apply():
    emit("[apply]")
    for k in range(6):
        rb = fresh(1450.0, 900.0, 3200.0, 3600.0)
        f = tuple(f32(v) for v in FC[k][0])
        at = tuple(f32(v) for v in FC[k][1])
        emit("case %d" % k)

        rb.FA = vec(1.0)
        rb.MA = vec(-1.0)
        apply_force(rb, f, at)
        pv("force.FA", rb.FA)
        pv("force.MA", rb.MA)

        rb.FA = vec(1.0)
        rb.MA = vec(-1.0)
        rb.R = setrow(rb.R, 0, (f32(0.6), f32(0.8)) + rb.R[0][2:])
        rb.R = setrow(rb.R, 1, (f32(-0.8), f32(0.6)) + rb.R[1][2:])
        rb.R = setrow(rb.R, 3, (f32(11.0), f32(-4.0)) + rb.R[3][2:])
        wf = mulmv3(rb.R, f)
        wat = mulmv3(rb.R, at)
        apply_force(rb, wf, wat)
        pv("frame.FA", rb.FA)
        pv("frame.MA", rb.MA)

        rb.MA = vec(2.0)
        rb.MA = add4(rb.MA, f)
        pv("moment.MA", rb.MA)

        rb.P = vec(3.0)
        rb.L = vec(-3.0)
        apply_impulse(rb, f, at)
        pv("imp.P", rb.P)
        pv("imp.L", rb.L)

        rb.P = vec(3.0)
        rb.L = vec(-3.0)
        apply_impulse(rb, f, at, f32(0.375))
        pv("scaled.P", rb.P)
        pv("scaled.L", rb.L)


def s_test_impulse():
    emit("[test-impulse]")
    for k in range(6):
        rb = fresh(1450.0 + 100.0 * k, 900.0, 3200.0, 3600.0)
        j = tuple(f32(v) for v in FC[k][0])
        at = tuple(f32(v) for v in FC[k][1])
        rb.P = vec(12.0)
        rb.L = vec(-7.0)
        rb.V = vec(0.5)
        rb.W = vec(-0.25)
        rb.R = setrow(rb.R, 0, (f32(0.6), f32(0.8)) + rb.R[0][2:])
        rb.R = setrow(rb.R, 1, (f32(-0.8), f32(0.6)) + rb.R[1][2:])

        ov = list(vec(77.0))
        m = cross3(at, j, at[3])
        p = add4(rb.P, j)
        l = add4(rb.L, m)
        # Three scalar stores: outV's w is left as the caller had it.
        for i in range(3):
            ov[i] = fmul(p[i], rb.massinv)
        iw = world_inertia_inv(rb)
        ow = mulmv3(iw, l)

        emit("case %d" % k)
        pv("outV", tuple(ov))
        pv("outW", ow)
        pf("energy", fadd(fmul(dot3(rb.P, rb.V), f32(0.5)),
                          fmul(dot3(rb.L, rb.W), f32(0.5))))
        v2 = scale4(p, rb.massinv)
        w2 = mulmv3(world_inertia_inv(rb), l)
        pf("testenergy", fadd(fmul(dot3(p, v2), f32(0.5)),
                              fmul(dot3(l, w2), f32(0.5))))
        pv("P-unchanged", rb.P)
        pv("L-unchanged", rb.L)


def s_star():
    emit("[star]")
    W = [(0.0, 0.0, 0.0, 0.0), (1.0, 0.0, 0.0, 5.0),
         (0.25, -1.5, 3.0, -5.0), (-2.0, 0.5, -0.125, 0.0)]
    for k in range(4):
        m = mat(1.0 + k * 0.5)
        w = tuple(f32(v) for v in W[k])
        emit("case %d" % k)
        pm("star", star_matrix(w, m))


def s_aux():
    emit("[aux]")
    MDF = [0.25, -0.5, 0.0]
    for k in range(3):
        rb = fresh(1450.0, 900.0, 3200.0, 3600.0)
        rb.X = vec(3.0)
        rb.P = vec(100.0 * (k + 1))
        rb.L = vec(-50.0 * (k + 1))
        rb.mdf = f32(MDF[k])
        rb.R = setrow(rb.R, 0, (f32(0.6), f32(0.8)) + rb.R[0][2:])
        rb.R = setrow(rb.R, 1, (f32(-0.8), f32(0.6)) + rb.R[1][2:])
        rb.R = setrow(rb.R, 3, (f32(2.0), f32(3.0)) + rb.R[3][2:])
        rb.FA = vec(40.0)
        rb.MA = vec(60.0)
        rb.M = mat(700.0)
        compute_auxiliaries(rb)
        emit("case %d" % k)
        pv("V", rb.V)
        pv("W", rb.W)
        pm("M", rb.M)
        pf("mdf", rb.mdf)
        pv("FA", rb.FA)
        pv("MA", rb.MA)
        pv("FA-after-stubs", rb.FA)


DC = [
    (0.0, 1.0, 0.0, 0.0, 0.20, 0, 0, 1, 2, 3, 10, 20, 30, 0.1, 0.2, 0.3),
    (0.0, 1.0, 50.0, 0.5, 0.20, 0, 1, 1, 2, 3, 10, 20, 30, 0.1, 0.2, 0.3),
    (30.0, 1.0, 0.0, 0.0, 0.20, 0, 0, 40, 10, 0, 90, 10, -5, 1.0, 0.0, 0.0),
    (30.0, 1.0, 0.0, 0.0, 0.20, 1, 0, 40, 10, 0, 90, 10, -5, 1.0, 0.0, 0.0),
    (30.0, 2.5, 0.0, 0.0, -0.40, 0, 0, 40, 10, 0, 90, 10, -5, 2.0, 3.0, 1.0),
    (30.0, 1.0, 0.0, 0.0, 0.60, 0, 0, 40, 10, 0, 90, 10, -5, 0.0, 0.0, 0.0),
    (30.0, 1.0, 0.0, 0.0, 0.00, 0, 0, 40, 10, 0, 90, 10, -5, 5.0, 5.0, 5.0),
    (30.0, 1.0, 0.0, 0.0, 0.20, 0, 0, 40, 10, 0, -90, 10, -5, 1.0, 0.0, 0.0),
    (200.0, 1.0, 0.0, 0.0, 0.20, 0, 0, 1, 1, 0, 90, 10, -5, 0.5, 0.5, 0.5),
    (30.0, 1.0, 12.0, 0.9, 0.20, 0, 1, 40, 10, 0, 90, 10, -5, 3.0, 1.0, 2.0),
    (0.0, 1.0, 4.0, 0.1, 0.20, 0, 1, 1, 1, 1, 10, 20, -99, 0.0, 0.0, 0.0),
    (0.0, 1.0, 4.0, -0.2, 0.20, 0, 0, 1, 1, 1, 10, 20, 99, 20.0, 0.0, 0.0),
    # 14.445 m/s scales to 32.30, between the flat limit of 31.90 and the
    # 32.86 the HP bonus buys. The pair is the only place the bonus decides
    # whether the brake fires rather than merely how far under it the car is.
    (30.0, 1.0, 0.0, 0.0, 0.00, 0, 0, 14.445, 0, 0, 90, 10, -5, 1.0, 0.0, 0.0),
    (30.0, 1.0, 0.0, 0.0, 0.00, 1, 0, 14.445, 0, 0, 90, 10, -5, 1.0, 0.0, 0.0),
    # Climbing at 5 m/s: 31.30 along the ground, 33.24 through the air, one
    # either side of the limit. The only case that sees the missing z term.
    (30.0, 1.0, 0.0, 0.0, 0.00, 0, 0, 14.0, 0, 5.0, 90, 10, -5, 1.0, 0.0, 0.0),
]


def s_derivative():
    emit("[derivative]")
    for k, c in enumerate(DC):
        (sl, cu, mz, mdf, rzz, hp, md,
         vx, vy, vz, fax, fay, faz, wx, wy, wz) = c
        rb = fresh(1450.0, 900.0, 3200.0, 3600.0)
        rb.speedlim = f32(sl)
        rb.catchup = f32(cu)
        rb.maxmz = f32(mz)
        rb.mdf = f32(mdf)
        rb.ishp = hp
        rb.md = md
        rb.R = setrow(rb.R, 0, (f32(0.6), f32(0.8), f32(rzz), rb.R[0][3]))
        rb.R = setrow(rb.R, 1, (f32(-0.8), f32(0.6)) + rb.R[1][2:])
        rb.R = setrow(rb.R, 3, (f32(4.0), f32(-2.0)) + rb.R[3][2:])
        rb.V = (f32(vx), f32(vy), f32(vz), f32(0.5))
        rb.W = (f32(wx), f32(wy), f32(wz), f32(-0.5))
        rb.FA = (f32(fax), f32(fay), f32(faz), f32(1.5))
        rb.MA = (f32(2.0), f32(-3.0), f32(faz * 1.5), f32(-2.5))
        rb.P = vec(500.0)
        rb.L = vec(-250.0)

        out = [f32(1000.0 + i) for i in range(32)]
        out = get_derivative(rb, out)
        emit("case %d returns out 1" % k)
        for i in range(32):
            emit("d[%2d] %s" % (i, g9(out[i])))
        pv("FA-after", rb.FA)


def s_state_array():
    emit("[state-array]")
    emit("getsize 32")
    emit("getstate is state 1")

    X, R, P, L, MDF = vec(1.0), mat(20.0), vec(40.0), vec(60.0), f32(80.0)
    buf = [f32(-1.0 - i) for i in range(32)]
    for i in range(4):
        buf[0 + i] = X[i]
    for r in range(4):
        for c in range(4):
            buf[4 + r * 4 + c] = R[r][c]
    for i in range(4):
        buf[20 + i] = P[i]
    for i in range(4):
        buf[24 + i] = L[i]
    buf[28] = MDF
    for i in range(32):
        emit("get[%2d] %s" % (i, g9(buf[i])))

    buf = [f32(500.0 + i) for i in range(32)]
    pv("X", tuple(buf[0:4]))
    pm("R", [tuple(buf[4 + r * 4:8 + r * 4]) for r in range(4)])
    pv("P", tuple(buf[20:24]))
    pv("L", tuple(buf[24:28]))
    pf("mdf", buf[28])

    v = vec(7.0)
    m = mat(300.0)
    pv("set_l", v)
    pv("set_p", v)
    pv("set_x", v)
    pm("set_r", m)
    emit("set_md -3")
    emit("set_ishp 300")
    pf("set_catchup", f32(1.75))
    pf("set_speedlim", f32(44.5))
    pf("set_maxmz", f32(-9.25))

    for name, off in (("Ibi", 288), ("FA", 240), ("cog", 352),
                      ("Matrix", 176), ("L", 112), ("W", 160), ("R", 32),
                      ("P", 96), ("V", 144), ("X", 16)):
        emit("ptr %s %d" % (pad(name, 10), off + 2 * SLACK))
    pf("massinv", fdiv(f32(1.0), f32(1450.0)))
    pf("mass", f32(1450.0))


SCENARIOS = [s_layout, s_ctor, s_inertia, s_setstate, s_apply,
             s_test_impulse, s_star, s_aux, s_derivative, s_state_array]


def model():
    del OUT[:]
    for s in SCENARIOS:
        s()
    return list(OUT)


# ----------------------------------------------------------------- harness

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


MUTATIONS = [
    # -- layout -------------------------------------------------------------
    ("rb-vtable-first", RH,
     "    uint32_t  pNext;                //   0  bNode, owned by the list",
     "    uint32_t  _vt_first;" + NL
     + "    uint32_t  pNext;                //   0"),
    ("rb-links-are-pointers", RH,
     "    uint32_t  pNext;                //   0  bNode, owned by the list"
     + NL + "    uint32_t  pPrev;                //   4",
     "    void     *pNext;" + NL + "    void     *pPrev;"),
    ("rb-vel-angvel-swapped", RH,
     "    bVector4  Velocity;             // 144  auxiliary" + NL
     + "    bVector4  AngularVelocity;      // 160  auxiliary",
     "    bVector4  AngularVelocity;      // 144" + NL
     + "    bVector4  Velocity;             // 160"),
    ("rb-mass-swapped", RH,
     "    float     Mass;                 // 280" + NL
     + "    float     Mass_inv;             // 284",
     "    float     Mass_inv;             // 280" + NL
     + "    float     Mass;                 // 284"),
    ("rb-ishp-is-byte", RH,
     "    int32_t   IsHP;                 // 276  a bool, stored as a word",
     "    int8_t    IsHP;                 // 276" + NL
     + "    uint8_t   _hpad[3];"),
    ("rb-limiters-swapped", RH,
     "    float     MaxMomentZ;           // 368" + NL
     + "    float     SpeedLimiter;         // 372",
     "    float     SpeedLimiter;         // 368" + NL
     + "    float     MaxMomentZ;           // 372"),
    ("rb-state-pl-swapped", RH,
     "    bVector4 P;                   //  80  linear momentum" + NL
     + "    bVector4 L;                   //  96  angular momentum",
     "    bVector4 L;                   //  80" + NL
     + "    bVector4 P;                   //  96"),
    ("rb-info-dims-shifted", RH,
     "    float    Ydim;          //  8" + NL + "    float    Zdim;          // 12",
     "    float    Zdim;          //  8" + NL + "    float    Ydim;          // 12"),
    # Inherited from cartypeinfo_check when RigidBodyInfo moved into this
    # header: the tensor put where Zdim is, which shifts every field after
    # it by four and is exactly the slip a hand-transcribed layout makes.
    ("rb-info-tensor-at-12", RH,
     "    float    Zdim;          // 12" + NL
     + "    bMatrix4 InertiaTensor; // 16",
     "    bMatrix4 InertiaTensor; // 12" + NL
     + "    float    Zdim;          // 76"),
    ("rb-getsize-29", RH,
     "#define RIGIDBODY_STATE_FLOATS 32",
     "#define RIGIDBODY_STATE_FLOATS 29"),

    # -- the constants ------------------------------------------------------
    ("rb-gravity-9-81", RH,
     "#define RIGIDBODY_GRAVITY          9.80000019f",
     "#define RIGIDBODY_GRAVITY          9.81000042f"),
    ("rb-limitbase-2", RH,
     "#define RIGIDBODY_LIMIT_BASE       1.89999998f",
     "#define RIGIDBODY_LIMIT_BASE       2.0f"),
    ("rb-spdscale-mph", RH,
     "#define RIGIDBODY_SPEED_SCALE      2.23602486f",
     "#define RIGIDBODY_SPEED_SCALE      2.23693633f"),
    ("rb-maxforce-1000", RH,
     "#define RIGIDBODY_MAX_FORCE     1200.0f",
     "#define RIGIDBODY_MAX_FORCE     1000.0f"),
    ("rb-maxmoment-is-impulse", RH,
     "#define RIGIDBODY_MAX_MOMENT     100.0f",
     "#define RIGIDBODY_MAX_MOMENT      10.0f"),
    ("rb-damp-gains-swapped", RH,
     "#define RIGIDBODY_DAMP_L_GAIN      2.0f         // gp-20500" + NL
     + "#define RIGIDBODY_DAMP_P_GAIN      8.0f         // gp-20504",
     "#define RIGIDBODY_DAMP_L_GAIN      8.0f" + NL
     + "#define RIGIDBODY_DAMP_P_GAIN      2.0f"),
    ("rb-vtables-swapped", RH,
     "#define RIGIDBODY_VTABLE        0x002987e8u" + NL
     + "#define PHYSICSCOMPONENT_VTABLE 0x00298728u",
     "#define RIGIDBODY_VTABLE        0x00298728u" + NL
     + "#define PHYSICSCOMPONENT_VTABLE 0x002987e8u"),

    # -- the tables ---------------------------------------------------------
    ("rb-angdamp-span-1", RC,
     "               RigidBodyAngularMomentumDampingValues, 6, 0.0f, 10.0f);",
     "               RigidBodyAngularMomentumDampingValues, 6, 0.0f, 1.0f);"),
    ("rb-motion-span-10", RC,
     "               RigidBodyMotionDampingValues, 8, 0.0f, 1.0f);",
     "               RigidBodyMotionDampingValues, 8, 0.0f, 10.0f);"),
    ("rb-tables-swapped", RC,
     "               RigidBodyAngularMomentumDampingValues, 6, 0.0f, 10.0f);",
     "               RigidBodyMotionDampingValues, 6, 0.0f, 10.0f);"),
    ("rb-energy-linear-only", RC,
     "    float ang = dot3(&rb->State.L, &rb->AngularVelocity);",
     "    float ang = dot3(&rb->State.L, &rb->Velocity);"),
    ("rb-angdamp-value", RC,
     "    0.0500000007f, 0.0500000007f, 0.25f, 0.699999988f, 2.0f, 5.0f",
     "    0.0500000007f, 0.100000001f, 0.25f, 0.699999988f, 2.0f, 5.0f"),
    ("rb-motion-last-value", RC,
     "    0.0599999987f, 0.0299999993f, 0.0149999997f, 0.0f",
     "    0.0599999987f, 0.0299999993f, 0.0149999997f, 0.00999999978f"),

    # -- the VU idioms ------------------------------------------------------
    ("rb-len3-assoc", RC,
     "    return sqrtf((xx + yy) + zz);",
     "    return sqrtf(xx + (yy + zz));"),
    ("rb-clamp-xyz-only", RC,
     "        v->z *= s;" + NL + "        v->w *= s;",
     "        v->z *= s;"),
    ("rb-clamp-inclusive", RC,
     "    if (cap < len) {",
     "    if (cap <= len) {"),
    ("rb-cross-negated", RC,
     "    float x = a->y * b->z - a->z * b->y;",
     "    float x = a->z * b->y - a->y * b->z;"),
    ("rb-cross-w-zero", RC,
     "    o->w = keep_w;",
     "    o->w = 0.0f;"),
    ("rb-add4-xyz-only", RC,
     "    o->w = a->w + b->w;",
     "    o->w = a->w;"),

    # -- the constructor ----------------------------------------------------
    ("rb-ctor-clears-w", RC,
     "    rb->State.X.x = 0.0f;" + NL + "    rb->State.X.y = 0.0f;" + NL
     + "    rb->State.X.z = 0.0f;",
     "    rb->State.X.x = 0.0f;" + NL + "    rb->State.X.y = 0.0f;" + NL
     + "    rb->State.X.z = 0.0f;" + NL + "    rb->State.X.w = 0.0f;"),
    ("rb-ctor-clears-matrix", RC,
     "    rb->MotionDamping = 1;      // in the delay slot of the call below",
     "    bIdentity(&rb->Matrix);" + NL + "    rb->MotionDamping = 1;"),
    ("rb-ctor-clears-cog", RC,
     "    rb->MotionDamping = 1;      // in the delay slot of the call below",
     "    rb->CenterOfGravity.x = 0.0f;" + NL + "    rb->MotionDamping = 1;"),
    ("rb-ctor-damping-zero", RC,
     "    rb->MotionDamping = 1;      // in the delay slot of the call below",
     "    rb->MotionDamping = 0;"),
    ("rb-ctor-catchup-zero", RC,
     "    rb->CatchUpMultiplier = 1.0f;",
     "    rb->CatchUpMultiplier = 0.0f;"),
    ("rb-fini-own-vtable", RC,
     "    physicscomponent_fini(rb);",
     "    rb->_vtable = RIGIDBODY_VTABLE;"),
    ("rb-calibrate-no-null-check", RC,
     "    if (cog == NULL)" + NL + "        return;",
     "    if (cog == NULL)" + NL + "        cog = &rb->State.X;"),

    # -- CalculateInertiaTensor / SetState ----------------------------------
    ("rb-massinv-from-rb", RC,
     "    rb->Mass_inv = 1.0f / rbi->Mass;",
     "    rb->Mass_inv = rbi->Mass;"),
    ("rb-inertia-not-inverted", RC,
     "    bInvertMatrix(&rb->I_body_inv, &rbi->InertiaTensor);",
     "    rb->I_body_inv = rbi->InertiaTensor;"),
    ("rb-setstate-p-not-scaled", RC,
     "    scale4(&rb->State.P, p, rb->Mass);",
     "    rb->State.P = *p;"),
    ("rb-setstate-full-invert", RC,
     "    bIdentity(&ibody);" + NL
     + "    ibody.v0.x = 1.0f / rb->I_body_inv.v0.x;" + NL
     + "    ibody.v1.y = 1.0f / rb->I_body_inv.v1.y;" + NL
     + "    ibody.v2.z = 1.0f / rb->I_body_inv.v2.z;",
     "    bInvertMatrix(&ibody, &rb->I_body_inv);"),
    ("rb-setstate-no-transpose", RC,
     "    bTransposeMatrix(&rt, &rb->State.R);" + NL
     + "    bMulMatrix(&t1, &rb->State.R, &ibody);",
     "    rt = rb->State.R;" + NL
     + "    bMulMatrix(&t1, &rb->State.R, &ibody);"),

    # -- the Apply family ---------------------------------------------------
    ("rb-force-moment-clamped", RC,
     "    cross3(&m, at, f, at->w);" + NL
     + "    clamp3(&m, RIGIDBODY_MAX_MOMENT);",
     "    cross3(&m, at, &v, at->w);" + NL
     + "    clamp3(&m, RIGIDBODY_MAX_MOMENT);"),
    ("rb-impulse-moment-unclamped", RC,
     "    cross3(&m, at, &v, at->w);" + NL
     + "    clamp3(&m, RIGIDBODY_MAX_ANG_IMPULSE);" + NL
     + "    add4(&rb->State.L, &rb->State.L, &m);" + NL + "}" + NL + NL
     + "void rigidbody_apply_impulse_scaled",
     "    cross3(&m, at, j, at->w);" + NL
     + "    clamp3(&m, RIGIDBODY_MAX_ANG_IMPULSE);" + NL
     + "    add4(&rb->State.L, &rb->State.L, &m);" + NL + "}" + NL + NL
     + "void rigidbody_apply_impulse_scaled"),
    ("rb-force-cross-reversed", RC,
     "    cross3(&m, at, f, at->w);",
     "    cross3(&m, f, at, at->w);"),
    ("rb-impulse-to-accumulator", RC,
     "    clamp3(&v, RIGIDBODY_MAX_IMPULSE);" + NL
     + "    add4(&rb->State.P, &rb->State.P, &v);" + NL + NL
     + "    // Here the cross",
     "    clamp3(&v, RIGIDBODY_MAX_IMPULSE);" + NL
     + "    add4(&rb->ForceAccumulator, &rb->ForceAccumulator, &v);" + NL + NL
     + "    // Here the cross"),
    ("rb-scaled-before-clamp", RC,
     "    clamp3(&m, RIGIDBODY_MAX_ANG_IMPULSE);" + NL
     + "    scale4(&m, &m, scale);       // scaled after the clamp, not before",
     "    scale4(&m, &m, scale);" + NL
     + "    clamp3(&m, RIGIDBODY_MAX_ANG_IMPULSE);"),
    ("rb-frame-no-rotate-at", RC,
     "    bMulMatrixVec3((bVector3 *)&wat, &rb->State.R, (const bVector3 *)at);",
     "    wat = *at;"),
    ("rb-testimpulse-writes-w", RC,
     "    outV->z = p.z * rb->Mass_inv;",
     "    outV->z = p.z * rb->Mass_inv;" + NL
     + "    outV->w = p.w * rb->Mass_inv;"),
    ("rb-energy-halves-together", RC,
     "    return lin * 0.5f + ang * 0.5f;",
     "    return (lin + ang) * 0.5f;"),

    # -- VectorStarMatrix ---------------------------------------------------
    ("rb-star-transposed", RC,
     "        o->x = -w->z * u->y + w->y * u->z;" + NL
     + "        o->y =  w->z * u->x - w->x * u->z;" + NL
     + "        o->z = -w->y * u->x + w->x * u->y;",
     "        o->x =  w->z * u->y - w->y * u->z;" + NL
     + "        o->y = -w->z * u->x + w->x * u->z;" + NL
     + "        o->z =  w->y * u->x - w->x * u->y;"),
    ("rb-star-w-not-cleared", RC,
     "        o->w = 0.0f;" + NL + "    }",
     "        o->w = u->w;" + NL + "    }"),
    ("rb-star-row3-zero", RC,
     "    out->v3.w = 1.0f;",
     "    out->v3.w = 0.0f;"),
    ("rb-star-four-rows", RC,
     "    for (i = 0; i < 3; i++) {",
     "    for (i = 0; i < 2; i++) {"),

    # -- ComputeAuxiliaries -------------------------------------------------
    ("rb-aux-mdf-not-floored", RC,
     "    if (rb->State.MotionDampingFactor < 0.0f)",
     "    if (rb->State.MotionDampingFactor < -1.0f)"),
    ("rb-aux-matrix-w-copied", RC,
     "    rb->Matrix.v3 = rb->State.X;" + NL + "    rb->Matrix.v3.w = 1.0f;",
     "    rb->Matrix.v3 = rb->State.X;"),
    ("rb-aux-no-gravity", RC,
     "    rigidbody_apply_force(rb, &grav, &at);",
     "    (void)grav; (void)at;"),
    ("rb-aux-gravity-positive", RC,
     "    grav.z = -RIGIDBODY_GRAVITY * rb->Mass;",
     "    grav.z = RIGIDBODY_GRAVITY * rb->Mass;"),
    ("rb-aux-keeps-accumulators", RC,
     "    rb->ForceAccumulator.x = 0.0f;" + NL
     + "    rb->ForceAccumulator.y = 0.0f;" + NL
     + "    rb->ForceAccumulator.z = 0.0f;" + NL
     + "    rb->ForceAccumulator.w = 0.0f;" + NL
     + "    rb->MomentAccumulator = rb->ForceAccumulator;",
     "    rb->MomentAccumulator = rb->ForceAccumulator;"),
    ("rb-aux-velocity-from-l", RC,
     "    scale4(&rb->Velocity, &rb->State.P, rb->Mass_inv);",
     "    scale4(&rb->Velocity, &rb->State.L, rb->Mass_inv);"),

    # -- GetDerivative ------------------------------------------------------
    ("rb-deriv-limiter-always", RC,
     "    if (rb->SpeedLimiter != 0.0f) {",
     "    if (rb->SpeedLimiter >= 0.0f) {"),
    ("rb-deriv-hp-always", RC,
     "        if (rb->IsHP != 0)" + NL
     + "            limit *= RIGIDBODY_HP_BONUS;",
     "        limit *= RIGIDBODY_HP_BONUS;"),
    ("rb-deriv-slope-from-v1", RC,
     "        slope = rb->State.R.v0.z;",
     "        slope = rb->State.R.v1.z;"),
    ("rb-deriv-slope-arms-swapped", RC,
     "        if (0.0f < slope) {",
     "        if (slope < 0.0f) {"),
    ("rb-deriv-planar-has-z", RC,
     "        planar = sqrtf(rb->Velocity.x * rb->Velocity.x" + NL
     + "                       + rb->Velocity.y * rb->Velocity.y)",
     "        planar = sqrtf(rb->Velocity.x * rb->Velocity.x" + NL
     + "                       + rb->Velocity.y * rb->Velocity.y"
     + " + rb->Velocity.z * rb->Velocity.z)"),
    ("rb-deriv-dot-sign", RC,
     "            && 0.0f < dot3(&rb->State.R.v0, &rb->ForceAccumulator)) {",
     "            && dot3(&rb->State.R.v0, &rb->ForceAccumulator) < 0.0f) {"),
    ("rb-deriv-brake-no-floor", RC,
     "            if (RIGIDBODY_BRAKE_FLOOR < brake)" + NL
     + "                brake = RIGIDBODY_BRAKE_FLOOR;",
     "            if (brake < RIGIDBODY_BRAKE_FLOOR)" + NL
     + "                brake = RIGIDBODY_BRAKE_FLOOR;"),
    ("rb-deriv-brake-to-y", RC,
     "            local.x = brake;",
     "            local.y = brake;"),
    ("rb-deriv-angdamp-positive", RC,
     "        float d = -table_get_value(&RigidBodyAngularMomentumDampingTable,",
     "        float d = table_get_value(&RigidBodyAngularMomentumDampingTable,"),
    ("rb-deriv-angdamp-on-w", RC,
     "    spin = len3(&rb->AngularVelocity);",
     "    spin = len3(&rb->Velocity);"),
    ("rb-deriv-damp-min-not-max", RC,
     "    if (damp < spin)" + NL + "        damp = spin;",
     "    if (spin < damp)" + NL + "        damp = spin;"),
    ("rb-deriv-rise-fall-swapped", RC,
     "    out[28] = (rb->State.MotionDampingFactor < damp)" + NL
     + "              ? RIGIDBODY_DAMP_RISE : -RIGIDBODY_DAMP_FALL;",
     "    out[28] = (rb->State.MotionDampingFactor < damp)" + NL
     + "              ? -RIGIDBODY_DAMP_FALL : RIGIDBODY_DAMP_RISE;"),
    ("rb-deriv-maxmz-from-ldot", RC,
     "        float mz = rb->MomentAccumulator.z;",
     "        float mz = out[26];"),
    ("rb-deriv-maxmz-zero-clamps", RC,
     "    if (rb->MaxMomentZ != 0.0f) {",
     "    if (rb->MaxMomentZ >= 0.0f) {"),
    ("rb-deriv-xdot-is-p", RC,
     "    *xdot = rb->Velocity;",
     "    *xdot = rb->State.P;"),
    ("rb-deriv-star-args-swapped", RC,
     "    VectorStarMatrix(rdot, &rb->AngularVelocity, &rb->State.R);",
     "    VectorStarMatrix(rdot, &rb->Velocity, &rb->State.R);"),

    # -- the state array ----------------------------------------------------
    ("rb-getstate-skips-mdf", RC,
     "    out[28] = rb->State.MotionDampingFactor;",
     "    out[28] = 0.0f;"),
    ("rb-setstate-array-offset", RC,
     "    rb->State.L = *(const bVector4 *)(in + 24);",
     "    rb->State.L = *(const bVector4 *)(in + 20);"),
    ("rb-moiz-from-v0", RC,
     "    return 1.0f / rb->I_body_inv.v2.z;",
     "    return 1.0f / rb->I_body_inv.v0.x;"),
]

# Two survivors that no transcript can catch, because nothing distinguishes
# them at the level of IEEE arithmetic.
#
# `rb-clamp-inclusive` turns `cap < len` into `cap <= len`, so a vector
# whose length is exactly the cap gets scaled where the image leaves it
# alone. The scale is `cap / len`, and when `len == cap` that division is
# exactly 1.0 for every finite non-zero cap -- IEEE division of a value by
# itself is exact. Multiplying all four lanes by exactly 1.0 returns each
# one unchanged, sign of zero included. The extra multiply is the identity,
# so the two spellings agree on every input, not merely on the ones here.
#
# `rb-energy-halves-together` turns `lin * 0.5f + ang * 0.5f` into
# `(lin + ang) * 0.5f`. Halving is exact: 0.5 is a power of two, so
# `x * 0.5f` only decrements the exponent and the mantissa is untouched.
# Rounding therefore commutes with the scaling, and
# `fl(fl(lin/2) + fl(ang/2)) == fl(fl(lin + ang) / 2)` for all normal
# inputs. The identity does fail once halving itself becomes lossy, in the
# subnormal range below about 1e-38, but an energy that small is not a
# number this object can produce -- the momenta would have to be near zero
# and their squares nearer still.
EQUIVALENT = ["rb-clamp-inclusive", "rb-energy-halves-together"]
EXPECT_MISSING = []


# The write, its OneDrive retry, and the journal that lets a killed pass be
# recovered from are all hostbuild's.
write_source = hostbuild.write_source


def mutate_pass():
    base_model = model()
    caught = 0
    survived = []
    missing = []

    for name, rel, before, after in MUTATIONS:
        path = ROOT / rel
        text = path.read_text(encoding="utf-8", newline="")
        crlf = "\r\n" in text
        probe = before.replace(NL, "\r\n") if crlf else before
        repl = after.replace(NL, "\r\n") if crlf else after
        if probe not in text:
            missing.append(name)
            print("  %-32s PATTERN NOT FOUND" % name)
            continue
        try:
            write_source(path, text.replace(probe, repl, 1))
            with tempfile.TemporaryDirectory() as tmp:
                try:
                    exe = hostbuild.build(tmp, SOURCES, name="rigidbody_test")
                except SystemExit:
                    print("  %-32s did not compile (caught)" % name)
                    caught += 1
                    continue
                out = Path(tmp) / "m.txt"
                if run_harness(exe, out) != 0:
                    print("  %-32s crashed the harness (caught)" % name)
                    caught += 1
                    continue
                n = diff(base_model, out.read_text().splitlines(), quiet=True)
                if n:
                    print("  %-32s caught, %d lines" % (name, n))
                    caught += 1
                elif name in EQUIVALENT:
                    print("  %-32s survived, equivalent by construction"
                          % name)
                else:
                    print("  %-32s SURVIVED" % name)
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
    unexpected = [m for m in missing if m not in EXPECT_MISSING]
    # A pattern that is not found is dropped from the denominator above, so
    # without this the tally line reads clean while a mutation never ran.
    if missing:
        print("%d PATTERN NOT FOUND -- the tally above is over %d of %d"
              % (len(missing), len(real), len(MUTATIONS)))
    print("%d mutations, %d caught, %d equivalent, %d unexplained"
          % (len(real), caught, len(EQUIVALENT), len(holes)))
    return 1 if (holes or unexpected) else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mutate", action="store_true")
    ap.add_argument("--dump", metavar="DIR")
    args = ap.parse_args()

    if args.mutate:
        sys.exit(mutate_pass())

    lines = model()
    with tempfile.TemporaryDirectory() as tmp:
        exe = hostbuild.build(tmp, SOURCES, name="rigidbody_test")
        out = Path(tmp) / "harness.txt"
        run_harness(exe, out)
        harness = out.read_text().splitlines()

        if args.dump:
            d = Path(args.dump)
            d.mkdir(parents=True, exist_ok=True)
            (d / "model.txt").write_text(NL.join(lines) + NL)
            (d / "harness.txt").write_text(NL.join(harness) + NL)
            print("wrote %s" % d)

    n = diff(lines, harness)
    print("%d scenarios, %d lines, %d differ" % (len(SCENARIOS), len(lines), n))
    sys.exit(1 if n else 0)


if __name__ == "__main__":
    main()
