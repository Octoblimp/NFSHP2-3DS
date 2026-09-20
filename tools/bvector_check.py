#!/usr/bin/env python3
"""Cross-check the bVector, bMatrix and bQuaternion ports against a model.

tools/src/bvector_test.c drives the C in "3DS Files/source" and prints one
line per call. This file prints the same lines from a Python model written
off the disassembly -- bVector.obj at 0x00240198, bQuaternion.obj at
0x002411f0, bMatrix.obj at 0x002424f8 -- and not off the C. Then it diffs
them. Two independent readings of the same listing agreeing line for line is
the evidence; one reading checked against itself is not.

bMath.obj has its own pair (tools/bmath_check.py). The four routines this one
needs from it -- bSqrt32, bInverse, bASin, bSinBam -- are imported from that
model rather than copied, so there is one Python bSqrt32 in the tree and it
is the mutation-tested one.

Every arithmetic step goes through f32(), because the port is float32 and
Python is not: a model that let one intermediate stay double would drift in
the last bit and the diff would blame the port. Integers go through i32() for
the same reason, since the EE wraps where C would be undefined.

Usage:
    python tools/bvector_check.py
    python tools/bvector_check.py --scenario invert
    python tools/bvector_check.py --dump out.txt
"""
import argparse
import difflib
import math
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hostbuild
from bmath_check import f32, i32, u32, bSqrt32, bInverse, bASin, bSinBam

NL = chr(10)

SOURCES = [
    "tools/src/bvector_test.c",
    "3DS Files/source/bvector.c",
    "3DS Files/source/bmatrix.c",
    "3DS Files/source/bquat.c",
    "3DS Files/source/bmath.c",
    "3DS Files/source/bmathtab.c",
]

# ---------------------------------------------------------------- machine ops


def fmul(a, b):
    return f32(a * b)


def fadd(a, b):
    return f32(a + b)


def fsub(a, b):
    return f32(a - b)


def fdiv(a, b):
    return f32(a / b)


def fsqrt(x):
    return f32(math.sqrt(x))


def fneg(x):
    return f32(-x)


def fabs32(x):
    return f32(abs(x))


def add32(a, b):
    """addu."""
    return i32(a + b)


def sub32(a, b):
    """subu."""
    return i32(a - b)


def absw(x):
    """pmaxw x,x,-x -- wraps at INT32_MIN instead of trapping."""
    n = i32(-x)
    return n if n > x else x


def sqw(x):
    """mult/mult1 keeping only the low 32 bits."""
    return i32(x * x)


def bFixMul(a, b):
    """mult, then dsll 16 / dsra32 0 -- bits 16..47 of the 64-bit product."""
    return i32((a * b) >> 16)


FLT_MAX = f32(3.40282347e+38)

# ------------------------------------------------------------ bVector.obj


def bNormalize2(v):
    """0x00240198."""
    x, y = v
    ln = fsqrt(fadd(fmul(x, x), fmul(y, y)))
    if ln == 0.0:
        return (f32(1.0), f32(0.0))
    return (fdiv(x, ln), fdiv(y, ln))


def bNormalize2To(v, ln):
    """0x002401f0. The zero case ignores `ln` and writes (1, 0)."""
    x, y = v
    k = fdiv(fsqrt(fadd(fmul(x, x), fmul(y, y))), ln)
    if k == 0.0:
        return (f32(1.0), f32(0.0))
    return (fdiv(x, k), fdiv(y, k))


def bNormalize3To(v, ln):
    """0x00240250. VU0 sum, one reciprocal. Zero writes (ln, 0, 0)."""
    x, y, z = v
    n = fadd(fadd(fmul(x, x), fmul(y, y)), fmul(z, z))
    k = fdiv(fsqrt(n), ln)
    if k == 0.0:
        return (ln, f32(0.0), f32(0.0))
    r = fdiv(f32(1.0), k)
    return (fmul(x, r), fmul(y, r), fmul(z, r))


def bScaleAdd2(a, b, s):
    """0x002402d0."""
    return (fadd(a[0], fmul(b[0], s)), fadd(a[1], fmul(b[1], s)))


def bEqual2(a, b, eps):
    """0x00240300. `eps < |d|` fails, so exactly eps is still equal."""
    for i in range(2):
        if eps < fabs32(fsub(a[i], b[i])):
            return 0
    return 1


def bEqual3(a, b, eps):
    """0x00240350."""
    for i in range(3):
        if eps < fabs32(fsub(a[i], b[i])):
            return 0
    return 1


def box_init(n):
    """0x00240cb8 / 0x00240f20."""
    return [FLT_MAX] * n, [fneg(FLT_MAX)] * n


def box_init_at(p, n):
    """0x00240ce0 / 0x00240f40."""
    return list(p[:n]), list(p[:n])


def box_expand(mn, mx, p, n):
    """0x00240d00 / 0x00240f58."""
    for i in range(n):
        if p[i] < mn[i]:
            mn[i] = p[i]
    for i in range(n):
        if mx[i] < p[i]:
            mx[i] = p[i]


def box_expand_r(mn, mx, p, r, n):
    """0x00240d40 / 0x00240f80."""
    lo = [fsub(p[i], r) for i in range(n)]
    hi = [fadd(p[i], r) for i in range(n)]
    for i in range(n):
        if lo[i] < mn[i]:
            mn[i] = lo[i]
    for i in range(n):
        if mx[i] < hi[i]:
            mx[i] = hi[i]


def box_expand_box(mn, mx, lo, hi, n):
    """0x00240d90 / 0x00240fc0."""
    for i in range(n):
        if lo[i] < mn[i]:
            mn[i] = lo[i]
    for i in range(n):
        if mx[i] < hi[i]:
            mx[i] = hi[i]


def box_inside(mn, mx, p, eps, n):
    """0x00240dd8 / 0x00240ff0. The grown boundary counts as inside."""
    for i in range(n):
        if p[i] < fsub(mn[i], eps):
            return 0
        if fadd(mx[i], eps) < p[i]:
            return 0
    return 1


def box_contains(mn, mx, imn, imx, n):
    """0x00240e50 / 0x002410a0. Inclusive."""
    for i in range(n):
        if not mn[i] <= imn[i]:
            return 0
        if not imx[i] <= mx[i]:
            return 0
    return 1


def box_overlapping(mn, mx, omn, omx, n):
    """0x00240eb8 / 0x00241138. Exclusive."""
    for i in range(n):
        if not omn[i] < mx[i]:
            return 0
        if not mn[i] < omx[i]:
            return 0
    return 1


def prescale(total):
    """The shift loop at 0x00240400: signed compare, arithmetic shift."""
    s = 0
    if 0xffff < total:
        while True:
            s += 2
            if not 0xffff < (total >> s):
                break
    return s


def _lenfix(comps):
    """0x002403c0 / 0x00240448, both widths."""
    total = absw(comps[0])
    for c in comps[1:]:
        total = add32(total, absw(c))
    s = prescale(total)
    sh = [c >> s for c in comps]
    sq = sqw(sh[0])
    for c in sh[1:]:
        sq = add32(sq, sqw(c))
    return i32(bSqrt32(u32(sq)) << s)


def bLengthFix2(v):
    return _lenfix(list(v))


def bLengthFix3(v):
    return _lenfix(list(v))


def _distfix(a, b):
    """0x002404f0 / 0x00240580. A choice of two shifts, not the loop."""
    d = [sub32(a[i], b[i]) for i in range(len(a))]
    total = absw(d[0])
    for c in d[1:]:
        total = add32(total, absw(c))
    s = 16 if total > 0x00ffffff else 8
    sh = [c >> s for c in d]
    sq = sqw(sh[0])
    for c in sh[1:]:
        sq = add32(sq, sqw(c))
    return i32(bSqrt32(u32(sq)) << s)


def bDistBetweenFix2(a, b):
    return _distfix(a, b)


def bDistBetweenFix3(a, b):
    return _distfix(a, b)


def bScaleFix(v, s):
    """0x00240640 / 0x00240710."""
    return tuple(bFixMul(c, s) for c in v)


def bScaleAddFix(a, b, s):
    """0x002406a0 / 0x002407a0."""
    return tuple(add32(a[i], bFixMul(b[i], s)) for i in range(len(a)))


def bDotFix(a, b):
    """0x00240848 / 0x002408a8, summed left to right."""
    t = bFixMul(a[0], b[0])
    for i in range(1, len(a)):
        t = add32(t, bFixMul(a[i], b[i]))
    return t


def bCrossFix3(a, b):
    """0x00240938."""
    return (sub32(bFixMul(a[1], b[2]), bFixMul(a[2], b[1])),
            sub32(bFixMul(a[2], b[0]), bFixMul(a[0], b[2])),
            sub32(bFixMul(a[0], b[1]), bFixMul(a[1], b[0])))


def _normfix(comps):
    """0x00240a48 / 0x00240b58. The pre-scaled components are normalised
    against the pre-scaled length, so the shift cancels."""
    n = len(comps)
    total = absw(comps[0])
    for c in comps[1:]:
        total = add32(total, absw(c))
    s = prescale(total)
    sh = [c >> s for c in comps]
    sq = sqw(sh[0])
    for c in sh[1:]:
        sq = add32(sq, sqw(c))
    ln = i32(bSqrt32(u32(sq)))
    if ln == 0:
        return tuple([0x10000] + [0] * (n - 1))
    inv = bInverse(ln)
    return tuple(bFixMul(c, inv) for c in sh)


def bNormalizeFix2(v):
    return _normfix(list(v))


def bNormalizeFix3(v):
    return _normfix(list(v))


# ------------------------------------------------------------ bMatrix.obj

IDENTITY = [(f32(1.0), f32(0.0), f32(0.0), f32(0.0)),
            (f32(0.0), f32(1.0), f32(0.0), f32(0.0)),
            (f32(0.0), f32(0.0), f32(1.0), f32(0.0)),
            (f32(0.0), f32(0.0), f32(0.0), f32(1.0))]


def bIdentity():
    """0x002424f8 and 0x00242528."""
    return [r for r in IDENTITY]


def bInvertMatrix(m):
    """0x00242578. Adjugate over determinant, then the translation row.

    The three negated cofactors are multiplied by -k rather than negated
    after the fact (neg.s at 0x00242630), and the determinant is summed
    (a*ei_fh - b*di_fg) + c*dh_eg in that order.
    """
    a, b, c = m[0][0], m[0][1], m[0][2]
    d, e, f = m[1][0], m[1][1], m[1][2]
    g, h, i = m[2][0], m[2][1], m[2][2]
    tx, ty, tz = m[3][0], m[3][1], m[3][2]

    ei_fh = fsub(fmul(e, i), fmul(f, h))
    di_fg = fsub(fmul(d, i), fmul(f, g))
    dh_eg = fsub(fmul(d, h), fmul(e, g))

    det = fadd(fsub(fmul(a, ei_fh), fmul(b, di_fg)), fmul(c, dh_eg))
    k = fdiv(f32(1.0), det)
    nk = fneg(k)

    o00 = fmul(ei_fh, k)
    o01 = fmul(fsub(fmul(b, i), fmul(c, h)), nk)
    o02 = fmul(fsub(fmul(b, f), fmul(c, e)), k)
    o10 = fmul(di_fg, nk)
    o11 = fmul(fsub(fmul(a, i), fmul(c, g)), k)
    o12 = fmul(fsub(fmul(a, f), fmul(c, d)), nk)
    o20 = fmul(dh_eg, k)
    o21 = fmul(fsub(fmul(a, h), fmul(b, g)), nk)
    o22 = fmul(fsub(fmul(a, e), fmul(b, d)), k)

    o30 = fneg(fadd(fadd(fmul(tx, o00), fmul(ty, o10)), fmul(tz, o20)))
    o31 = fneg(fadd(fadd(fmul(tx, o01), fmul(ty, o11)), fmul(tz, o21)))
    o32 = fneg(fadd(fadd(fmul(tx, o02), fmul(ty, o12)), fmul(tz, o22)))

    return [(o00, o01, o02, f32(0.0)),
            (o10, o11, o12, f32(0.0)),
            (o20, o21, o22, f32(0.0)),
            (o30, o31, o32, f32(1.0))]


def rowmul(r, m):
    """vmulax / vmadday / vmaddaz / vmaddw: r.x*m0 + r.y*m1 + r.z*m2 + r.w*m3."""
    out = []
    for c in range(4):
        t = fmul(r[0], m[0][c])
        t = fadd(t, fmul(r[1], m[1][c]))
        t = fadd(t, fmul(r[2], m[2][c]))
        t = fadd(t, fmul(r[3], m[3][c]))
        out.append(t)
    return tuple(out)


def bMulMatrix(m1, m2):
    """0x002426f8. Each row of m2 transformed by m1."""
    return [rowmul(m2[i], m1) for i in range(4)]


def bMulMatrixVec4(m, v):
    """0x00242770."""
    return rowmul(v, m)


def bMulMatrixVec3(m, v):
    """0x002427b0. w forced to 1, so the translation row applies."""
    t = rowmul((v[0], v[1], v[2], f32(1.0)), m)
    return (t[0], t[1], t[2])


def bTransposeMatrix(m):
    """0x00242808."""
    return [tuple(m[r][c] for r in range(4)) for c in range(4)]


# -------------------------------------------------------- bQuaternion.obj


def _dot4(a, b):
    """The VU0 accumulate: ((x + y) + z) + w, always in that order."""
    t = fmul(a[0], b[0])
    t = fadd(t, fmul(a[1], b[1]))
    t = fadd(t, fmul(a[2], b[2]))
    t = fadd(t, fmul(a[3], b[3]))
    return t


def bLength(q):
    """0x00241728."""
    return fsqrt(_dot4(q, q))


def bNormalize(q):
    """0x00241758. VRSQRT in the original; 1/sqrt here."""
    k = fdiv(f32(1.0), fsqrt(_dot4(q, q)))
    return tuple(fmul(c, k) for c in q)


def bConjugate(q):
    """0x002416f0."""
    return (fneg(q[0]), fneg(q[1]), fneg(q[2]), q[3])


def bMult(a, b):
    """0x00241798. o.xyz = a*b.w + (b*a.w + a x b); o.w = a.w*b.w - dot3."""
    cx = fsub(fmul(a[1], b[2]), fmul(a[2], b[1]))
    cy = fsub(fmul(a[2], b[0]), fmul(a[0], b[2]))
    cz = fsub(fmul(a[0], b[1]), fmul(a[1], b[0]))

    dot = fadd(fadd(fmul(a[0], b[0]), fmul(a[1], b[1])), fmul(a[2], b[2]))
    w = fsub(fmul(a[3], b[3]), dot)

    tx = fadd(fmul(b[0], a[3]), cx)
    ty = fadd(fmul(b[1], a[3]), cy)
    tz = fadd(fmul(b[2], a[3]), cz)

    return (fadd(fmul(a[0], b[3]), tx),
            fadd(fmul(a[1], b[3]), ty),
            fadd(fmul(a[2], b[3]), tz),
            w)


SLERP_EPS = f32(0.0500000007)     # gp-26976 = 0x00322290, 0x3d4ccccd


def bSlerp(a, b, t):
    """0x00241570."""
    cs = _dot4(a, b)

    if SLERP_EPS < fsub(f32(1.0), fabs32(cs)):
        theta = (16384 - bASin(fabs32(cs))) & 0xffff
        sn = bSinBam(theta)
        th = f32(float(theta))
        ka = fdiv(bSinBam(int(fmul(fsub(f32(1.0), t), th)) & 0xffff), sn)
        kb = fdiv(bSinBam(int(fmul(t, th)) & 0xffff), sn)
    else:
        ka = fsub(f32(1.0), t)
        kb = t

    if cs < 0.0:
        ka = fneg(ka)

    return tuple(fadd(fmul(b[i], kb), fmul(a[i], ka)) for i in range(4))


def _mat_from(m00, m01, m02, m10, m11, m12, m20, m21, m22):
    z = f32(0.0)
    return [(m00, m01, m02, z),
            (m10, m11, m12, z),
            (m20, m21, m22, z),
            (z, z, z, f32(1.0))]


def bQuaternionGetMatrix(q):
    """0x002414b0. The two squares are summed, then subtracted from 1."""
    x, y, z, w = q
    x2, y2, z2 = fadd(x, x), fadd(y, y), fadd(z, z)

    xx2, yy2, zz2 = fmul(x, x2), fmul(y, y2), fmul(z, z2)
    wx2, wy2, wz2 = fmul(w, x2), fmul(w, y2), fmul(w, z2)
    xy2, xz2, yz2 = fmul(x, y2), fmul(x, z2), fmul(y, z2)

    sxy = fadd(xx2, yy2)
    sxz = fadd(xx2, zz2)
    syz = fadd(yy2, zz2)
    one = f32(1.0)

    return _mat_from(fsub(one, syz), fsub(xy2, wz2), fadd(xz2, wy2),
                     fadd(xy2, wz2), fsub(one, sxz), fsub(yz2, wx2),
                     fsub(xz2, wy2), fadd(yz2, wx2), fsub(one, sxy))


def bQuaternionToMatrix(q):
    """0x00241800. The same matrix, one square subtracted at a time."""
    x, y, z, w = q
    x2, y2, z2, w2 = fadd(x, x), fadd(y, y), fadd(z, z), fadd(w, w)

    xx2, yy2, zz2 = fmul(x2, x), fmul(y2, y), fmul(z2, z)
    wx2, wy2, wz2 = fmul(w2, x), fmul(w2, y), fmul(w2, z)
    xy2, xz2, yz2 = fmul(x2, y), fmul(x2, z), fmul(y2, z)

    one = f32(1.0)
    ax = fsub(one, xx2)
    ay = fsub(one, yy2)

    return _mat_from(fsub(ay, zz2), fsub(xy2, wz2), fadd(xz2, wy2),
                     fadd(xy2, wz2), fsub(ax, zz2), fsub(yz2, wx2),
                     fsub(xz2, wy2), fadd(yz2, wx2), fsub(ax, yy2))


NEXT = (1, 2, 0)      # 0x002a3060


def shepperd(m):
    """0x002411f0 and 0x002418c0, which are the same code twice."""
    a = [m[r][c] for r in range(4) for c in range(4)]
    half = f32(0.5)
    one = f32(1.0)

    trace = fadd(fadd(a[0], a[5]), a[10])
    if trace > 0.0:
        s = fsqrt(fadd(trace, one))
        w = fmul(s, half)
        k = fdiv(half, s)
        return (fmul(fsub(a[6], a[9]), k),
                fmul(fsub(a[8], a[2]), k),
                fmul(fsub(a[1], a[4]), k),
                w)

    i = 1 if a[0] < a[5] else 0
    if a[i * 5] < a[10]:
        i = 2
    j = NEXT[i]
    k = NEXT[j]

    s = fsqrt(fadd(fsub(a[i * 5], fadd(a[j * 5], a[k * 5])), one))
    q4 = [None] * 4
    q4[i] = fmul(s, half)
    if s != 0.0:
        s = fdiv(half, s)
    q4[3] = fmul(fsub(a[j * 4 + k], a[k * 4 + j]), s)
    q4[j] = fmul(fadd(a[i * 4 + j], a[j * 4 + i]), s)
    q4[k] = fmul(fadd(a[i * 4 + k], a[k * 4 + i]), s)
    return tuple(q4)


IDENTITY_Q = (f32(0.0), f32(0.0), f32(0.0), f32(1.0))     # 0x00315290

# ------------------------------------------------------------------ input

NUMS = (0, 1, -1, 2, 3, -5, 7, -11, 16, 33, -64, 128,
        255, -256, 1000, -1023, 4096, -8192, 65536, -100000, 123456, -987654,
        31, 17)
NNUM = len(NUMS)

FIXN = (0, 1, -1, 2, -3, 100, -1000, 0x8000, -0x8000, 0x10000, -0x10000,
        0x1234, -0x4321, 0x100000, -0x100000, 0x7fffff, -0x7fffff,
        0x1000000, -0x1000000, 0x20000000, -0x20000000, 0x7fffffff,
        -0x7fffffff, 12345678, -87654321, 65536000, 3, -7)
NFIX = len(FIXN)


def fv(k):
    return f32(float(NUMS[k % NNUM]) / 256.0)


def iv(k):
    return FIXN[k % NFIX]


def v2(k):
    return (fv(k), fv(k + 1))


def v3(k):
    return (fv(k), fv(k + 1), fv(k + 2))


def v3m(k):
    """Components far apart in the deck; adjacent ones never separate the
    two groupings of the length sum."""
    return (fv(k), fv(k + 10), fv(k + 14))


def v4(k):
    return (fv(k), fv(k + 1), fv(k + 2), fv(k + 3))


def f2(k):
    return (iv(k), iv(k + 1))


def f3(k):
    return (iv(k), iv(k + 1), iv(k + 2))


def mgen(k):
    return [v4(k), v4(k + 4), v4(k + 8), v4(k + 12)]


def uq(k):
    return bNormalize((fv(k), fv(k + 1), fv(k + 2), fadd(fv(k + 3), f32(1.0))))


def affine(k):
    q = uq(k)
    m = bQuaternionToMatrix(q)
    s = [fadd(fv(k + 6), f32(2.0)),
         fadd(fv(k + 7), f32(2.0)),
         fadd(fv(k + 8), f32(2.0))]
    for r in range(3):
        m[r] = (fmul(m[r][0], s[r]), fmul(m[r][1], s[r]),
                fmul(m[r][2], s[r]), m[r][3])
    m[3] = (fv(k + 9), fv(k + 10), fv(k + 11), m[3][3])
    return m


# --------------------------------------------------------------- printing

OUT = []


def emit(s):
    OUT.append(s)


def s2(v):
    return "(%.9g %.9g)" % (v[0], v[1])


def s3(v):
    return "(%.9g %.9g %.9g)" % (v[0], v[1], v[2])


def s4(v):
    return "(%.9g %.9g %.9g %.9g)" % (v[0], v[1], v[2], v[3])


def sm(m):
    return " ".join(s4(r) for r in m)


def sf2(v):
    return "(%d %d)" % (v[0], v[1])


def sf3(v):
    return "(%d %d %d)" % (v[0], v[1], v[2])


# -------------------------------------------------------------- scenarios


def s_fixmul():
    for x in FIXN:
        for y in FIXN:
            emit("fixmul %11d %11d -> %11d" % (x, y, bFixMul(x, y)))


def s_normalize2():
    z = (f32(0.0), f32(0.0))
    emit("normalize2 %s -> %s" % (s2(z), s2(bNormalize2(z))))
    for k in range(3 * NNUM):
        v = v2(k)
        emit("normalize2 %s -> %s" % (s2(v), s2(bNormalize2(v))))


def s_normalize2to():
    z = (f32(0.0), f32(0.0))
    for n in (1, 2, -3, 17, -1024):
        ln = f32(float(n) / 4.0)
        emit("normalize2to %s %.9g -> %s"
             % (s2(z), ln, s2(bNormalize2To(z, ln))))
        for k in range(2 * NNUM):
            v = v2(k)
            emit("normalize2to %s %.9g -> %s"
                 % (s2(v), ln, s2(bNormalize2To(v, ln))))


def s_normalize3to():
    z = (f32(0.0), f32(0.0), f32(0.0))
    for n in (1, 2, -3, 17, -1024):
        ln = f32(float(n) / 4.0)
        emit("normalize3to %s %.9g -> %s"
             % (s3(z), ln, s3(bNormalize3To(z, ln))))
        for k in range(2 * NNUM):
            v = v3(k)
            emit("normalize3to %s %.9g -> %s"
                 % (s3(v), ln, s3(bNormalize3To(v, ln))))
        for k in range(2 * NNUM):
            v = v3m(k)
            emit("normalize3tomix %s %.9g -> %s"
                 % (s3(v), ln, s3(bNormalize3To(v, ln))))


def s_scaleadd2():
    for k in range(2 * NNUM):
        a, b, s = v2(k), v2(k + 5), fv(k + 11)
        emit("scaleadd2 %s %s %.9g -> %s"
             % (s2(a), s2(b), s, s2(bScaleAdd2(a, b, s))))


def s_equal():
    for n in (0, 1, 4, 256, 65536):
        e = f32(float(n) / 256.0)
        for k in range(NNUM):
            a, b = v2(k), v2(k + 1)
            c, d = v3(k), v3(k + 1)
            emit("equal2 %s %s %.9g -> %d" % (s2(a), s2(b), e, bEqual2(a, b, e)))
            emit("equal2 %s %s %.9g -> %d" % (s2(a), s2(a), e, bEqual2(a, a, e)))
            emit("equal3 %s %s %.9g -> %d" % (s3(c), s3(d), e, bEqual3(c, d, e)))
            emit("equal3 %s %s %.9g -> %d" % (s3(c), s3(c), e, bEqual3(c, c, e)))


def _bbox(n, gen, sv, tag):
    mn, mx = box_init(n)
    emit("init%s -> %s %s" % (tag, sv(mn), sv(mx)))

    for k in range(NNUM):
        p = gen(k)
        box_expand(mn, mx, p, n)
        emit("expand%s %s -> %s %s" % (tag, sv(p), sv(mn), sv(mx)))

    for k in range(NNUM):
        p, r = gen(k + 3), fv(k + 7)
        box_expand_r(mn, mx, p, r, n)
        emit("expand%sr %s %.9g -> %s %s" % (tag, sv(p), r, sv(mn), sv(mx)))

    for k in range(NNUM):
        lo, hi = gen(k + 2), gen(k + 9)
        box_expand_box(mn, mx, lo, hi, n)
        emit("expand%sbox %s %s -> %s %s"
             % (tag, sv(lo), sv(hi), sv(mn), sv(mx)))

    for k in range(NNUM):
        a, b = gen(k), gen(k + 4)
        e = fv(k + 6)
        lo, hi = box_init_at(a, n)
        emit("init%sat %s -> %s %s" % (tag, sv(a), sv(lo), sv(hi)))

        box_expand(lo, hi, b, n)
        ilo, ihi = gen(k + 1), gen(k + 5)

        emit("inside%s %s %s %s %.9g -> %d"
             % (tag, sv(lo), sv(hi), sv(ilo), e,
                box_inside(lo, hi, ilo, e, n)))
        emit("contains%s %s %s %s %s -> %d"
             % (tag, sv(lo), sv(hi), sv(ilo), sv(ihi),
                box_contains(lo, hi, ilo, ihi, n)))
        emit("contains%sself %s %s -> %d"
             % (tag, sv(lo), sv(hi), box_contains(lo, hi, lo, hi, n)))
        emit("overlap%s %s %s %s %s -> %d"
             % (tag, sv(lo), sv(hi), sv(ilo), sv(ihi),
                box_overlapping(lo, hi, ilo, ihi, n)))
        emit("overlap%sself %s %s -> %d"
             % (tag, sv(lo), sv(hi), box_overlapping(lo, hi, lo, hi, n)))


def s_bbox2():
    _bbox(2, v2, s2, "2")


def s_bbox3():
    _bbox(3, v3, s3, "3")


def s_bbox2edge():
    alo, ahi = [0.0, 0.0], [2.0, 1.0]
    xlo, xhi = [2.0, 0.0], [3.0, 1.0]
    ylo, yhi = [0.0, 1.0], [2.0, 2.0]
    hix, lox = [3.0, 1.0], [-1.0, 0.0]

    emit("overlap2touchx -> %d" % box_overlapping(alo, ahi, xlo, xhi, 2))
    emit("overlap2touchxrev -> %d" % box_overlapping(xlo, xhi, alo, ahi, 2))
    emit("overlap2touchy -> %d" % box_overlapping(alo, ahi, ylo, yhi, 2))
    emit("overlap2touchyrev -> %d" % box_overlapping(ylo, yhi, alo, ahi, 2))
    emit("contains2edge -> %d" % box_contains(alo, ahi, alo, ahi, 2))
    emit("contains2past -> %d" % box_contains(alo, ahi, alo, xhi, 2))
    emit("inside2edge -> %d" % box_inside(alo, ahi, hix, f32(1.0), 2))
    emit("inside2past -> %d" % box_inside(alo, ahi, hix, f32(0.9375), 2))
    emit("inside2low -> %d" % box_inside(alo, ahi, lox, f32(1.0), 2))
    emit("inside2lowpast -> %d" % box_inside(alo, ahi, lox, f32(0.9375), 2))


def s_bbox3edge():
    alo, ahi = [0.0, 0.0, 0.0], [2.0, 1.0, 1.0]
    xlo, xhi = [2.0, 0.0, 0.0], [3.0, 1.0, 1.0]
    ylo, yhi = [0.0, 1.0, 0.0], [2.0, 2.0, 1.0]
    zlo, zhi = [0.0, 0.0, 1.0], [2.0, 1.0, 2.0]
    hix, lox = [3.0, 1.0, 1.0], [-1.0, 0.0, 0.0]

    emit("overlap3touchx -> %d" % box_overlapping(alo, ahi, xlo, xhi, 3))
    emit("overlap3touchxrev -> %d" % box_overlapping(xlo, xhi, alo, ahi, 3))
    emit("overlap3touchy -> %d" % box_overlapping(alo, ahi, ylo, yhi, 3))
    emit("overlap3touchyrev -> %d" % box_overlapping(ylo, yhi, alo, ahi, 3))
    emit("overlap3touchz -> %d" % box_overlapping(alo, ahi, zlo, zhi, 3))
    emit("overlap3touchzrev -> %d" % box_overlapping(zlo, zhi, alo, ahi, 3))
    emit("contains3edge -> %d" % box_contains(alo, ahi, alo, ahi, 3))
    emit("contains3past -> %d" % box_contains(alo, ahi, alo, xhi, 3))
    emit("inside3edge -> %d" % box_inside(alo, ahi, hix, f32(1.0), 3))
    emit("inside3past -> %d" % box_inside(alo, ahi, hix, f32(0.9375), 3))
    emit("inside3low -> %d" % box_inside(alo, ahi, lox, f32(1.0), 3))
    emit("inside3lowpast -> %d" % box_inside(alo, ahi, lox, f32(0.9375), 3))


def s_lengthfix():
    for k in range(4 * NFIX):
        a, b = f2(k), f3(k)
        emit("lengthfix2 %s -> %d" % (sf2(a), bLengthFix2(a)))
        emit("lengthfix3 %s -> %d" % (sf3(b), bLengthFix3(b)))


def s_distfix():
    for k in range(4 * NFIX):
        a, b = f2(k), f2(k + 5)
        c, d = f3(k), f3(k + 7)
        emit("distfix2 %s %s -> %d"
             % (sf2(a), sf2(b), bDistBetweenFix2(a, b)))
        emit("distfix3 %s %s -> %d"
             % (sf3(c), sf3(d), bDistBetweenFix3(c, d)))


def s_scalefix():
    for k in range(4 * NFIX):
        a, b, s = f2(k), f3(k), iv(k + 11)
        emit("scalefix2 %s %d -> %s" % (sf2(a), s, sf2(bScaleFix(a, s))))
        emit("scalefix3 %s %d -> %s" % (sf3(b), s, sf3(bScaleFix(b, s))))


def s_scaleaddfix():
    for k in range(4 * NFIX):
        a, b = f2(k), f2(k + 3)
        c, d = f3(k), f3(k + 4)
        s = iv(k + 13)
        emit("scaleaddfix2 %s %s %d -> %s"
             % (sf2(a), sf2(b), s, sf2(bScaleAddFix(a, b, s))))
        emit("scaleaddfix3 %s %s %d -> %s"
             % (sf3(c), sf3(d), s, sf3(bScaleAddFix(c, d, s))))


def s_dotfix():
    for k in range(4 * NFIX):
        a, b = f2(k), f2(k + 6)
        c, d = f3(k), f3(k + 9)
        emit("dotfix2 %s %s -> %d" % (sf2(a), sf2(b), bDotFix(a, b)))
        emit("dotfix3 %s %s -> %d" % (sf3(c), sf3(d), bDotFix(c, d)))


def s_crossfix():
    for k in range(4 * NFIX):
        a, b = f3(k), f3(k + 5)
        emit("crossfix3 %s %s -> %s" % (sf3(a), sf3(b), sf3(bCrossFix3(a, b))))


def s_normalizefix():
    for k in range(4 * NFIX):
        a, b = f2(k), f3(k)
        emit("normalizefix2 %s -> %s" % (sf2(a), sf2(bNormalizeFix2(a))))
        emit("normalizefix3 %s -> %s" % (sf3(b), sf3(bNormalizeFix3(b))))


def s_identity():
    emit("identity -> %s" % sm(bIdentity()))
    emit("oldidentity -> %s" % sm(bIdentity()))


def s_invert():
    for k in range(2 * NNUM):
        m = affine(k)
        emit("invert %s -> %s" % (sm(m), sm(bInvertMatrix(m))))


def s_mulmatrix():
    for k in range(2 * NNUM):
        m1, m2 = mgen(k), mgen(k + 5)
        emit("mulmatrix %s %s -> %s" % (sm(m1), sm(m2), sm(bMulMatrix(m1, m2))))
    for k in range(NNUM):
        m1, m2 = mgen(k), mgen(k + 5)
        emit("mulmatrixalias %s %s -> %s"
             % (sm(m1), sm(m2), sm(bMulMatrix(m1, m2))))


def s_mulvec():
    for k in range(2 * NNUM):
        m = mgen(k)
        a, b = v4(k + 3), v3(k + 7)
        emit("mulvec4 %s %s -> %s" % (sm(m), s4(a), s4(bMulMatrixVec4(m, a))))
        emit("mulvec3 %s %s -> %s" % (sm(m), s3(b), s3(bMulMatrixVec3(m, b))))


def s_transpose():
    for k in range(2 * NNUM):
        m = mgen(k)
        emit("transpose %s -> %s" % (sm(m), sm(bTransposeMatrix(m))))
        emit("transposeself %s -> %s" % (sm(m), sm(bTransposeMatrix(m))))


def s_qbasic():
    emit("identityq -> %s" % s4(IDENTITY_Q))
    for k in range(3 * NNUM):
        q = (fv(k), fv(k + 1), fv(k + 2), fadd(fv(k + 3), f32(1.0)))
        emit("qlength %s -> %.9g" % (s4(q), bLength(q)))
        emit("qnormalize %s -> %s" % (s4(q), s4(bNormalize(q))))
        emit("qconjugate %s -> %s" % (s4(q), s4(bConjugate(q))))
        emit("qconjugateself %s -> %s" % (s4(q), s4(bConjugate(q))))


def s_qmult():
    for k in range(3 * NNUM):
        a = (fv(k), fv(k + 1), fv(k + 2), fv(k + 3))
        b = (fv(k + 5), fv(k + 7), fv(k + 9), fv(k + 11))
        emit("qmult %s %s -> %s" % (s4(a), s4(b), s4(bMult(a, b))))
        emit("qmultrev %s %s -> %s" % (s4(b), s4(a), s4(bMult(b, a))))


def s_slerp():
    for k in range(2 * NNUM):
        a, b = uq(k), uq(k + 7)
        for n in (0, 1, 64, 128, 192, 255, 256, 300, -64):
            t = f32(float(n) / 256.0)
            emit("slerp %s %s %.9g -> %s"
                 % (s4(a), s4(b), t, s4(bSlerp(a, b, t))))

    for k in range(NNUM):
        a = uq(k)
        t = f32(float(k % 5) / 4.0)

        b = bNormalize((fadd(a[0], f32(fv(k) / 4096.0)), a[1], a[2], a[3]))
        emit("slerpnear %s %s %.9g -> %s"
             % (s4(a), s4(b), t, s4(bSlerp(a, b, t))))

        b = (fneg(a[0]), fneg(a[1]), fneg(a[2]), fneg(a[3]))
        emit("slerpanti %s %s %.9g -> %s"
             % (s4(a), s4(b), t, s4(bSlerp(a, b, t))))


def s_q2m():
    for k in range(3 * NNUM):
        q = uq(k)
        emit("getmatrix %s -> %s" % (s4(q), sm(bQuaternionGetMatrix(q))))
        emit("tomatrix %s -> %s" % (s4(q), sm(bQuaternionToMatrix(q))))
        r = (fv(k), fv(k + 2), fv(k + 4), fv(k + 6))
        emit("getmatrixraw %s -> %s" % (s4(r), sm(bQuaternionGetMatrix(r))))
        emit("tomatrixraw %s -> %s" % (s4(r), sm(bQuaternionToMatrix(r))))


def s_m2q():
    for k in range(3 * NNUM):
        m = bQuaternionToMatrix(uq(k))
        emit("frommatrix %s -> %s" % (sm(m), s4(shepperd(m))))
        emit("matrixtoq %s -> %s" % (sm(m), s4(shepperd(m))))

    diag = ((0, 0, 0), (-256, -256, -256), (-256, 0, -512),
            (-512, -256, 0), (0, -512, -256), (-1024, -1024, 256),
            (256, -1024, -1024), (-1024, 256, -1024))
    for i, d in enumerate(diag):
        m = mgen(i * 3)
        m[0] = (f32(float(d[0]) / 256.0),) + m[0][1:]
        m[1] = (m[1][0], f32(float(d[1]) / 256.0)) + m[1][2:]
        m[2] = m[2][:2] + (f32(float(d[2]) / 256.0), m[2][3])
        emit("matrixtoqdiag %s -> %s" % (sm(m), s4(shepperd(m))))


SCENARIOS = [
    ("fixmul", s_fixmul),
    ("normalize2", s_normalize2),
    ("normalize2to", s_normalize2to),
    ("normalize3to", s_normalize3to),
    ("scaleadd2", s_scaleadd2),
    ("equal", s_equal),
    ("bbox2", s_bbox2),
    ("bbox2edge", s_bbox2edge),
    ("bbox3", s_bbox3),
    ("bbox3edge", s_bbox3edge),
    ("lengthfix", s_lengthfix),
    ("distfix", s_distfix),
    ("scalefix", s_scalefix),
    ("scaleaddfix", s_scaleaddfix),
    ("dotfix", s_dotfix),
    ("crossfix", s_crossfix),
    ("normalizefix", s_normalizefix),
    ("identity", s_identity),
    ("invert", s_invert),
    ("mulmatrix", s_mulmatrix),
    ("mulvec", s_mulvec),
    ("transpose", s_transpose),
    ("qbasic", s_qbasic),
    ("qmult", s_qmult),
    ("slerp", s_slerp),
    ("q2m", s_q2m),
    ("m2q", s_m2q),
]


def model(names):
    del OUT[:]
    for name, fn in SCENARIOS:
        if names and name not in names:
            continue
        emit("scenario " + name)
        fn()
    return NL.join(OUT) + NL


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", action="append",
                    help="run only this scenario (repeatable)")
    ap.add_argument("--dump", help="write both transcripts next to this path")
    args = ap.parse_args()

    names = args.scenario or []
    known = [s[0] for s in SCENARIOS]
    for n in names:
        if n not in known:
            sys.exit("unknown scenario: %s" % n)

    with tempfile.TemporaryDirectory() as tmp:
        exe = hostbuild.build(tmp, SOURCES, name="bvector_test")
        r = subprocess.run([str(exe)] + names, capture_output=True, text=True)
        if r.returncode != 0:
            sys.exit("harness failed (%d):%s%s" % (r.returncode, NL, r.stderr))
        port = r.stdout.replace(chr(13) + NL, NL)

    ours = model(names)

    if args.dump:
        with open(args.dump + ".port.txt", "w", newline=NL) as fh:
            fh.write(port)
        with open(args.dump + ".model.txt", "w", newline=NL) as fh:
            fh.write(ours)

    a = port.splitlines()
    b = ours.splitlines()
    diff = [ln for ln in difflib.unified_diff(a, b, "port", "model",
                                              lineterm="", n=1)]
    n = len([ln for ln in diff
             if ln[:1] in "+-" and not ln.startswith(("+++", "---"))])
    count = len(names) if names else len(SCENARIOS)
    print("%d scenarios, %d lines, %d differ" % (count, len(a), n))
    if diff:
        print(NL.join(diff[:120]))
        if len(diff) > 120:
            print("... %d more diff lines" % (len(diff) - 120))
    return 1 if diff else 0


if __name__ == "__main__":
    sys.exit(main())
