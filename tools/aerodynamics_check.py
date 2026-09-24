"""Cross-check 3DS Files/source/aerodynamics.c against a model of the image.

    3DS Files/source/aerodynamics.{c,h}   Aerodynamics.obj, 0x001a4b58

Aerodynamics is the drag and the two downforces on a car body: three
ApplyForce calls a frame, and the downforce total handed on to the
suspensions. It has no state and no vtable, so the transcript is what it
does to a RigidBody's two accumulators, what it writes through `out`, and
the six floats of the record.

The model below is written from the listing. The RigidBody side --
ApplyForce's clamps, its moment taken from the *unclamped* force, and
bMulMatrixVec3's w lane -- is rigidbody_check's and bvector_check's,
imported rather than written again, so the three are checked against the
same model of the calls they make. ApplyForceInFrame had no checker of
its own before this one; it is modelled here, from 0x00193170, as two
bMulMatrixVector calls (an 8-byte thunk to bMulMatrixVec3) and an
ApplyForce.

What the transcript exists to pin down:

**v is not a unit vector unless Boost is 1.** It is Velocity * (1 / s),
and s is the speed over Boost. One case has Boost 2 and its "direction"
of length 2 goes into the fourth power.

**The speed floor is strict, and so is nothing else.** `c.lt.s` against
1e-4 for the direction, `c.le.s` against 0.5 for the ground-effect arm
(twice, on two reads of GroundEffect), `c.eq.s` against 0 for which
downforce formula runs. One case sits on each boundary.

**Every force's w lane is live.** The drag is `vmulx.xyzw`, so the
velocity's w lane is scaled with the rest and lands in ForceAccumulator.w;
the application point's w lane is the moment's (vopmsub writes xyz only);
and the in-frame points get a w of R.v3.w from bMulMatrixVec3. The drag
point's w is the port's one deviation -- stack garbage in the image, 0 in
the port -- and the model follows the port there.

**The two .sdata floats are read every call.** One scenario changes them.

    python tools/aerodynamics_check.py
    python tools/aerodynamics_check.py --mutate
    python tools/aerodynamics_check.py --dump out/aerodynamics
"""
import argparse
import os
import re
import struct
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hostbuild
import bmath_check as BM
import bvector_check as BV
import rigidbody_check as RB
import physicssystem_check as PS

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

SOURCES = [
    "tools/src/aerodynamics_test.c",
    "3DS Files/source/aerodynamics.c",
    "3DS Files/source/rigidbody.c",
    "3DS Files/source/bmatrix.c",
    "3DS Files/source/table.c",
    "3DS Files/source/bvector.c",
    "3DS Files/source/bmath.c",
    "3DS Files/source/bmathtab.c",
]

AC = "3DS Files/source/aerodynamics.c"
RC = "3DS Files/source/rigidbody.c"
MC = "3DS Files/source/bmatrix.c"

ELF = BM.ELF
f32 = BV.f32
bits = BM.bits
fmul, fadd, fsub, fdiv, fneg, fsqrt = (BV.fmul, BV.fadd, BV.fsub,
                                       BV.fdiv, BV.fneg, BV.fsqrt)
insn, imm, lui_float, gp_word = PS.insn, PS.imm, PS.lui_float, PS.gp_word

PTR = 8
SLACK = PTR - 4

OP_LUI, OP_ADDIU, OP_SW, OP_LW = 0x0f, 0x09, 0x2b, 0x23
OP_LWC1, OP_SWC1, OP_LQC2 = 0x31, 0x39, 0x36


def g9(x):
    return "%.9g" % x


def fbits(x):
    return struct.unpack("<I", struct.pack("<f", f32(x)))[0]


OUT = []


def emit(s):
    OUT.append(s)


def pv(tag, v):
    emit("%s %s %s %s %s" % (tag, g9(v[0]), g9(v[1]), g9(v[2]), g9(v[3])))


# ============================================================= the image

def fields(name):
    size, rec = PS.mdebug_record(name)
    out = {}
    for m in re.finditer(r"^\s+(\w+)\s+type#\d+\s+offset=(\d+)\s+bits=32",
                         rec, re.M):
        out[m.group(1)] = int(m.group(2)) // 8
    return size, out


AERO_SIZE, AERO = fields("Aerodynamics")
INFO_SIZE, INFO = fields("AeroInfo")

# The listing reads every field at the offset the record gives it.
assert imm(0x001a4bd4, OP_LW) == AERO["AI"]              # lw v0,0(s0)
assert imm(0x001a4ba4, OP_LW) == AERO["pBody"]           # lw v0,4(s0)
assert imm(0x001a4bc8, OP_LWC1) == AERO["Boost"]
assert imm(0x001a4bcc, OP_LWC1) == AERO["Draft"]
assert imm(0x001a4be8, OP_LWC1) == AERO["Throttle"]
assert imm(0x001a4bf0, OP_LWC1) == AERO["GroundEffect"]
assert imm(0x001a4c74, OP_LWC1) == AERO["GroundEffect"]  # the reread
assert imm(0x001a4be0, OP_LWC1) == INFO["Drag"]
assert imm(0x001a4d18, OP_LWC1) == INFO["FrontDownforce"]
assert imm(0x001a4d14, OP_LWC1) == INFO["RearDownforce"]
assert imm(0x001a4d40, OP_LWC1) == INFO["FrontDownforce"]
assert imm(0x001a4d3c, OP_LWC1) == INFO["RearDownforce"]
# DoSnapshot clears 20, 8 and 16.
assert [imm(a, OP_SW) for a in (0x001a4b6c, 0x001a4b70, 0x001a4b74)] == [
    AERO["GroundEffect"], AERO["Boost"], AERO["Throttle"]]

# And the body's.
PS2_VELOCITY = imm(0x001a4ba8, OP_LQC2)    # lqc2 vf3,144(v0)
PS2_R_V0 = imm(0x001a4cb8, OP_LQC2)        # lqc2 vf3,32(v1)
PS2_R_V2Z = imm(0x001a4c60, OP_LWC1)       # lwc1 $f4,72(v1)
assert PS2_R_V2Z == PS2_R_V0 + 2 * 16 + 8

C_OFF_FACTOR_W = gp_word(0x001a4be4)       # gp-19720
C_OFF_HEIGHT_W = gp_word(0x001a4c3c)       # gp-19716
C_MIN_SPEED_W = gp_word(0x001a4c88)        # gp-29476
C_FRONT_SHARE_W = gp_word(0x001a4cfc)      # gp-29472
C_REAR_SHARE_W = gp_word(0x001a4d04)       # gp-29468
C_ONE = lui_float(0x001a4bd8)
C_GE = lui_float(0x001a4bf8)
assert C_ONE == 1.0

C_MIN_SPEED = bits(C_MIN_SPEED_W)
C_FRONT_SHARE = bits(C_FRONT_SHARE_W)
C_REAR_SHARE = bits(C_REAR_SHARE_W)

# ApplyForce's two caps, which rigidbody_check keeps as constants.
assert lui_float(0x001930ac) == RB.C_MAX_FORCE
assert lui_float(0x00193124) == RB.C_MAX_MOMENT
# ApplyForceInFrame passes the body's State.R (s3 + 32) to a thunk.
assert imm(0x00193188, OP_ADDIU) == PS2_R_V0
assert insn(0x00193658) >> 26 == 0x02                       # j
assert (insn(0x00193658) & 0x03ffffff) << 2 == 0x002427b0   # bMulMatrixVec3

FRONT_LOC = ELF.syms["FrontDownforceLocation"][0]
REAR_LOC = ELF.syms["RearDownforceLocation"][0]


def hi_lo(lui_addr, addiu_addr):
    return (((insn(lui_addr) & 0xffff) << 16)
            + imm(addiu_addr, OP_ADDIU)) & 0xffffffff


# ResolveForces pushes at those two.
assert hi_lo(0x001a4d60, 0x001a4d64) == FRONT_LOC
assert hi_lo(0x001a4d88, 0x001a4d90) == REAR_LOC


# The inlined constructor, in PhysicsCar's: Boost and Draft from $f20,
# which is `lui at,0x3f80 ; mtc1 at,$f20` a little earlier, and zero for
# the other two.
def _ctor_stores():
    f20 = lui_float(0x00135450)
    assert (insn(0x00135454) >> 21) & 0x7ff == (0x11 << 5) | 4   # mtc1
    assert (insn(0x00135454) >> 11) & 31 == 20
    got = {}
    for a in (0x00135504, 0x00135508, 0x00135514, 0x0013551c):
        w = insn(a)
        op, rt = w >> 26, (w >> 16) & 31
        if op == OP_SWC1:
            assert rt == 20, hex(a)
            got[imm(a, OP_SWC1)] = f20
        else:
            assert op == OP_SW and rt == 0, hex(a)
            got[imm(a, OP_SW)] = f32(0.0)
    return got


_CTOR = _ctor_stores()
INIT_BOOST = _CTOR[AERO["Boost"]]
INIT_DRAFT = _CTOR[AERO["Draft"]]
INIT_THROTTLE = _CTOR[AERO["Throttle"]]
INIT_GE = _CTOR[AERO["GroundEffect"]]


def static_init(mem):
    """0x001a4de8, run on a dict of address -> float: lui, addiu, mtc1
    and swc1 are all it is."""
    gpr = [0] * 32
    fpr = [0.0] * 32
    a = 0x001a4de8
    stop = None
    while stop is None or a <= stop:
        w = insn(a)
        op = w >> 26
        rs, rt = (w >> 21) & 31, (w >> 16) & 31
        if op == OP_LUI:
            gpr[rt] = (w & 0xffff) << 16
        elif op == OP_ADDIU:
            gpr[rt] = (gpr[rs] + imm(a, OP_ADDIU)) & 0xffffffff
        elif op == 0x11 and rs == 4:                     # mtc1
            fpr[(w >> 11) & 31] = bits(gpr[rt])
        elif op == OP_SWC1:
            addr = (gpr[rs] + imm(a, OP_SWC1)) & 0xffffffff
            assert addr in mem, hex(addr)
            mem[addr] = fpr[rt]
        elif op == 0 and w & 0x3f == 8:                  # jr ra
            stop = a + 4
        else:
            assert w == 0, (hex(a), hex(w))
        gpr[0] = 0
        a += 4


def max_s(a, b):
    """The EE's max.s compares sign-magnitude, so max(+0, -0) is +0."""
    ia, ib = fbits(a), fbits(b)
    sa = -(ia & 0x7fffffff) if ia & 0x80000000 else ia
    sb = -(ib & 0x7fffffff) if ib & 0x80000000 else ib
    if sa == sb:
        return a
    return a if sa > sb else b


# ============================================================ the model

def dump_aero(tag, a):
    emit("%s ai 1 body 1 boost %s draft %s throttle %s ge %s"
         % (tag, g9(a["boost"]), g9(a["draft"]), g9(a["throttle"]),
            g9(a["ge"])))


def aero_init():
    return {"boost": INIT_BOOST, "draft": INIT_DRAFT,
            "throttle": INIT_THROTTLE, "ge": INIT_GE}


STATE = {"factor": bits(C_OFF_FACTOR_W), "height": bits(C_OFF_HEIGHT_W),
         "front": None, "rear": None}


def s_layout():
    emit("[layout]")
    emit("sizeof %d slack %d" % (AERO_SIZE + 2 * SLACK, SLACK))
    emit("off %d %d %d %d %d %d"
         % (AERO["AI"], AERO["pBody"] + SLACK,
            AERO["Boost"] + 2 * SLACK, AERO["Draft"] + 2 * SLACK,
            AERO["Throttle"] + 2 * SLACK, AERO["GroundEffect"] + 2 * SLACK))
    emit("aeroinfo %d %d %d %d %d"
         % (INFO_SIZE, INFO["Drag"], INFO["FrontDownforce"],
            INFO["RearDownforce"], INFO["AutoBalanceDownforce"]))
    # Everything in RigidBody from State onwards moves by two slack terms.
    emit("body %d %d %d" % (PS2_VELOCITY + 2 * SLACK, PS2_R_V0 + 2 * SLACK,
                            PS2_R_V2Z + 2 * SLACK))
    emit("consts %08x %08x %08x %08x" % (C_MIN_SPEED_W, C_FRONT_SHARE_W,
                                         C_REAR_SHARE_W, fbits(C_GE)))
    emit("sdata %08x %08x" % (C_OFF_FACTOR_W, C_OFF_HEIGHT_W))


def s_static():
    emit("[static]")
    mem = {}
    for base, vals in ((FRONT_LOC, (7.0, 7.5, 8.0, 8.5)),
                       (REAR_LOC, (-7.0, -7.5, -8.0, -8.5))):
        for i, v in enumerate(vals):
            mem[base + 4 * i] = f32(v)
    static_init(mem)
    front = tuple(mem[FRONT_LOC + 4 * i] for i in range(4))
    rear = tuple(mem[REAR_LOC + 4 * i] for i in range(4))
    pv("front", front)
    pv("rear", rear)
    STATE["front"] = front[:3] + (f32(0.0),)
    STATE["rear"] = rear[:3] + (f32(0.0),)


def s_init():
    emit("[init]")
    a = aero_init()
    dump_aero("init", a)
    a["boost"], a["draft"], a["throttle"] = f32(1.5), f32(0.625), f32(0.75)
    a["ge"] = f32(0.875)
    dump_aero("set", a)
    emit("at-speed %s" % g9(at_speed(f32(2.0), f32(1.5), f32(2.5))))


def at_speed(speed, front, rear):
    """0x001a4dc8: max.s against zero, then (Front + Rear), then the mul."""
    return fmul(max_s(f32(0.0), speed), fadd(front, rear))


def dot3(a, b):
    return RB.dot3(a, b)


def resolve(rb, a, ai):
    """0x001a4b80. `rb` is a rigidbody_check.RB; returns what goes to
    *out."""
    one, zero = f32(1.0), f32(0.0)
    vel = rb.V

    # ---- drag
    speed = fsqrt(dot3(vel, vel))
    s = fdiv(speed, a["boost"])
    drag = fmul(fmul(s, a["draft"]), ai["drag"])
    off = fsub(one, a["throttle"])
    k = fadd(drag, fmul(fmul(drag, fsub(STATE["factor"], one)), off))
    force = RB.scale4(vel, fneg(k))
    at_z = fmul(STATE["height"], off) if C_GE <= a["ge"] else zero
    RB.apply_force(rb, force, (zero, zero, at_z, zero))

    # ---- downforce
    up = rb.R[2][2]
    if up < zero:
        up = zero
    if C_GE <= a["ge"]:
        up = one
    d = (one, zero, zero)
    if C_MIN_SPEED < s:
        d = RB.scale4(vel, fdiv(one, s))
    c = dot3(d, rb.R[0])
    if c < zero:
        c = zero
    c = fmul(c, c)
    c = fmul(c, c)
    if a["ge"] == zero:
        w = fmul(c, up)
        fs = fmul(fmul(s, C_FRONT_SHARE), w)
        rs = fmul(fmul(s, C_REAR_SHARE), w)
        total = fadd(ai["front"], ai["rear"])
        rd = fmul(rs, total)
        fd = fmul(fs, total)
    else:
        w = fmul(c, up)
        rd = fmul(fmul(s, ai["rear"]), w)
        fd = fmul(fmul(s, ai["front"]), w)

    for push, loc in ((fneg(fd), STATE["front"]), (fneg(rd), STATE["rear"])):
        wf = RB.mulmv3(rb.R, (zero, zero, push, zero))
        wat = RB.mulmv3(rb.R, loc)
        RB.apply_force(rb, wf, wat)
    return fadd(fd, rd)


def row(v):
    return tuple(f32(x) for x in v)


I = ((1, 0, 0, 0), (0, 1, 0, 0), (0, 0, 1, 0), (0, 0, 0, 1))
UPSIDE = ((1, 0, 0, 0), (0, -1, 0, 0), (0, 0, -1, 0), (0, 0, 0, 1))

# name, vel, R, boost, draft, throttle, ge, drag, front, rear, with_out --
# tools/src/aerodynamics_test.c's kCases, in its order.
CASES = [
    ("level", (30.0, 0.0, 0.0, 0.0), I,
     1.0, 1.0, 1.0, 0.0, 0.375, 2.5, 3.25, 1),
    ("coast", (20.0, 5.0, -1.0, 0.0),
     ((0.96, 0.28, 0, 0), (-0.28, 0.96, 0, 0), (0, 0, 1, 0), (0, 0, 0, 1)),
     1.25, 0.8, 0.3, 0.0, 0.4, 1.5, 2.0, 1),
    ("ge-half", (12.0, -3.0, 0.5, 0.0),
     ((1, 0, 0, 0), (0, 0.968245804, -0.25, 0),
      (0, 0.25, 0.968245804, 0), (0, 0, 0, 1)),
     1.0, 1.0, 0.2, 0.5, 0.3, 2.0, 1.0, 1),
    ("ge-low", (25.0, 2.0, 0.0, 0.0),
     ((0.8, 0.6, 0, 0), (-0.6, 0.8, 0, 0), (0, 0, 0.5, 0),
      (3.0, -2.0, 1.0, 1)),
     1.0, 1.0, 0.6, 0.25, 0.5, 3.0, 4.0, 1),
    ("ge-inverted", (18.0, 0.0, 4.0, 0.0), UPSIDE,
     1.0, 1.5, 0.0, 0.75, 0.25, 1.25, 0.75, 1),
    ("inverted", (18.0, 0.0, 4.0, 0.0), UPSIDE,
     1.0, 1.0, 0.5, 0.0, 0.25, 1.25, 0.75, 1),
    ("reverse", (-15.0, 1.0, 0.0, 0.0), I,
     1.0, 1.0, 0.0, 0.0, 0.35, 2.0, 2.0, 1),
    ("still", (0.0, 0.0, 0.0, 0.0), I,
     1.0, 1.0, 1.0, 0.0, 0.3, 2.0, 2.0, 1),
    ("at-floor", (0.0, 9.99999975e-05, 0.0, 0.0),
     ((0.6, 0.8, 0, 0), (-0.8, 0.6, 0, 0), (0, 0, 1, 0), (0, 0, 0, 1)),
     1.0, 1.0, 1.0, 0.0, 0.3, 2.0, 2.0, 1),
    ("over-floor", (0.0, 0.000100000005, 0.0, 0.0),
     ((0.6, 0.8, 0, 0), (-0.8, 0.6, 0, 0), (0, 0, 1, 0), (0, 0, 0, 1)),
     1.0, 1.0, 1.0, 0.0, 0.3, 2.0, 2.0, 1),
    ("boost", (40.0, 0.0, 0.0, 0.0), I,
     2.0, 1.0, 1.0, 0.0, 0.375, 2.5, 3.25, 1),
    ("bracket", (15.0, 4.3, 0.7, 0.0),
     ((0.96, 0.28, 0, 0), (-0.28, 0.96, 0, 0), (0, 0, 1, 0), (0, 0, 0, 1)),
     1.0, 1.0, 0.4, 0.0, 0.35, 1.5, 2.0, 1),
    ("clamp", (150.0, -40.0, 10.0, 2.0),
     ((0.96, -0.28, 0, 0), (0.28, 0.96, 0, 0), (0, 0, 1, 0), (0, 0, 0, 1)),
     1.0, 1.0, 0.1, 0.9, 0.5, 1.0, 1.0, 1),
    ("no-out", (22.0, 1.0, 0.0, 0.0), I,
     1.0, 1.0, 1.0, 0.0, 0.375, 2.5, 3.25, 0),
    ("long-axis", (10.0, 0.0, 0.0, 0.0),
     ((2, 0, 0, 0), (0, 1, 0, 0), (0, 0, 1, 0), (0, 0, 0, 1)),
     1.0, 1.0, 1.0, 0.0, 0.2, 0.5, 0.75, 1),
]

# The two floor cases are only on the floor if sqrt(x * x) comes back as
# x, which the harness's comment claims.
for _c in CASES:
    if _c[0] in ("at-floor", "over-floor"):
        _x = f32(_c[1][1])
        assert fsqrt(fmul(_x, _x)) == _x, _c[0]
assert f32(9.99999975e-05) == C_MIN_SPEED
assert fbits(0.000100000005) == C_MIN_SPEED_W + 1


def body(vel, r):
    rb = RB.RB()
    z = f32(0.0)
    rb.V = row(vel)
    rb.R = [row(x) for x in r]
    rb.FA = (z, z, z, z)
    rb.MA = (z, z, z, z)
    return rb


def s_resolve():
    emit("[resolve]")
    for (name, vel, r, boost, draft, throttle, ge, drag, front, rear,
         with_out) in CASES:
        rb = body(vel, r)
        rb.FA = row((1.0, 2.0, 3.0, 4.0))
        rb.MA = row((-1.0, -2.0, -3.0, -4.0))
        ai = {"drag": f32(drag), "front": f32(front), "rear": f32(rear)}
        a = aero_init()
        a["boost"], a["draft"] = f32(boost), f32(draft)
        a["throttle"], a["ge"] = f32(throttle), f32(ge)
        emit("case %s" % name)
        got = resolve(rb, a, ai)
        out = got if with_out else f32(1234.5)
        pv("  FA", rb.FA)
        pv("  MA", rb.MA)
        emit("  out %s" % g9(out))
        dump_aero("  after", a)


def s_tuning():
    emit("[tuning]")
    rb = body((10.0, 0.0, 0.0, 0.0), I)
    ai = {"drag": f32(0.5), "front": f32(1.0), "rear": f32(1.0)}
    a = aero_init()
    a["throttle"], a["ge"] = f32(0.25), f32(1.0)
    saved = STATE["factor"], STATE["height"]
    STATE["factor"], STATE["height"] = f32(3.5), f32(-0.75)
    out = resolve(rb, a, ai)
    STATE["factor"], STATE["height"] = saved
    pv("  FA", rb.FA)
    pv("  MA", rb.MA)
    emit("  out %s" % g9(out))


def s_at_speed():
    emit("[at-speed]")
    for sp in (-5.0, -0.0, 0.0, 3.5, 100.0, 0.1):
        x = f32(sp)
        emit("  %s -> %s" % (g9(x), g9(at_speed(x, f32(1.75), f32(2.125)))))


def s_snapshot():
    emit("[snapshot]")
    pairs = [(0, 0), (1, 0), (0, 2), (128, 64)]
    for k in range(-1, 4):
        a = aero_init()
        a["boost"], a["draft"] = f32(1.25), f32(0.5)
        a["throttle"], a["ge"] = f32(0.75), f32(0.625)
        # The image ORs bytes 56 and 57 (lbu at 0x001a4b58/5c); the port
        # asks wheel.h's seam, which NULL leaves alone.
        if k >= 0 and (pairs[k][0] | pairs[k][1]):
            a["ge"], a["boost"], a["throttle"] = (f32(0.0),) * 3
        dump_aero("  seam" if k >= 0 else "  null", a)


assert imm(0x001a4b58, 0x24) == 57 and imm(0x001a4b5c, 0x24) == 56   # lbu


def model():
    del OUT[:]
    STATE["factor"] = bits(C_OFF_FACTOR_W)
    STATE["height"] = bits(C_OFF_HEIGHT_W)
    s_layout()
    s_static()
    s_init()
    s_resolve()
    s_tuning()
    s_at_speed()
    s_snapshot()
    return list(OUT)


# ============================================================= running

run_harness = PS.run_harness
diff = PS.diff
HARNESS_HUNG = PS.HARNESS_HUNG

# ============================================================ mutations

MUTATIONS = [
    # -- the static data ---------------------------------------------------
    ("static-front-x-neg", AC,
     "    FrontDownforceLocation.x = 1.0f;",
     "    FrontDownforceLocation.x = -1.0f;"),
    ("static-rear-x-pos", AC,
     "    RearDownforceLocation.x  = -1.0f;",
     "    RearDownforceLocation.x  = 1.0f;"),
    ("static-writes-w", AC,
     "    RearDownforceLocation.y  = 0.0f;",
     "    RearDownforceLocation.y  = 0.0f;" + NL
     + "    FrontDownforceLocation.w = 0.0f;"),
    ("static-drops-rear-y", AC,
     "    RearDownforceLocation.y  = 0.0f;" + NL,
     ""),
    ("static-front-z-as-w", AC,
     "    FrontDownforceLocation.z = 0.0f;",
     "    FrontDownforceLocation.w = 0.0f;"),
    ("sdata-factor", AC,
     "float OffThrottleDragFactor       = 2.0f;",
     "float OffThrottleDragFactor       = 2.5f;"),
    ("sdata-height", AC,
     "float OffThrottleDragCenterHeight = -0.100000001f;",
     "float OffThrottleDragCenterHeight = -0.125f;"),

    # -- init and the setters ----------------------------------------------
    ("init-boost-zero", AC,
     "    a->Boost        = 1.0f;",
     "    a->Boost        = 0.0f;"),
    ("init-draft-zero", AC,
     "    a->Draft        = 1.0f;",
     "    a->Draft        = 0.0f;"),
    ("init-throttle-one", AC,
     "    a->Throttle     = 0.0f;" + NL + "    a->GroundEffect = 0.0f;",
     "    a->Throttle     = 1.0f;" + NL + "    a->GroundEffect = 0.0f;"),
    ("init-ge-half", AC,
     "    a->GroundEffect = 0.0f;" + NL + "}",
     "    a->GroundEffect = 0.5f;" + NL + "}"),
    ("set-draft-writes-boost", AC,
     "{ a->Draft = f; }",
     "{ a->Boost = f; }"),
    ("set-throttle-noop", AC,
     "{ a->Throttle = f; }",
     "{ (void)a; (void)f; }"),
    ("set-ge-writes-throttle", AC,
     "    a->GroundEffect = f;",
     "    a->Throttle = f;"),

    # -- the drag ----------------------------------------------------------
    ("drag-no-sqrt", AC,
     "    speed = sqrtf(dot3(vel, vel));",
     "    speed = dot3(vel, vel);"),
    ("drag-times-boost", AC,
     "    s     = speed / a->Boost;",
     "    s     = speed * a->Boost;"),
    ("drag-no-draft", AC,
     "    drag  = (s * a->Draft) * a->AI->Drag;",
     "    drag  = s * a->AI->Drag;"),
    ("drag-bracket", AC,
     "    drag  = (s * a->Draft) * a->AI->Drag;",
     "    drag  = s * (a->Draft * a->AI->Drag);"),
    ("drag-factor-whole", AC,
     "(OffThrottleDragFactor - 1.0f)",
     "OffThrottleDragFactor"),
    ("drag-factor-folded", AC,
     "(OffThrottleDragFactor - 1.0f)",
     "(2.0f - 1.0f)"),
    ("drag-off-is-throttle", AC,
     "    off   = 1.0f - a->Throttle;",
     "    off   = a->Throttle;"),
    ("drag-k-regrouped", AC,
     "    k     = drag + (drag * (OffThrottleDragFactor - 1.0f)) * off;",
     "    k     = drag * (1.0f + (OffThrottleDragFactor - 1.0f) * off);"),
    ("drag-sign", AC,
     "    scale4(&force, vel, -k);",
     "    scale4(&force, vel, k);"),
    ("scale-drops-w", AC,
     "    o->w = v->w * s;",
     "    o->w = v->w;"),
    ("dot-bracket", AC,
     "    return (xx + yy) + zz;",
     "    return xx + (yy + zz);"),

    # -- the drag's point --------------------------------------------------
    ("at-z-unguarded", AC,
     "    if (AERODYNAMICS_GROUND_EFFECT <= a->GroundEffect)" + NL
     + "        at.z = OffThrottleDragCenterHeight * off;",
     "    at.z = OffThrottleDragCenterHeight * off;"),
    ("at-z-strict", AC,
     "    if (AERODYNAMICS_GROUND_EFFECT <= a->GroundEffect)" + NL
     + "        at.z = ",
     "    if (AERODYNAMICS_GROUND_EFFECT < a->GroundEffect)" + NL
     + "        at.z = "),
    ("at-z-no-off", AC,
     "        at.z = OffThrottleDragCenterHeight * off;",
     "        at.z = OffThrottleDragCenterHeight;"),
    ("at-z-height-folded", AC,
     "        at.z = OffThrottleDragCenterHeight * off;",
     "        at.z = -0.100000001f * off;"),
    ("at-w-one", AC,
     "    at.w = 0.0f;",
     "    at.w = 1.0f;"),
    ("at-x-one", AC,
     "    at.x = 0.0f;",
     "    at.x = 1.0f;"),

    # -- the up factor -----------------------------------------------------
    ("up-no-floor", AC,
     "    if (up < 0.0f)" + NL + "        up = 0.0f;" + NL,
     ""),
    ("up-axis-y", AC,
     "    up = rb->State.R.v2.z;",
     "    up = rb->State.R.v2.y;"),
    ("up-strict", AC,
     "    if (AERODYNAMICS_GROUND_EFFECT <= a->GroundEffect)" + NL
     + "        up = 1.0f;",
     "    if (AERODYNAMICS_GROUND_EFFECT < a->GroundEffect)" + NL
     + "        up = 1.0f;"),
    ("up-not-forced", AC,
     "    if (AERODYNAMICS_GROUND_EFFECT <= a->GroundEffect)" + NL
     + "        up = 1.0f;" + NL,
     ""),

    # -- the direction -----------------------------------------------------
    ("dir-default-zero", AC,
     "    dir.x = 1.0f;",
     "    dir.x = 0.0f;"),
    ("dir-floor-inclusive", AC,
     "    if (AERODYNAMICS_MIN_SPEED < s)",
     "    if (AERODYNAMICS_MIN_SPEED <= s)"),
    ("dir-divides", AC,
     "        scale4(&dir, vel, 1.0f / s);",
     "        { dir.x = vel->x / s; dir.y = vel->y / s;"
     " dir.z = vel->z / s; dir.w = vel->w / s; }"),
    ("dir-over-speed", AC,
     "        scale4(&dir, vel, 1.0f / s);",
     "        scale4(&dir, vel, 1.0f / speed);"),
    ("dir-normalised", AC,
     "    if (AERODYNAMICS_MIN_SPEED < s)" + NL
     + "        scale4(&dir, vel, 1.0f / s);",
     "    if (AERODYNAMICS_MIN_SPEED < speed)" + NL
     + "        scale4(&dir, vel, 1.0f / speed);"),
    ("c-axis-v1", AC,
     "    c = dot3(&dir, &rb->State.R.v0);",
     "    c = dot3(&dir, &rb->State.R.v1);"),
    ("c-no-floor", AC,
     "    if (c < 0.0f)" + NL + "        c = 0.0f;" + NL,
     ""),
    ("c-squared-once", AC,
     "    c = c * c;" + NL + "    c = c * c;",
     "    c = c * c;"),

    # -- the two downforce arms --------------------------------------------
    ("arm-test-half", AC,
     "    if (a->GroundEffect == 0.0f) {",
     "    if (a->GroundEffect < AERODYNAMICS_GROUND_EFFECT) {"),
    ("arm0-shares-swapped", AC,
     [("s * AERODYNAMICS_FRONT_SHARE", "s * AERODYNAMICS_TMP_SHARE", 1),
      ("s * AERODYNAMICS_REAR_SHARE", "s * AERODYNAMICS_FRONT_SHARE", 1),
      ("s * AERODYNAMICS_TMP_SHARE", "s * AERODYNAMICS_REAR_SHARE", 1)]),
    ("arm0-front-only", AC,
     "        sum = a->AI->FrontDownforce + a->AI->RearDownforce;",
     "        sum = a->AI->FrontDownforce;"),
    ("arm0-fd-from-rear", AC,
     "        fd  = fs * sum;",
     "        fd  = rs * sum;"),
    ("arm0-no-w", AC,
     "        rs  = rs * w;",
     "        rs  = rs * 1.0f;"),
    ("arm0-bracket", AC,
     "        fs  = fs * w;",
     "        fs  = s * (AERODYNAMICS_FRONT_SHARE * w);"),
    ("arm1-rear-from-front", AC,
     "        rd = (s * a->AI->RearDownforce) * w;",
     "        rd = (s * a->AI->FrontDownforce) * w;"),
    ("arm1-no-w", AC,
     "        fd = (s * a->AI->FrontDownforce) * w;",
     "        fd = s * a->AI->FrontDownforce;"),
    ("arm1-bracket", AC,
     "        rd = (s * a->AI->RearDownforce) * w;",
     "        rd = s * (a->AI->RearDownforce * w);"),
    ("arm1-quadratic", AC,
     "        fd = (s * a->AI->FrontDownforce) * w;",
     "        fd = ((s * s) * a->AI->FrontDownforce) * w;"),

    # -- the two pushes and the answer -------------------------------------
    ("front-sign", AC,
     "    front.z = -fd;",
     "    front.z = fd;"),
    ("front-from-rear", AC,
     "    front.z = -fd;",
     "    front.z = -rd;"),
    ("rear-along-x", AC,
     "    rear.x  = 0.0f;" + NL + "    rear.y  = 0.0f;" + NL
     + "    rear.z  = -rd;",
     "    rear.x  = -rd;" + NL + "    rear.y  = 0.0f;" + NL
     + "    rear.z  = 0.0f;"),
    ("front-at-rear", AC,
     "&front, &FrontDownforceLocation);",
     "&front, &RearDownforceLocation);"),
    ("front-not-in-frame", AC,
     "    rigidbody_apply_force_in_frame(rb, &front, &FrontDownforceLocation);",
     "    rigidbody_apply_force(rb, &front, &FrontDownforceLocation);"),
    ("rear-skipped", AC,
     "    rigidbody_apply_force_in_frame(rb, &rear, &RearDownforceLocation);"
     + NL,
     ""),
    ("out-front-only", AC,
     "        *out = fd + rd;",
     "        *out = fd;"),
    ("out-unguarded", AC,
     "    if (out)" + NL + "        *out = fd + rd;",
     "    *out = fd + rd;"),

    # -- GetDownforceAtSpeed -----------------------------------------------
    ("at-speed-no-max", AC,
     "    float m = speed > 0.0f ? speed : 0.0f;",
     "    float m = speed;"),
    ("at-speed-fabs", AC,
     "    float m = speed > 0.0f ? speed : 0.0f;",
     "    float m = fabsf(speed);"),
    ("at-speed-rear-only", AC,
     "    return m * (a->AI->FrontDownforce + a->AI->RearDownforce);",
     "    return m * a->AI->RearDownforce;"),

    # -- DoSnapshot --------------------------------------------------------
    ("snap-ignores-answer", AC,
     "    if (gReplayShouldResetFn && gReplayShouldResetFn(snap)) {",
     "    if (gReplayShouldResetFn) {"),
    ("snap-null-resets", AC,
     "    if (gReplayShouldResetFn && gReplayShouldResetFn(snap)) {",
     "    if (!gReplayShouldResetFn || gReplayShouldResetFn(snap)) {"),
    ("snap-clears-draft", AC,
     "        a->Boost        = 0.0f;",
     "        a->Draft        = 0.0f;"),
    ("snap-keeps-ge", AC,
     "        a->GroundEffect = 0.0f;" + NL + "        a->Boost",
     "        a->Boost"),
    ("snap-boost-one", AC,
     "        a->Boost        = 0.0f;",
     "        a->Boost        = 1.0f;"),

    # -- ApplyForceInFrame and bMulMatrixVec3, first checked here ----------
    ("inframe-at-untransformed", RC,
     "    bMulMatrixVec3((bVector3 *)&wat, &rb->State.R, "
     "(const bVector3 *)at);",
     "    wat = *at;"),
    ("inframe-force-untransformed", RC,
     "    bMulMatrixVec3((bVector3 *)&wf, &rb->State.R, "
     "(const bVector3 *)f);",
     "    wf = *f;"),
    ("inframe-args-swapped", RC,
     "    rigidbody_apply_force(rb, &wf, &wat);",
     "    rigidbody_apply_force(rb, &wat, &wf);"),
    ("vec3-w-in-zero", MC,
     "    in.w = 1.0f;" + NL + "    row_times_matrix(&t, &in, m);" + NL
     + "    o->x = t.x;",
     "    in.w = 0.0f;" + NL + "    row_times_matrix(&t, &in, m);" + NL
     + "    o->x = t.x;"),
    ("vec3-pad-zero", MC,
     "    o->pad = t.w;",
     "    o->pad = 0.0f;"),
]

EQUIVALENT = {}

for _name in EQUIVALENT:
    assert any(_m[0] == _name for _m in MUTATIONS), _name
assert len(set(m[0] for m in MUTATIONS)) == len(MUTATIONS)


def mutate_pass():
    base_model = model()
    survived, missing, caught = [], [], 0

    with tempfile.TemporaryDirectory() as tmp:
        exe = hostbuild.build(tmp, SOURCES, name="aerodynamics_test")
        out = Path(tmp) / "base.txt"
        run_harness(exe, out)
        if diff(base_model, out.read_text().splitlines(), quiet=True):
            print("base already differs -- fix that before mutating")
            return 1

    for m in MUTATIONS:
        name, rel = m[0], m[1]
        path = ROOT / rel
        text = path.read_text(encoding="utf-8", newline="")
        mutated = PS.apply_mutation(text, PS.edits_of(m))
        if mutated is None:
            missing.append(name)
            print("  %-34s PATTERN NOT FOUND" % name)
            continue
        try:
            hostbuild.write_source(path, mutated)
            with tempfile.TemporaryDirectory() as tmp:
                try:
                    exe = hostbuild.build(tmp, SOURCES,
                                          name="aerodynamics_test")
                except SystemExit:
                    print("  %-34s did not compile (caught)" % name)
                    caught += 1
                    continue
                out = Path(tmp) / "m.txt"
                rc = run_harness(exe, out)
                if rc == HARNESS_HUNG:
                    print("  %-34s hung the harness (caught)" % name)
                    caught += 1
                    continue
                if rc != 0:
                    print("  %-34s crashed the harness (caught)" % name)
                    caught += 1
                    continue
                n = diff(base_model, out.read_text().splitlines(), quiet=True)
                if n:
                    print("  %-34s caught, %d lines" % (name, n))
                    caught += 1
                elif name in EQUIVALENT:
                    print("  %-34s survived, equivalent by construction"
                          % name)
                else:
                    print("  %-34s SURVIVED" % name)
                    survived.append(name)
        finally:
            try:
                hostbuild.write_source(path, text)
            except OSError:
                sys.exit("could not restore %s -- it still holds the "
                         "mutation %s. Put the original back before "
                         "trusting anything printed above." % (rel, name))

    real = [m for m in MUTATIONS if m[0] not in missing]
    holes = [s for s in survived if s not in EQUIVALENT]
    if missing:
        print("%d PATTERN NOT FOUND -- the tally below is over %d of %d"
              % (len(missing), len(real), len(MUTATIONS)))
    print("%d mutations, %d caught, %d equivalent, %d unexplained"
          % (len(real), caught, len(EQUIVALENT), len(holes)))
    for name in holes:
        print("  unexplained: %s" % name)
    return 1 if (holes or missing) else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mutate", action="store_true")
    ap.add_argument("--dump", metavar="DIR")
    args = ap.parse_args()

    if args.mutate:
        sys.exit(mutate_pass())

    lines = model()
    with tempfile.TemporaryDirectory() as tmp:
        exe = hostbuild.build(tmp, SOURCES, name="aerodynamics_test")
        out = Path(tmp) / "harness.txt"
        run_harness(exe, out)
        harness = out.read_text().splitlines()

        if args.dump:
            d = Path(args.dump)
            d.mkdir(parents=True, exist_ok=True)
            (d / "model.txt").write_text(NL.join(lines) + NL)
            (d / "harness.txt").write_text(NL.join(harness) + NL)

    bad = diff(lines, harness)
    print("%d scenarios, %d lines, %d differ"
          % (sum(1 for line in lines if line.startswith("[")),
             len(harness), bad))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
