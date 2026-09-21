"""Cross-check 3DS Files/source/steering.c against a model of Steering.

Steering is the fifth slice of task 25, after CarState, Engine, CarTypeInfo
and CarDriver. It is a two-field base class -- the car type, and a pointer
to an array of per-wheel rotation matrices it does not own -- that computes
nothing at all, plus the one subclass in the image that does:
TwoWheelAckermanSteering.

Four things this transcript exists to pin down.

**The object carries its own trigonometry constants.** Its pi and 2pi are
0x40490fd0 and 0x40c90fd0, eleven ulps below the true float values, and
its pi/2 is 0x3fc90fdc, one ulp *above*. The fold decides which side of
the half-turn a steering angle lands on, and the pi/2 goes straight into
every cosine, so these are not cosmetic. The transcript prints all three
next to the true values.

**The cosine is a sine call.** `bSinF(angle + pi/2)`, not bCos and not
cosf, so the one-ulp pi/2 error rides along into every matrix.

**The Ackerman geometry is the small-angle approximation.**
cot(outer) = cot(inner) + Track/Wheelbase with tan(x) ~ x becomes
outer = (W * inner) / (W + T * inner), which is why there is a divide and
no atan. The transcript includes a geometry whose denominator comes close
to zero, where the approximation visibly blows up, because that is
behaviour the port has to reproduce rather than fix.

**Which matrix gets which angle depends on the sign.** Steering one way,
matrix 0 takes the full angle and matrix 1 the reduced one; steering the
other, they swap and both are negated.

The float layer is imported from bmath_check -- itself a model of
bMath.obj written from the ELF, not from the port -- so bSinF is not
being checked against itself here.

    python tools/steering_check.py
    python tools/steering_check.py --mutate
    python tools/steering_check.py --dump out/steering
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
import bmath_check

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

SOURCES = [
    "tools/src/steering_test.c",
    "3DS Files/source/steering.c",
    "3DS Files/source/bmatrix.c",
    "3DS Files/source/bmath.c",
    "3DS Files/source/bmathtab.c",
]

SH = "3DS Files/source/steering.h"
SC = "3DS Files/source/steering.c"

# The host this runs on. A property of the machine, not of the port: the
# PS2 layout below is stated in PS2 offsets and widened from here.
PTR = 8
SLACK = PTR - 4

f32 = bmath_check.f32
bits = bmath_check.bits
bSinF = bmath_check.bSinF


def g9(x):
    return "%.9g" % x


def pad(s, n):
    return s + " " * (n - len(s)) if len(s) < n else s


OUT = []


def emit(s):
    OUT.append(s)


# ------------------------------------------------------------- the image

# 0x00321804 .. 0x00321810, the pool SetSteering reads.
C_BAM_TO_RAD = bits(0x38c90fdb)
C_PI = bits(0x40490fd0)
C_TWO_PI = bits(0x40c90fd0)
C_HALF_PI = bits(0x3fc90fdc)

# Built with `lui 0x002a ; addiu` in the two constructors and the two
# destructors.
VT_STEERING = 0x00299018
VT_ACKERMAN = 0x00298ff8

_pool = struct.unpack("<4I", bmath_check.ELF.read(0x00321804, 16))
assert _pool == (0x38c90fdb, 0x40490fd0, 0x40c90fd0, 0x3fc90fdc), _pool

# -------------------------------------------------------------- the layout

# PS2 offsets. Steering is 12 bytes with the vptr last -- the old g++ ABI
# appends it -- and the subclass pads 12..15 to put bMatrix4 on a quadword.
PS2_STEERING = [("Steering.CTI", 0),
                ("Steering.SteeringMatrix", 4),
                ("Steering._vtable", 8)]
PS2_STEERING_SIZE = 12
PS2_ACKERMAN = [("TwoWheelAckermanSteering.base", 0),
                ("TwoWheelAckermanSteering.AckermanMatrix", 16)]
PS2_ACKERMAN_SIZE = 144
ACKERMAN_MATRICES = 2
MATRIX_SIZE = 64


def host_off(name, off):
    """Widen a PS2 offset: one slack term per pointer at or before it."""
    ptrs_before = sum(1 for _, o in (("CTI", 0), ("SteeringMatrix", 4))
                      if o < off)
    return off + ptrs_before * SLACK


def s_layout():
    emit("[layout]")
    emit("sizeof_host Steering %d" % (PS2_STEERING_SIZE + 3 * SLACK))
    emit("sizeof_host Ackerman %d" % (PS2_ACKERMAN_SIZE + 2 * SLACK))
    emit("slack %d" % SLACK)

    for name, off in PS2_STEERING:
        emit("off %s %d" % (pad(name, 28), host_off(name, off)))
    # The base is still at zero; only what follows it moves, and it
    # moves by the two pointers inside it.
    for name, off in PS2_ACKERMAN:
        emit("off %s %d" % (pad(name, 28),
                            off + (2 * SLACK if off else 0)))

    emit("arr AckermanMatrix %d" % (ACKERMAN_MATRICES * MATRIX_SIZE))
    emit("stride AckermanMatrix %d" % MATRIX_SIZE)
    emit("sizeof bMatrix4 %d" % MATRIX_SIZE)
    emit("sizeof bVector4 16")

    emit("const bam2rad %08x" % 0x38c90fdb)
    emit("const pi      %08x" % 0x40490fd0)
    emit("const twopi   %08x" % 0x40c90fd0)
    emit("const halfpi  %08x" % 0x3fc90fdc)

    # The true float values, so the eleven-ulp and one-ulp gaps are on
    # the page rather than in a comment.
    def tb(x):
        return struct.unpack("<I", struct.pack("<f", x))[0]

    emit("true  pi      %08x" % tb(3.14159265358979323846))
    emit("true  twopi   %08x" % tb(6.28318530717958647692))
    emit("true  halfpi  %08x" % tb(1.57079632679489661923))

    emit("vtable Steering %08x" % VT_STEERING)
    emit("vtable Ackerman %08x" % VT_ACKERMAN)


# --------------------------------------------------- construction, teardown

def s_init():
    emit("[init]")
    # 0x0019c580: `sw a1,0(v0)` and `sw v1,8(v0)`. SteeringMatrix is never
    # written, so whatever was in the four bytes at offset 4 stays there.
    for k in range(2):
        emit("run %d cti 1" % k)
        emit("run %d vtable %08x" % (k, VT_STEERING))
        emit("run %d matrix kept 1" % k)

    # 0x0019ba98: one store, to the vtable word.
    emit("fini vtable %08x" % VT_STEERING)
    emit("fini cti null 1")
    emit("fini matrix kept 1")


def scribbled_matrix(i):
    """What the harness fills matrix i with before each call."""
    return [f32(1000.0 * (i + 1) + j + 0.5) for j in range(16)]


def emit_matrix(tag, m):
    for j in range(16):
        emit("%s[%2d] %s" % (tag, j, g9(m[j])))


def s_ackerman_init():
    emit("[ackerman-init]")
    # 0x0019c500. `move v0,s0` at the end, CTI and the subclass vtable
    # written inline, and `addiu a2,a0,16 ; sw a2,4(a0)` for the matrix
    # pointer. The two-iteration loop in between has an empty body.
    emit("returns this 1")
    emit("cti 1")
    emit("vtable %08x" % VT_ACKERMAN)
    emit("matrix delta 0")
    for i in range(ACKERMAN_MATRICES):
        emit_matrix("m%d" % i, scribbled_matrix(i))

    # 0x0019c498 is `jr ra ; nop`.
    emit("aux unchanged 1")

    # 0x0019c4a0 stores ACKERMAN_VTABLE, then calls ~Steering, which
    # stores STEERING_VTABLE over the top. The base's value is what is
    # left behind.
    emit("fini vtable %08x" % VT_STEERING)
    emit("fini cti 1")
    emit("fini matrix delta 0")


def s_get_matrix():
    emit("[get-matrix]")
    # 0x0019c548: `lw v0,4(a0) ; sll a1,a1,6 ; addu v0,v0,a1`.
    for k in (-1, 0, 1, 2, 3, 7):
        emit("get %2d delta %d" % (k, k * MATRIX_SIZE))


# ------------------------------------------------------------- SetSteering

GEOMS = [
    ("sedan", [1.40, 1.35, -1.30, -1.25], [0.75, -0.75, 0.80, -0.70]),
    ("wide", [0.90, 0.95, -2.05, -2.10], [1.10, -1.10, 1.05, -1.15]),
    ("negtrack", [1.25, 1.20, -1.30, -1.35], [-0.80, 0.80, -0.85, 0.75]),
]

BAMS = [0x0000, 0x0001, 0x2000, 0x7fff, 0x8000, 0x8001, 0xc000, 0xffff]


def rotate_z(angle):
    """bIdentity, then m[0] and m[5] to cos, m[1] to sin, m[4] to -sin.

    The cosine is bSinF(angle + pi/2): the image has no cosine call here,
    and the pi/2 it adds is its own one-ulp-high constant.
    """
    m = [0.0] * 16
    m[0] = m[5] = m[10] = m[15] = 1.0
    c = bSinF(f32(angle + C_HALF_PI))
    s = bSinF(angle)
    m[0] = c
    m[1] = s
    m[4] = f32(-s)
    m[5] = c
    return m


def set_steering(gx, gy, bam):
    """0x0019bb18."""
    # `andi a1,a1,0xffff ; mtc1 ; cvt.s.w ; mul.s` -- zero-extended, so
    # rad starts in [0, 2pi) and is never negative before the fold.
    rad = f32(float(bam & 0xffff) * C_BAM_TO_RAD)

    # Both differences are computed before the branch; the second is in
    # the delay slot of a plain bc1f, so it happens on either path.
    wheelbase = f32(f32(gx[0]) - f32(gx[3]))
    track = f32(f32(gy[0]) - f32(gy[1]))

    if C_PI < rad:                       # c.lt.s -- strict, pi does not fold
        rad = f32(rad - C_TWO_PI)

    inner = f32(-rad) if rad < 0.0 else rad
    outer = f32(f32(wheelbase * inner)
                / f32(wheelbase + f32(track * inner)))

    if rad < 0.0:
        first, second = f32(-outer), f32(-inner)
    else:
        first, second = inner, outer

    return rotate_z(first), rotate_z(second)


def s_set_steering():
    emit("[set-steering]")
    for name, gx, gy in GEOMS:
        gxf = [f32(v) for v in gx]
        gyf = [f32(v) for v in gy]
        for bam in BAMS:
            emit("case %s %04x" % (name, bam))
            m0, m1 = set_steering(gxf, gyf, bam)
            emit_matrix("m0", m0)
            emit_matrix("m1", m1)


SCENARIOS = [s_layout, s_init, s_ackerman_init, s_get_matrix, s_set_steering]


def model():
    del OUT[:]
    for s in SCENARIOS:
        s()
    return list(OUT)


# ----------------------------------------------------------------- harness

def run_harness(exe, out_path):
    with open(out_path, "w") as fh:
        r = subprocess.run([str(exe)], stdout=fh, stderr=subprocess.PIPE,
                           text=True)
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
    ("st-vtable-first", SH,
     "    const CarTypeInfo *CTI;            // 0",
     "    uint32_t           _vtable_first;" + NL
     + "    const CarTypeInfo *CTI;            // 0"),
    ("st-fields-swapped", SH,
     "    const CarTypeInfo *CTI;            // 0" + NL
     + "    bMatrix4          *SteeringMatrix; // 4   not owned",
     "    bMatrix4          *SteeringMatrix; // 0" + NL
     + "    const CarTypeInfo *CTI;            // 4"),
    ("st-matrices-1", SH,
     "#define ACKERMAN_MATRICES 2",
     "#define ACKERMAN_MATRICES 1"),
    ("st-matrices-1-padded", SH,
     "    bMatrix4 AckermanMatrix[ACKERMAN_MATRICES]; //  16",
     "    bMatrix4 AckermanMatrix[ACKERMAN_MATRICES - 1];" + NL
     + "    uint8_t  _mpad[64];"),
    ("st-matrices-3", SH,
     "#define ACKERMAN_MATRICES 2",
     "#define ACKERMAN_MATRICES 3"),
    ("st-matrix-at-32", SH,
     "    Steering base;                            //   0",
     "    Steering base;                            //   0" + NL
     + "    uint8_t  _gap[16];"),

    # -- the constants ------------------------------------------------------
    ("st-bam2rad-off-by-one", SH,
     "#define STEERING_BAM_TO_RADIANS 9.58738019e-05f",
     "#define STEERING_BAM_TO_RADIANS 9.58738092e-05f"),
    ("st-pi-true", SH,
     "#define STEERING_IMAGE_PI       3.14159012f",
     "#define STEERING_IMAGE_PI       3.14159274f"),
    ("st-twopi-true", SH,
     "#define STEERING_IMAGE_TWO_PI   6.28318024f",
     "#define STEERING_IMAGE_TWO_PI   6.28318548f"),
    ("st-halfpi-true", SH,
     "#define STEERING_IMAGE_HALF_PI  1.57079649f",
     "#define STEERING_IMAGE_HALF_PI  1.57079633f"),
    ("st-vtables-swapped", SH,
     "#define STEERING_VTABLE        0x00299018u" + NL
     + "#define ACKERMAN_VTABLE        0x00298ff8u",
     "#define STEERING_VTABLE        0x00298ff8u" + NL
     + "#define ACKERMAN_VTABLE        0x00299018u"),

    # -- Steering -----------------------------------------------------------
    ("st-init-clears-matrix", SC,
     "    s->_vtable = STEERING_VTABLE;" + NL
     + "    // SteeringMatrix is deliberately not written: see steering.h.",
     "    s->_vtable = STEERING_VTABLE;" + NL
     + "    s->SteeringMatrix = NULL;"),
    ("st-fini-writes-ackerman", SC,
     "void steering_fini(Steering *s)" + NL + "{" + NL
     + "    s->_vtable = STEERING_VTABLE;",
     "void steering_fini(Steering *s)" + NL + "{" + NL
     + "    s->_vtable = ACKERMAN_VTABLE;"),
    ("st-fini-clears-cti", SC,
     "void steering_fini(Steering *s)" + NL + "{" + NL
     + "    s->_vtable = STEERING_VTABLE;",
     "void steering_fini(Steering *s)" + NL + "{" + NL
     + "    s->CTI = NULL;" + NL
     + "    s->_vtable = STEERING_VTABLE;"),
    ("st-getmatrix-scale-16", SC,
     "    return s->SteeringMatrix + wheel;",
     "    return (bMatrix4 *)((char *)s->SteeringMatrix + wheel * 16);"),
    ("st-getmatrix-clamped", SC,
     "    return s->SteeringMatrix + wheel;",
     "    if (wheel < 0) wheel = 0;" + NL
     + "    if (wheel > 1) wheel = 1;" + NL
     + "    return s->SteeringMatrix + wheel;"),

    # -- TwoWheelAckermanSteering's constructor and destructor --------------
    ("st-ack-no-matrix-store", SC,
     "    a->base.SteeringMatrix = &a->AckermanMatrix[0];",
     "    (void)0;"),
    ("st-ack-matrix-is-second", SC,
     "    a->base.SteeringMatrix = &a->AckermanMatrix[0];",
     "    a->base.SteeringMatrix = &a->AckermanMatrix[1];"),
    ("st-ack-base-vtable", SC,
     "    a->base._vtable = ACKERMAN_VTABLE;" + NL + NL
     + "    // `addiu a2,a0,16`",
     "    a->base._vtable = STEERING_VTABLE;" + NL + NL
     + "    // `addiu a2,a0,16`"),
    ("st-ack-clears-matrices", SC,
     "    a->base.SteeringMatrix = &a->AckermanMatrix[0];",
     "    a->base.SteeringMatrix = &a->AckermanMatrix[0];" + NL
     + "    { int zi; for (zi = 0; zi < ACKERMAN_MATRICES; zi++)" + NL
     + "          bIdentity(&a->AckermanMatrix[zi]); }"),
    ("st-ack-fini-keeps-own", SC,
     "    steering_fini(&a->base);",
     "    (void)0;"),
    ("st-aux-not-empty", SC,
     "    (void)a;   // jr ra ; nop",
     "    a->base._vtable = 0;"),

    # -- the rotation -------------------------------------------------------
    ("st-rot-no-identity", SC,
     "    bIdentity(m);" + NL + NL + "    c = bSinF",
     "    (void)0;" + NL + NL + "    c = bSinF"),
    ("st-rot-identity-last", SC,
     "    bIdentity(m);" + NL + NL
     + "    c = bSinF(angle + STEERING_IMAGE_HALF_PI);",
     "    c = bSinF(angle + STEERING_IMAGE_HALF_PI);"),
    ("st-rot-cos-reflected", SC,
     "    c = bSinF(angle + STEERING_IMAGE_HALF_PI);",
     "    c = bSinF(STEERING_IMAGE_HALF_PI - angle);"),
    ("st-rot-transposed", SC,
     "    m->v0.y = s;" + NL + "    m->v1.x = -s;",
     "    m->v0.y = -s;" + NL + "    m->v1.x = s;"),
    ("st-rot-m5-one", SC,
     "    m->v1.y = c;",
     "    m->v1.y = 1.0f;"),
    ("st-rot-about-y", SC,
     "    m->v0.x = c;" + NL + "    m->v0.y = s;" + NL
     + "    m->v1.x = -s;" + NL + "    m->v1.y = c;",
     "    m->v0.x = c;" + NL + "    m->v0.z = -s;" + NL
     + "    m->v2.x = s;" + NL + "    m->v2.z = c;"),

    # -- SetSteering --------------------------------------------------------
    ("st-bam-signed", SC,
     "    rad = (float)(int32_t)bam * STEERING_BAM_TO_RADIANS;",
     "    rad = (float)(int16_t)bam * STEERING_BAM_TO_RADIANS;"),
    ("st-fold-inclusive", SC,
     "    if (STEERING_IMAGE_PI < rad)",
     "    if (STEERING_IMAGE_PI <= rad)"),
    ("st-fold-subtracts-pi", SC,
     "        rad -= STEERING_IMAGE_TWO_PI;",
     "        rad -= STEERING_IMAGE_PI;"),
    ("st-wheelbase-w2", SC,
     "    wheelbase = cti->Wheels[0].PositionX - cti->Wheels[3].PositionX;",
     "    wheelbase = cti->Wheels[0].PositionX - cti->Wheels[2].PositionX;"),
    ("st-wheelbase-reversed", SC,
     "    wheelbase = cti->Wheels[0].PositionX - cti->Wheels[3].PositionX;",
     "    wheelbase = cti->Wheels[3].PositionX - cti->Wheels[0].PositionX;"),
    ("st-track-w2", SC,
     "    track     = cti->Wheels[0].PositionY - cti->Wheels[1].PositionY;",
     "    track     = cti->Wheels[0].PositionY - cti->Wheels[2].PositionY;"),
    ("st-track-reversed", SC,
     "    track     = cti->Wheels[0].PositionY - cti->Wheels[1].PositionY;",
     "    track     = cti->Wheels[1].PositionY - cti->Wheels[0].PositionY;"),
    ("st-axes-swapped", SC,
     "    wheelbase = cti->Wheels[0].PositionX - cti->Wheels[3].PositionX;"
     + NL
     + "    track     = cti->Wheels[0].PositionY - cti->Wheels[1].PositionY;",
     "    wheelbase = cti->Wheels[0].PositionY - cti->Wheels[3].PositionY;"
     + NL
     + "    track     = cti->Wheels[0].PositionX - cti->Wheels[1].PositionX;"),
    ("st-denom-no-inner", SC,
     "    outer = (wheelbase * inner) / (wheelbase + track * inner);",
     "    outer = (wheelbase * inner) / (wheelbase + track);"),
    ("st-denom-grouped", SC,
     "    outer = (wheelbase * inner) / (wheelbase + track * inner);",
     "    outer = (wheelbase * inner) / ((wheelbase + track) * inner);"),
    ("st-ratio-wt-swapped", SC,
     "    outer = (wheelbase * inner) / (wheelbase + track * inner);",
     "    outer = (track * inner) / (track + wheelbase * inner);"),
    ("st-inner-not-abs", SC,
     "    inner = (rad < 0.0f) ? -rad : rad;",
     "    inner = rad;"),
    ("st-sign-branch-inverted", SC,
     "        first  = -outer;" + NL + "        second = -inner;",
     "        first  = -inner;" + NL + "        second = -outer;"),
    ("st-sign-not-negated", SC,
     "        first  = -outer;" + NL + "        second = -inner;",
     "        first  = outer;" + NL + "        second = inner;"),
    ("st-matrices-swapped", SC,
     "    ackerman_rotate_z(&a->AckermanMatrix[0], first);" + NL
     + "    ackerman_rotate_z(&a->AckermanMatrix[1], second);",
     "    ackerman_rotate_z(&a->AckermanMatrix[0], second);" + NL
     + "    ackerman_rotate_z(&a->AckermanMatrix[1], first);"),
    ("st-both-get-first", SC,
     "    ackerman_rotate_z(&a->AckermanMatrix[1], second);",
     "    ackerman_rotate_z(&a->AckermanMatrix[1], first);"),
]

# `if (PI < rad)` and `if (PI <= rad)` cannot be told apart through this
# entry point, and the reason is worth keeping.
#
# rad is f32(bam * 2pi/65536) for an unsigned 16-bit bam, so it takes
# exactly 65536 values. None of them is the image's pi: the products step
# 0x40490e49 -> 0x40490fdb across bam 32767 -> 32768 and straddle
# 0x40490fd0 without landing on it. So `rad == IMAGE_PI` never happens and
# the two comparisons agree everywhere.
#
# Note what that depends on. If the image had used the *true* float pi,
# 0x40490fdb, bam 32768 would hit it exactly and the two comparisons would
# disagree at that one value. The eleven-ulp-low constant is what makes
# this equivalence hold.
EQUIVALENT = ["st-fold-inclusive"]
EXPECT_MISSING = []


def mutate_pass():
    base_model = model()
    caught = 0
    survived = []
    missing = []

    for name, rel, before, after in MUTATIONS:
        path = ROOT / rel
        text = path.read_text(encoding="utf-8", newline="")
        probe = before.replace(NL, "\r\n") if "\r\n" in text else before
        repl = after.replace(NL, "\r\n") if "\r\n" in text else after
        if probe not in text:
            missing.append(name)
            print("  %-28s PATTERN NOT FOUND" % name)
            continue
        try:
            path.write_text(text.replace(probe, repl, 1),
                            encoding="utf-8", newline="")
            with tempfile.TemporaryDirectory() as tmp:
                try:
                    exe = hostbuild.build(tmp, SOURCES, name="steering_test")
                except SystemExit:
                    print("  %-28s did not compile (caught)" % name)
                    caught += 1
                    continue
                out = Path(tmp) / "m.txt"
                if run_harness(exe, out) != 0:
                    print("  %-28s crashed the harness (caught)" % name)
                    caught += 1
                    continue
                n = diff(base_model, out.read_text().splitlines(), quiet=True)
                if n:
                    print("  %-28s caught, %d lines" % (name, n))
                    caught += 1
                elif name in EQUIVALENT:
                    print("  %-28s survived, equivalent by construction"
                          % name)
                else:
                    print("  %-28s SURVIVED" % name)
                    survived.append(name)
        finally:
            path.write_text(text, encoding="utf-8", newline="")

    real = [m for m in MUTATIONS if m[0] not in missing]
    holes = [s for s in survived if s not in EQUIVALENT]
    unexpected = [m for m in missing if m not in EXPECT_MISSING]
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
        exe = hostbuild.build(tmp, SOURCES, name="steering_test")
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
