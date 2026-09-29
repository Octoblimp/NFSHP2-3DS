"""Cross-check 3DS Files/source/emath.c against an independent model.

eMathE.obj (0x0011b9a0 .. 0x0011c7b8) is the engine's matrix layer: the
camera, the car sim, the AI and the collision code are all written in terms
of it. Almost every line of it is VU0 macro mode, so none of it could be read
at all until tools/vudis.py existed.

The model below is written from the disassembly -- the register traces are
quoted next to each function -- and not from emath.c. That matters here more
than usual: session 15 found two geometry bugs that a cross-check had been
passing for four sessions because the C had been written from a document that
had been written from the Python. The chain of custody for every rule here
runs back to an address in the ELF.

Everything is float32. The EE has no double and neither does VU0, so each
intermediate is put back through f32() -- otherwise the model computes in 53
bits, the port computes in 24, and the transcripts disagree in the last digit
on about a third of the lines.

    python tools/emath_check.py
    python tools/emath_check.py --mutate       # break emath.c and re-diff
    python tools/emath_check.py --dump out/emath
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
from bmath_check import bCosBam, bSinBam

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

SOURCES = [
    "tools/src/emath_test.c",
    "3DS Files/source/emath.c",
    "3DS Files/source/bmatrix.c",
    "3DS Files/source/bvector.c",
    "3DS Files/source/bmath.c",
    "3DS Files/source/bmathtab.c",
]


def f32(x):
    return struct.unpack("<f", struct.pack("<f", x))[0]


def bits(w):
    return struct.unpack("<f", struct.pack("<I", w))[0]


def g9(x):
    return "%.9g" % x


# ------------------------------------------------------- the ELF's constants
#
# Read out of .lit4/.sdata at the addresses the listings load from, not
# rounded from math.pi. C_ROT_PI_2 is one ulp above C_PI_2 and that is not a
# typo in this file: eRotateX/Y/Z load 0x3fc90fdc from gp-32396/-32388/-32380
# while eSin compares against 0x3fc90fdb at gp-32420.
C_2PI = bits(0x40c90fdb)
C_PI = bits(0x40490fdb)
C_PI_2 = bits(0x3fc90fdb)
C_SIN_3 = bits(0xbe2aaaa4)
C_SIN_5 = bits(0x3c08873e)
C_SIN_7 = bits(0xb94fb21f)
C_SIN_9 = bits(0x362e9c14)
C_BAM_TO_RAD = bits(0x38c90fdb)
C_ROT_PI_2 = bits(0x3fc90fdc)


# ------------------------------------------------------------------ the types
#
# A matrix is a flat list of sixteen floats, row-major, row i at 4i. A vector
# is a list of four. Keeping them as plain lists rather than a class is
# deliberate: the transcript has to be built out of indices anyway, and a
# class would invite the model to share structure with the port.


def mat_new():
    return [0.0] * 16


def mat_identity():
    m = mat_new()
    m[0] = m[5] = m[10] = m[15] = 1.0
    return m


def mat_copy(m):
    return list(m)


# ----------------------------------------------------------------- the maths


def esin(x):
    """0x0011bf50.

        c.lt.s f0,f12 / sub.s      while (2pi < x) x -= 2pi
        c.lt.s f12,f0 / add.s      while (x < 0)   x += 2pi
        c.le.s f1,f12 / sub.s      if (pi <= x) { x -= pi; sign = -1 }
        c.le.s f0,f12 / bc1tl      if (pi/2 <= x) x = pi - x
        then x + x3*C3 + x5*C5 + x7*C7 + x9*C9, summed left to right
    """
    x = f32(x)
    sign = 1.0
    while C_2PI < x:
        x = f32(x - C_2PI)
    while x < 0.0:
        x = f32(x + C_2PI)
    if C_PI <= x:
        x = f32(x - C_PI)
        sign = -1.0
    if C_PI_2 <= x:
        x = f32(C_PI - x)

    x2 = f32(x * x)
    x3 = f32(x * x2)
    x5 = f32(x3 * x2)
    x7 = f32(x5 * x2)
    x9 = f32(x7 * x2)
    r = f32(x + f32(x3 * C_SIN_3))
    r = f32(r + f32(x5 * C_SIN_5))
    r = f32(r + f32(x7 * C_SIN_7))
    r = f32(r + f32(x9 * C_SIN_9))
    return f32(r * sign)


def emul_matrix(m1, m2):
    """0x0011bab0. vf4..vf7 are m1 (broadcast), vf8..vf11 are m2, so out row i
    is m1[i].x*m2.row0 + m1[i].y*m2.row1 + m1[i].z*m2.row2 + m1[i].w*m2.row3.
    bMulMatrix at 0x002426f8 loads the two the other way round, which is the
    whole difference between the two symbols."""
    o = mat_new()
    for i in range(4):
        for c in range(4):
            acc = f32(m1[i * 4 + 0] * m2[0 + c])
            acc = f32(acc + f32(m1[i * 4 + 1] * m2[4 + c]))
            acc = f32(acc + f32(m1[i * 4 + 2] * m2[8 + c]))
            acc = f32(acc + f32(m1[i * 4 + 3] * m2[12 + c]))
            o[i * 4 + c] = acc
    return o


def emul_vector4(m, v):
    """0x0011bb28."""
    o = [0.0] * 4
    for c in range(4):
        acc = f32(v[0] * m[0 + c])
        acc = f32(acc + f32(v[1] * m[4 + c]))
        acc = f32(acc + f32(v[2] * m[8 + c]))
        acc = f32(acc + f32(v[3] * m[12 + c]))
        o[c] = acc
    return o


def emul_vector3(m, v):
    """Retail's 0x0011b300 (the demo's 0x0011bb68). w forced to 1, so the
    translation row applies, and x, y and z added into the +0 lanes of the
    quadword at 0x002dc400 (vadd.xyz), so a -0 comes in as +0."""
    return emul_vector4(m, [f32(0.0 + v[0]), f32(0.0 + v[1]),
                            f32(0.0 + v[2]), 1.0])


def etranspose(m):
    """0x0011c368."""
    o = mat_new()
    for r in range(4):
        for c in range(4):
            o[r * 4 + c] = m[c * 4 + r]
    return o


def ecreate_translation(v):
    """0x0011c310."""
    m = mat_identity()
    m[12], m[13], m[14] = v[0], v[1], v[2]
    return m


def _rot_sin_cos(bam):
    """The shared head of eRotateX/Y/Z: BAM to radians, then eSin twice. The
    cosine is eSin(theta + 0x3fc90fdc) -- note the constant."""
    theta = f32(float(bam & 0xffff) * C_BAM_TO_RAD)
    c = esin(f32(theta + C_ROT_PI_2))
    s = esin(theta)
    return s, c


def erotate_x(m, bam):
    """0x0011c048. Stores at 0(sp)=1, 20=c, 24=s, 36=-s, 40=c, 60=1."""
    s, c = _rot_sin_cos(bam)
    r = mat_new()
    r[0] = 1.0
    r[5], r[6] = c, s
    r[9], r[10] = f32(-s), c
    r[15] = 1.0
    return emul_matrix(m, r)


def erotate_y(m, bam):
    """0x0011c110. 0=c, 8=-s, 20=1, 32=s, 40=c, 60=1."""
    s, c = _rot_sin_cos(bam)
    r = mat_new()
    r[0], r[2] = c, f32(-s)
    r[5] = 1.0
    r[8], r[10] = s, c
    r[15] = 1.0
    return emul_matrix(m, r)


def erotate_z(m, bam):
    """0x0011c1d8. 0=c, 4=s, 16=-s, 20=c, 40=1, 60=1."""
    s, c = _rot_sin_cos(bam)
    r = mat_new()
    r[0], r[1] = c, s
    r[4], r[5] = f32(-s), c
    r[10] = 1.0
    r[15] = 1.0
    return emul_matrix(m, r)


def etranslate(m, v):
    """0x0011c2a0. Builds T(v) on the stack and calls eMulMatrix(o, m, T)."""
    return emul_matrix(m, ecreate_translation(v))


def ecreate_axis_rotation(axis, bam):
    """0x0011bc68. bCos then bSin -- the table, not eSin. The products are
    formed in the order the listing forms them:

        f1 = k*x   f6 = k*z   f2 = k*y
        f7 = f1*z  f6 = f6*z  f4 = f2*z  f2 = f2*y
        f0 = x*s   f3 = f1*y  f1 = f1*x
    """
    c = f32(bCosBam(bam & 0xffff))
    s = f32(bSinBam(bam & 0xffff))
    x, y, z = axis[0], axis[1], axis[2]
    k = f32(1.0 - c)
    sz, sy, sx = f32(s * z), f32(s * y), f32(x * s)
    kx, ky, kz = f32(k * x), f32(k * y), f32(k * z)
    kxz, kzz, kyz = f32(kx * z), f32(kz * z), f32(ky * z)
    kyy, kxy, kxx = f32(ky * y), f32(kx * y), f32(kx * x)

    m = mat_new()
    m[0], m[1], m[2] = f32(kxx + c), f32(kxy - sz), f32(kxz + sy)
    m[4], m[5], m[6] = f32(kxy + sz), f32(kyy + c), f32(kyz - sx)
    m[8], m[9], m[10] = f32(kxz - sy), f32(kyz + sx), f32(kzz + c)
    m[15] = 1.0
    return m


def _cross(a, b):
    """vopmula ACC,a,b then vopmsub d,b,a -- d = a x b."""
    return [f32(f32(a[1] * b[2]) - f32(b[1] * a[2])),
            f32(f32(a[2] * b[0]) - f32(b[2] * a[0])),
            f32(f32(a[0] * b[1]) - f32(b[0] * a[1])),
            0.0]


def _normalize(v):
    """vmul.xyz then vaddy.x then vaddz.x then vrsqrt: the sum order is x,
    then +y, then +z, and the scale is 1/sqrt applied to every lane."""
    d = f32(v[0] * v[0])
    d = f32(d + f32(v[1] * v[1]))
    d = f32(d + f32(v[2] * v[2]))
    k = f32(1.0 / f32(math.sqrt(d)))
    return [f32(v[0] * k), f32(v[1] * k), f32(v[2] * k), 0.0]


def ecreate_lookat(eye, target, up):
    """0x0011bd68. dir = normalize(target - eye); right = (-up) x dir;
    up' = dir x right; normalize both; write them as COLUMNS; then
    eMulMatrix(o, T(-eye), that)."""
    negup = [f32(0.0 - up[0]), f32(0.0 - up[1]), f32(0.0 - up[2]), 0.0]
    d = [f32(target[0] - eye[0]), f32(target[1] - eye[1]),
         f32(target[2] - eye[2]), 0.0]
    d = _normalize(d)
    right = _cross(negup, d)
    newup = _cross(d, right)
    right = _normalize(right)
    newup = _normalize(newup)

    rot = mat_new()
    rot[0], rot[1], rot[2] = right[0], newup[0], d[0]
    rot[4], rot[5], rot[6] = right[1], newup[1], d[1]
    rot[8], rot[9], rot[10] = right[2], newup[2], d[2]
    rot[15] = 1.0

    trans = mat_identity()
    trans[12] = f32(0.0 - eye[0])
    trans[13] = f32(0.0 - eye[1])
    trans[14] = f32(0.0 - eye[2])
    return emul_matrix(trans, rot)


def einvert_transformation(m):
    """0x0011c3f0. R^T with a cleared fourth column into 0(sp), T(-t) into
    64(sp), then eMulMatrix(o, T, R^T)."""
    rot = mat_new()
    for r in range(3):
        for c in range(3):
            rot[r * 4 + c] = m[c * 4 + r]
    rot[15] = 1.0
    trans = mat_identity()
    trans[12] = f32(0.0 - m[12])
    trans[13] = f32(0.0 - m[13])
    trans[14] = f32(0.0 - m[14])
    return emul_matrix(trans, rot)


def einvert_rotation(m):
    """0x0011c6a0. eTransposeMatrix, then zero 12, 28, 44, 48, 52, 56 AND 60.
    The corner really is left at zero."""
    o = etranspose(m)
    o[3] = o[7] = o[11] = 0.0
    o[12] = o[13] = o[14] = o[15] = 0.0
    return o


def eorthonormalize(m):
    """0x0011c5d0. x = normalize(row0); z = normalize(x cross row1_raw);
    y = z cross x. Row 1 of the input is read before it is replaced, and
    rows 2 and 3 of the input are not read at all."""
    x = [m[0], m[1], m[2], 0.0]
    y = [m[4], m[5], m[6], 0.0]
    x = _normalize(x)
    z = _cross(x, y)
    z = _normalize(z)
    y = _cross(z, x)

    o = mat_new()
    o[0], o[1], o[2] = x[0], x[1], x[2]
    o[4], o[5], o[6] = y[0], y[1], y[2]
    o[8], o[9], o[10] = z[0], z[1], z[2]
    o[15] = 1.0
    return o


def enormalized_direction(a, b):
    """0x0011b9e0, and the one broken function in the file.

        vmul.xyz  vf02,vf03,vf03     vf2 = d*d
        vadday.x  ACC, vf02,vf02y    ACC.x = d.x^2 + d.y^2
        vaddaz.z  ACC, vf00,vf02z    ACC.z = d.z^2      <- written, never read
        vmaddw.x  vf01,vf00,vf00w    vf1.x = ACC.x + 0

    so the length it divides by is the 2D one. Every other normalise in the
    image -- about fifty of them, including bNormalize and the two above --
    sums three components with vaddy.x/vaddz.x. Its only caller is
    OLDeRenderLightFlare, which nothing calls, so it never shipped visibly."""
    dx = f32(b[0] - a[0])
    dy = f32(b[1] - a[1])
    dz = f32(b[2] - a[2])
    d = f32(f32(dx * dx) + f32(dy * dy))
    k = f32(1.0 / f32(math.sqrt(d)))
    return [f32(dx * k), f32(dy * k), f32(dz * k), 0.0]


def _transform_w1(m, v):
    """The shape eRotTransPers and eGetClipFlags share: vmaddw reads vf00.w,
    so w comes from the constant 1 and not from the vector."""
    o = [0.0] * 4
    for c in range(4):
        acc = f32(v[0] * m[0 + c])
        acc = f32(acc + f32(v[1] * m[4 + c]))
        acc = f32(acc + f32(v[2] * m[8 + c]))
        acc = f32(acc + m[12 + c])
        o[c] = acc
    return o


def erot_trans_pers(m, v):
    """0x0011bb98. vdiv Q,vf00w,vf12w then vmulq.xyz -- w is stored as it came
    out of the transform, undivided."""
    t = _transform_w1(m, v)
    q = f32(1.0 / t[3])
    return [f32(t[0] * q), f32(t[1] * q), f32(t[2] * q), t[3]]


def eget_clip_flags(v, m):
    """0x0011bc00. vclipw compares against |w| with strict inequalities and
    pushes six bits; cfc2 vi18 + andi 0x3f keeps the newest test."""
    t = _transform_w1(m, v)
    w = abs(t[3])
    f = 0
    if t[0] > w:
        f |= 0x01
    if t[0] < -w:
        f |= 0x02
    if t[1] > w:
        f |= 0x04
    if t[1] < -w:
        f |= 0x08
    if t[2] > w:
        f |= 0x10
    if t[2] < -w:
        f |= 0x20
    return f


def evector_star_matrix(o, v, m):
    """0x0011c4e8. Row i of the result is v x row i of m. Nine floats are
    written; the fourth column and row 3 keep whatever o already held."""
    vx, vy, vz = v[0], v[1], v[2]
    out = mat_copy(o)
    for r in range(3):
        a, b, c = m[r * 4 + 0], m[r * 4 + 1], m[r * 4 + 2]
        out[r * 4 + 0] = f32(f32(f32(-vz) * b) + f32(vy * c))
        out[r * 4 + 1] = f32(f32(vz * a) + f32(f32(-vx) * c))
        out[r * 4 + 2] = f32(f32(f32(-vy) * a) + f32(vx * b))
    return out


def eis_point_in_poly(pt, poly, n):
    """0x0011c6e8. j trails i and starts at n-1; the y test is half-open, so
    a horizontal ray through a vertex crosses once."""
    inside = 0
    j = n - 1
    for i in range(n):
        yi, yj = poly[i][1], poly[j][1]
        if (yi <= pt[1] and pt[1] < yj) or (yj <= pt[1] and pt[1] < yi):
            t = f32(f32(poly[j][0] - poly[i][0]) * f32(pt[1] - yi))
            if pt[0] < f32(f32(t / f32(yj - yi)) + poly[i][0]):
                inside = 0 if inside else 1
        j = i
    return inside


# ------------------------------------------------------------------- the rng

class Rng(object):
    """The harness's LCG. Every step is exact in float32 -- 24 integer bits
    times a power of two -- so this needs no rounding of its own."""

    def __init__(self, seed):
        self.s = seed & 0xffffffff

    def f(self, scale):
        self.s = (self.s * 1103515245 + 12345) & 0xffffffff
        u = f32(f32(float(self.s >> 8) * f32(1.0 / 8388608.0)) - 1.0)
        return f32(u * scale)

    def mat(self, scale):
        return [self.f(scale) for _ in range(16)]

    def vec3(self, scale):
        return [self.f(scale), self.f(scale), self.f(scale), 0.0]


# ------------------------------------------------------------- the transcript

BAMS = [0, 1, 2, 100, 8191, 8192, 8193, 16383, 16384, 16385,
        24575, 24576, 24577, 32767, 32768, 32769, 40960, 49151, 49152, 49153,
        57344, 60000, 65534, 65535,
        4096, 12288, 20480, 28672, 36864, 45056, 53248, 61440]

SIN_XS = [0.0, 1e-8, 0.5, 1.0, 1.5707963, 1.5707964, 2.0, 3.1415926,
          3.1415927, 3.1415928, 4.0, 6.2831852, 6.2831855, 6.2831858,
          7.0, 12.566371, 100.0, -0.5, -3.0, -6.2831855, -20.0]

AXES = [[1.0, 0.0, 0.0, 0.0],
        [0.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0, 0.0],
        [0.57735026, 0.57735026, 0.57735026, 0.0],
        [-0.70710678, 0.70710678, 0.0, 0.0],
        [0.26726124, 0.53452247, 0.80178374, 0.0]]

SQUARE = [(0.0, 0.0), (4.0, 0.0), (4.0, 4.0), (0.0, 4.0)]
ELL = [(0.0, 0.0), (4.0, 0.0), (4.0, 2.0), (2.0, 2.0), (2.0, 4.0), (0.0, 4.0)]
BOWTIE = [(0.0, 0.0), (4.0, 4.0), (4.0, 0.0), (0.0, 4.0)]


class Out(object):
    def __init__(self):
        self.lines = []

    def __call__(self, s):
        self.lines.append(s)

    def v3(self, tag, v):
        self("  %s %s %s %s" % (tag, g9(v[0]), g9(v[1]), g9(v[2])))

    def v4(self, tag, v):
        self("  %s %s %s %s %s"
             % (tag, g9(v[0]), g9(v[1]), g9(v[2]), g9(v[3])))

    def mat(self, m):
        for r in range(4):
            self("    %s %s %s %s" % (g9(m[r * 4 + 0]), g9(m[r * 4 + 1]),
                                      g9(m[r * 4 + 2]), g9(m[r * 4 + 3])))


def s_sin(o):
    o("scenario sin")
    for x in SIN_XS:
        o("  sin %s -> %s" % (g9(f32(x)), g9(esin(f32(x)))))
    for b in BAMS:
        r = f32(float(b) * C_BAM_TO_RAD)
        o("  bam %5d rad %s -> %s" % (b, g9(r), g9(esin(r))))


def s_basics(o):
    o("scenario basics")
    o("  identity")
    o.mat(mat_identity())
    o("  zero")
    o.mat(mat_new())
    o("  eIdentity")
    o.mat(mat_identity())
    o("  eZeroMatrix")
    o.mat(mat_new())

    g = Rng(0x1234567)
    a = g.mat(4.0)
    b = g.mat(4.0)
    o("  a")
    o.mat(a)
    o("  b")
    o.mat(b)
    o("  a*b")
    o.mat(emul_matrix(a, b))
    o("  b*a")
    o.mat(emul_matrix(b, a))
    o("  a*b aliased dst=src1")
    o.mat(emul_matrix(a, b))
    o("  a*b aliased dst=src2")
    o.mat(emul_matrix(a, b))
    o("  transpose a")
    o.mat(etranspose(a))

    v3 = g.vec3(3.0)
    o.v3("v3", v3)
    o.v3("v3*a", emul_vector3(a, v3))
    v4 = [g.f(3.0) for _ in range(4)]
    o.v4("v4", v4)
    o.v4("v4*a", emul_vector4(a, v4))

    # Retail's +0 lanes: -0 in, with every product a zero and a -0
    # translation, comes out +0 where the demo's gave -0.
    z = mat_identity()
    z[12] = z[13] = z[14] = -0.0
    o.v3("-0*z", emul_vector3(z, [-0.0, -0.0, -0.0]))
    # And each lane alone: with the other two lanes' products -0 (a +0 times
    # -1), only a lane that kept its -0 turns its output -0.
    n = [1.0, -1.0, -1.0, 0.0,
         -1.0, 1.0, -1.0, 0.0,
         -1.0, -1.0, 1.0, 0.0,
         -0.0, -0.0, -0.0, 1.0]
    o.v3("-0*n", emul_vector3(n, [-0.0, -0.0, -0.0]))


def s_rotate(o):
    o("scenario rotate")
    g = Rng(0x2468ace)
    base = g.mat(2.0)
    o("  base")
    o.mat(base)
    ident = mat_identity()
    for b in BAMS:
        o("  rotX %5d of identity" % b)
        o.mat(erotate_x(ident, b))
        o("  rotY %5d of identity" % b)
        o.mat(erotate_y(ident, b))
        o("  rotZ %5d of identity" % b)
        o.mat(erotate_z(ident, b))
        o("  rotX %5d of base" % b)
        o.mat(erotate_x(base, b))
        o("  rotZ %5d of base" % b)
        o.mat(erotate_z(base, b))


def s_translate(o):
    o("scenario translate")
    g = Rng(0x13572468)
    base = g.mat(2.0)
    for _ in range(6):
        v = g.vec3(50.0)
        o.v3("v", v)
        o("  createTranslation")
        o.mat(ecreate_translation(v))
        o("  translate base")
        o.mat(etranslate(base, v))


def s_axis(o):
    o("scenario axis")
    for i, ax in enumerate(AXES):
        for j in range(0, len(BAMS), 3):
            o("  axis %d bam %5d" % (i, BAMS[j]))
            o.mat(ecreate_axis_rotation([f32(c) for c in ax], BAMS[j]))


def s_lookat(o):
    o("scenario lookat")
    g = Rng(0xfeedface)
    for _ in range(12):
        eye = g.vec3(100.0)
        target = g.vec3(100.0)
        up = g.vec3(1.0)
        o.v3("eye", eye)
        o.v3("target", target)
        o.v3("up", up)
        o.mat(ecreate_lookat(eye, target, up))
    o("  canonical")
    o.mat(ecreate_lookat([0.0, 0.0, 10.0, 0.0], [0.0, 0.0, 0.0, 0.0],
                         [0.0, 1.0, 0.0, 0.0]))


def s_invert(o):
    o("scenario invert")
    g = Rng(0x0badf00d)
    for i in range(8):
        g.vec3(1.0)                       # the harness draws an axis it never uses
        base = g.mat(3.0)
        o("  invertTransform")
        o.mat(einvert_transformation(base))
        o("  invertRotation")
        o.mat(einvert_rotation(base))
        o("  orthonormalize")
        o.mat(eorthonormalize(base))
        rot = erotate_x(erotate_z(mat_identity(), (i * 8192) & 0xffff),
                        (i * 4096) & 0xffff)
        o("  invertTransform of rotation")
        o.mat(einvert_transformation(rot))
        o("  orthonormalize of rotation")
        o.mat(eorthonormalize(rot))


def s_vectors(o):
    o("scenario vectors")
    g = Rng(0xc0ffee)
    for _ in range(10):
        a = [g.f(50.0), g.f(50.0), g.f(50.0), g.f(1.0)]
        b = [g.f(50.0), g.f(50.0), g.f(50.0), g.f(1.0)]
        o.v4("from", a)
        o.v4("to", b)
        o.v4("dir", enormalized_direction(a, b))
        # eReflectVector is `jr ra`: the harness prints whatever was in the
        # destination, which is the direction it just computed.
        o.v4("reflect", enormalized_direction(a, b))
    for _ in range(10):
        m = g.mat(2.0)
        a = [g.f(20.0), g.f(20.0), g.f(20.0), g.f(2.0)]
        o.v4("v", a)
        o.v4("pers", erot_trans_pers(m, a))
        o("  clip %02x" % eget_clip_flags(a, m))
    ident = mat_identity()
    for i in range(-3, 4):
        o("  clipx %2d -> %02x"
          % (i, eget_clip_flags([float(i), 0.0, 0.0, 1.0], ident)))
        o("  clipy %2d -> %02x"
          % (i, eget_clip_flags([0.0, float(i), 0.0, 1.0], ident)))
        o("  clipz %2d -> %02x"
          % (i, eget_clip_flags([0.0, 0.0, float(i), 1.0], ident)))
    for _ in range(6):
        dst = g.mat(1.0)
        m = g.mat(2.0)
        v = g.vec3(3.0)
        o.v3("star v", v)
        o("  star")
        o.mat(evector_star_matrix(dst, v, m))


def s_poly(o):
    o("scenario poly")
    for name, poly in (("square", SQUARE), ("ell", ELL), ("bowtie", BOWTIE)):
        for j in range(-2, 13):
            for i in range(-2, 13):
                x = f32(float(i) * 0.5)
                y = f32(float(j) * 0.5)
                o("  %s %s %s -> %d"
                  % (name, g9(x), g9(y),
                     eis_point_in_poly((x, y), poly, len(poly))))
    for n in (0, 1, 2):
        o("  square n=%d -> %d" % (n, eis_point_in_poly((1.0, 1.0), SQUARE, n)))


SCENARIOS = [("sin", s_sin), ("basics", s_basics), ("rotate", s_rotate),
             ("translate", s_translate), ("axis", s_axis),
             ("lookat", s_lookat), ("invert", s_invert),
             ("vectors", s_vectors), ("poly", s_poly)]


def model():
    o = Out()
    for _name, fn in SCENARIOS:
        fn(o)
    return o.lines


# --------------------------------------------------------------- the harness


# A mutation can turn a loop into one with no exit. With no deadline here
# that mutant runs until something kills it and stalls the whole pass; the
# harness itself runs in well under a second.
HARNESS_TIMEOUT = 60


def run_c(exe):
    try:
        r = subprocess.run([str(exe)], capture_output=True,
                           timeout=HARNESS_TIMEOUT)
    except subprocess.TimeoutExpired:
        sys.exit("harness hung, killed after %d s" % HARNESS_TIMEOUT)
    if r.returncode != 0:
        sys.exit("harness failed (%d):%s%s"
                 % (r.returncode, NL, r.stderr.decode("latin-1")))
    lines = r.stdout.decode("latin-1").split(NL)[:-1]
    return [ln[:-1] if ln.endswith(chr(13)) else ln for ln in lines]


def diff(a, b, limit=40):
    d = [ln for ln in difflib.unified_diff(a, b, "port", "model",
                                           lineterm="", n=1)]
    n = len([ln for ln in d
             if ln[:1] in "+-" and not ln.startswith(("+++", "---"))])
    if limit and d:
        print(NL.join(d[:limit]))
        if len(d) > limit:
            print("... %d more diff lines" % (len(d) - limit))
    return d, n


# Each entry breaks one rule the model states. A survivor means the
# transcript never exercises that rule, which is a gap in the scenarios --
# unless the two arms are provably the same number, in which case it is an
# equivalent mutant and belongs nowhere near this list.
MUTATIONS = [
    ("eMulMatrix order", "bMulMatrix(o, m2, m1);", "bMulMatrix(o, m1, m2);"),
    ("eMulVector3 x without retail's +0", "    in.x = 0.0f + v->x;",
     "    in.x = v->x;"),
    ("eMulVector3 y without retail's +0", "    in.y = 0.0f + v->y;",
     "    in.y = v->y;"),
    ("eMulVector3 z without retail's +0", "    in.z = 0.0f + v->z;",
     "    in.z = v->z;"),
    ("sin 2pi loop to if", "while (E_TWO_PI < x) x = x - E_TWO_PI;",
     "if (E_TWO_PI < x) x = x - E_TWO_PI;"),
    ("sin negative loop to if", "while (x < 0.0f)     x = x + E_TWO_PI;",
     "if (x < 0.0f)     x = x + E_TWO_PI;"),
    ("sin pi fold strict", "if (E_PI <= x) {", "if (E_PI < x) {"),
    # The strict/non-strict variant of this one is an EQUIVALENT mutant and is
    # deliberately absent: pi and pi/2 have the same mantissa in the image, so
    # E_PI - E_HALF_PI is E_HALF_PI exactly and the fold is the identity at the
    # only input where the two spellings disagree. Dropping the fold is not.
    ("sin quadrant fold dropped", "    if (E_HALF_PI <= x) x = E_PI - x;",
     "    /* quadrant fold removed */"),
    ("sin c5 sign", "#define E_SIN_C5   0x1.110e7cp-7f",
     "#define E_SIN_C5   -0x1.110e7cp-7f"),
    ("sin c9 dropped", "    r = r + x9 * E_SIN_C9;", "    r = r + x9 * 0.0f;"),
    ("sin sum order", "    r = x + x3 * E_SIN_C3;\n    r = r + x5 * E_SIN_C5;",
     "    r = x + x5 * E_SIN_C5;\n    r = r + x3 * E_SIN_C3;"),
    ("rotate half-pi ulp", "#define E_ROT_HALF_PI  0x1.921fb8p+0f",
     "#define E_ROT_HALF_PI  0x1.921fb6p+0f"),
    ("rotX sin sign", "    r.v1.y = c;  r.v1.z = s;\n    r.v2.y = -s; r.v2.z = c;",
     "    r.v1.y = c;  r.v1.z = -s;\n    r.v2.y = s;  r.v2.z = c;"),
    ("rotY sin sign", "    r.v0.x = c;  r.v0.z = -s;",
     "    r.v0.x = c;  r.v0.z = s;"),
    ("rotZ sin sign", "    r.v0.x = c;  r.v0.y = s;\n    r.v1.x = -s; r.v1.y = c;",
     "    r.v0.x = c;  r.v0.y = -s;\n    r.v1.x = s;  r.v1.y = c;"),
    ("rotate order", "    eMulMatrix(o, m, &r);\n}\n\n// 0x0011c110.",
     "    eMulMatrix(o, &r, m);\n}\n\n// 0x0011c110."),
    ("bam to rad", "#define E_BAM_TO_RAD   0x1.921fb6p-14f",
     "#define E_BAM_TO_RAD   0x1.921fb4p-14f"),
    ("axis uses eSin", "    float c = bCosBam(bam);",
     "    float c = eSin((float)(int)bam * E_BAM_TO_RAD + E_ROT_HALF_PI);"),
    ("axis sy sign", "m->v0.z = kxz + sy; m->v0.w = 0.0f;",
     "m->v0.z = kxz - sy; m->v0.w = 0.0f;"),
    ("axis k", "    float k = 1.0f - c;", "    float k = 1.0f + c;"),
    ("axis w corner", "    m->v3.x = 0.0f; m->v3.y = 0.0f; m->v3.z = 0.0f; m->v3.w = 1.0f;",
     "    m->v3.x = 0.0f; m->v3.y = 0.0f; m->v3.z = 0.0f; m->v3.w = 0.0f;"),
    ("cross order", "    float x = a->y * b->z - b->y * a->z;",
     "    float x = b->y * a->z - a->y * b->z;"),
    ("normalize drops z", "    d = d + v->z * v->z;", "    d = d + 0.0f;"),
    ("lookat up not negated", "    negUp.x = 0.0f - up->x;", "    negUp.x = up->x;"),
    ("lookat rows not columns", "    rot.v0.x = right.x; rot.v0.y = newUp.x; rot.v0.z = dir.x;",
     "    rot.v0.x = right.x; rot.v0.y = right.y; rot.v0.z = right.z;"),
    ("lookat translate side", "    eMulMatrix(m, &trans, &tmp);",
     "    eMulMatrix(m, &tmp, &trans);"),
    ("invertTransform no transpose",
     "    rot.v0.x = m->v0.x; rot.v0.y = m->v1.x; rot.v0.z = m->v2.x; rot.v0.w = 0.0f;",
     "    rot.v0.x = m->v0.x; rot.v0.y = m->v0.y; rot.v0.z = m->v0.z; rot.v0.w = 0.0f;"),
    ("invertRotation keeps corner", "    o->v3.w = 0.0f;\n}", "    o->v3.w = 1.0f;\n}"),
    ("orthonormalize cross order", "    vu_cross(&y, &z, &x);",
     "    vu_cross(&y, &x, &z);"),
    ("orthonormalize skips second normalize", "    vu_normalize(&z);\n    vu_cross(&y, &z, &x);",
     "    vu_cross(&y, &z, &x);"),
    ("normalizedDirection gains z", "    float d = dx * dx + dy * dy;",
     "    float d = dx * dx + dy * dy + dz * dz;"),
    ("pers w from vector",
     "    float w = v->x * m->v0.w + v->y * m->v1.w + v->z * m->v2.w + m->v3.w;",
     "    float w = v->x * m->v0.w + v->y * m->v1.w + v->z * m->v2.w + v->w * m->v3.w;"),
    ("pers divides w too", "    t.x *= q; t.y *= q; t.z *= q;",
     "    t.x *= q; t.y *= q; t.z *= q; t.w *= q;"),
    ("clip not strict", "    if (t.x > w)  f |= 0x01u;", "    if (t.x >= w) f |= 0x01u;"),
    ("clip w not absolute", "    w = t.w < 0.0f ? -t.w : t.w;", "    w = t.w;"),
    ("clip bit order", "    if (t.z > w)  f |= 0x10u;", "    if (t.z > w)  f |= 0x20u;"),
    ("star sign", "    o->v0.x = -vz * m->v0.y + vy * m->v0.z;",
     "    o->v0.x = vz * m->v0.y + -vy * m->v0.z;"),
    ("star writes w", "    o->v0.z = -vy * m->v0.x + vx * m->v0.y;",
     "    o->v0.z = -vy * m->v0.x + vx * m->v0.y; o->v0.w = 0.0f;"),
    ("poly j starts at 0", "    int i, j = n - 1, inside = 0;",
     "    int i, j = 0, inside = 0;"),
    ("poly y test closed", "        if (((poly[i].y <= pt->y && pt->y < poly[j].y)) ||",
     "        if (((poly[i].y <= pt->y && pt->y <= poly[j].y)) ||"),
    ("poly x test strict", "            if (pt->x < t / (poly[j].y - poly[i].y) + poly[i].x)",
     "            if (pt->x <= t / (poly[j].y - poly[i].y) + poly[i].x)"),
    ("translation matrix row", "    m->v3.x = v->x;", "    m->v0.x = v->x;"),
]


# The write, its OneDrive retry, and the journal that lets a killed pass be
# recovered from are all hostbuild's.
write_source = hostbuild.write_source


def mutate_pass(py_lines):
    src = ROOT / "3DS Files" / "source" / "emath.c"
    # newline="" so the file's own line endings survive the round trip, and
    # the patterns are translated to match rather than the file to match the
    # patterns -- a universal-newlines read here would rewrite the source to
    # LF on every write, and a bare-newline pattern would miss a CRLF file
    # silently the other way round.
    original = src.read_text(encoding="utf-8", newline="")
    crlf = (chr(13) + NL) in original
    survived = []
    try:
        for name, old, new in MUTATIONS:
            if crlf:
                old = old.replace(NL, chr(13) + NL)
                new = new.replace(NL, chr(13) + NL)
            if old not in original:
                survived.append("%s (pattern gone: %r)" % (name, old))
                print("  %-34s PATTERN GONE" % name)
                continue
            write_source(src, original.replace(old, new, 1))
            with tempfile.TemporaryDirectory() as tmp:
                try:
                    exe = hostbuild.build(tmp, SOURCES, name="emath_test")
                except SystemExit:
                    print("  %-34s did not compile (counts as caught)" % name)
                    continue
                try:
                    got = run_c(exe)
                except SystemExit:
                    print("  %-34s crashed the harness (caught)" % name)
                    continue
            _d, bad = diff(got, py_lines, limit=0)
            if bad:
                print("  %-34s caught, %d lines" % (name, bad))
            else:
                print("  %-34s SURVIVED" % name)
                survived.append(name)
    finally:
        try:
            write_source(src, original)
        except OSError:
            sys.exit("could not restore %s -- it still holds a "
                     "mutation. Put the original line back before "
                     "trusting anything printed above." % src)
    return survived


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mutate", action="store_true",
                    help="break emath.c a rule at a time and re-diff")
    ap.add_argument("--dump", help="write both transcripts next to this path")
    a = ap.parse_args()

    ours = model()
    with tempfile.TemporaryDirectory() as tmp:
        exe = hostbuild.build(tmp, SOURCES, name="emath_test")
        port = run_c(exe)

    if a.dump:
        for tag, lines in (("port", port), ("model", ours)):
            with open("%s.%s.txt" % (a.dump, tag), "w", newline=NL) as fh:
                fh.write(NL.join(lines) + NL)

    _d, bad = diff(port, ours)
    print("%d scenarios, %d lines, %d differ"
          % (len(SCENARIOS), len(port), bad))
    rc = 1 if bad else 0

    if a.mutate:
        if bad:
            print("not mutating while the baseline differs")
            return rc
        print("mutations:")
        survived = mutate_pass(ours)
        print("%d mutations, %d survived" % (len(MUTATIONS), len(survived)))
        for s in survived:
            print("  SURVIVED: %s" % s)
        rc |= 1 if survived else 0
    return rc


if __name__ == "__main__":
    sys.exit(main())
