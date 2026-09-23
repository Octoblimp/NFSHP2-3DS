#!/usr/bin/env python3
r"""Cross-check the bware math library against a second implementation.

`3DS Files/source/bmath.c` is the port of `bMath.obj` -- integer reciprocal
and divide, a restoring square root, the xorshift random, two floored
modulos, and the table- and series-driven trigonometry the rest of the engine
is built on. This file is those nineteen functions written again, in Python,
from the disassembly at 0x00241bc8 rather than from the C. Both run the same
sweeps and print the same transcript; the diff is the test.

Why bother, when the C is a transcription of the same listing:

  * The trig is not sinf. `bSin` is a five-term Taylor series over an angle
    quantised to 1/65536 of a turn and it overshoots -- 1.00000358 at the
    peak. `bFixSin` interpolates a Q15 table and tops out at 65534. `bASin`
    walks twelve octaves of a 192-entry secant table. Every one of those is a
    place where a "cleaner" implementation would be wrong, and the only way
    to be sure the port is not cleaner is to write it twice.

  * The operation order is load-bearing. float32 addition is not
    associative, and the original computes things like `(1 - x*x/2) + x^4/24`
    in an order the scheduler picked. Both sides here follow the listing, so
    a reordering shows up as a diff rather than as a last-bit shrug.

  * The fixed-point paths wrap. `bDiv` shifts a 64-bit product left by 16 and
    then right by 32, throwing away the top sixteen bits on the way; `bSqrt32`
    keeps twice the root in its accumulator. Both are modelled literally.

The tables are read straight out of NFSHP2.ELF here, while the port reads
them from `bmathtab.c`, which `tools/gen_bmath_tables.py` wrote from the same
ELF. The `tables` scenario compares the two, so a bad generator run is a diff
and not a silent shift of every angle in the game.

What this does NOT model is the EE FPU's departures from IEEE -- it has no
denormals, no infinities and no NaN, and it saturates where a host would
overflow. The sweeps stay inside the normal range, where the two agree.

The --mutate pass covers bToPolar, the last of the nineteen to be ported
(Session 25). The twelve mutations that held the other eighteen to the
transcript in Session 12 ran from a scratchpad script that was not kept.

Usage:
    python tools/bmath_check.py
    python tools/bmath_check.py --scenario asin
    python tools/bmath_check.py --dump out.txt
    python tools/bmath_check.py --mutate
"""
import argparse
import difflib
import math
import os
import struct
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hostbuild
import mipsdis

NL = chr(10)

SOURCES = [
    "tools/src/bmath_test.c",
    "3DS Files/source/bmath.c",
    "3DS Files/source/bmathtab.c",
]

# ---------------------------------------------------------------- machine ops


def f32(x):
    """Round a Python float to float32, the way every EE FPU op does."""
    return struct.unpack("<f", struct.pack("<f", x))[0]


def bits(w):
    """A float32 from its bit pattern -- how the ELF's constants are read."""
    return struct.unpack("<f", struct.pack("<I", w))[0]


def u32(x):
    return x & 0xffffffff


def i32(x):
    x &= 0xffffffff
    return x - (1 << 32) if x & 0x80000000 else x


def sdiv(a, b):
    """MIPS `div`: quotient truncated toward zero, not floored."""
    q = abs(a) // abs(b)
    return -q if (a < 0) != (b < 0) else q


def trunc32(x):
    """cvt.w.s -- truncate toward zero into an int32."""
    return int(x)


# --------------------------------------------------------------- ELF constants

ELF = mipsdis.Elf()

# The gp-relative pool bSin reads, at 0x00322294. bSinCos has its own copy at
# 0x003222bc; they are byte-identical where they overlap, and the four terms
# only bSinCos uses sit in the gaps.
C_BAM_TO_RAD = bits(0x38c90fdb)
C_3PI_2 = bits(0x4096cbe4)
C_2PI = bits(0x40c90fdb)
C_PI_2 = bits(0x3fc90fdb)
C_PI = bits(0x40490fdb)
C_1_6 = bits(0x3e2aaaab)
C_1_24 = bits(0x3d2aaaab)
C_1_120 = bits(0x3c088889)
C_1_720 = bits(0x3ab60b61)
C_1_5040 = bits(0x39500d01)
C_1_40320 = bits(0x37d00d01)
C_1_362880 = bits(0x3638ef1d)
C_1_3628800 = bits(0x3493f27e)
C_RAD_TO_BAM = bits(0x4622f983)

SIN_TABLE = list(struct.unpack("<513h", ELF.read(0x00315928, 1026)))
ATAN_LOW = list(struct.unpack("<129H", ELF.read(0x00315d30, 258)))
ATAN_HIGH = list(struct.unpack("<129H", ELF.read(0x00315e38, 258)))
# 209 entries, not 192: bASin's `oct >= 11` loop exit produces buckets
# 16..31 against octave eleven's base, so it indexes up to 207.
_asin_raw = ELF.read(0x003152a0, 209 * 8)
ASIN_TABLE = [struct.unpack_from("<HHf", _asin_raw, i * 8) for i in range(209)]

# Every constant above must be exactly what the ELF holds at the gp offsets
# bSin and bSinCos use; if a future edit fat-fingers one, fail loudly rather
# than print 2219 subtly wrong lines.
_pool = struct.unpack("<14f", ELF.read(0x00322294, 56))
assert _pool == (C_BAM_TO_RAD, C_3PI_2, C_2PI, C_PI_2, C_PI, C_1_6, C_1_120,
                 C_1_5040, C_1_362880, C_RAD_TO_BAM, C_BAM_TO_RAD, C_3PI_2,
                 C_2PI, C_PI_2), _pool
_pool2 = struct.unpack("<7f", ELF.read(0x003222d0, 28))
assert _pool2 == (C_1_6, C_1_24, C_1_120, C_1_720, C_1_5040, C_1_40320,
                  C_1_362880), _pool2


# ---------------------------------------------------------------- the library


def bInverse(x):
    """0x00241bc8."""
    if x == 0:
        return 0x7fffffff
    return i32(u32(sdiv(0x7fffffff, x)) << 1)


def bDiv(a, b):
    """0x00241bf8."""
    if b == 0:
        if a == 0:
            return 0
        return 0x7fffffff if a > 0 else -0x80000000
    p = a * sdiv(0x7fffffff, b)
    # dsll 16 then dsra32 0: the left shift is a 64-bit one and drops the top
    # sixteen bits of the product before the arithmetic right shift sees them.
    w = (p << 16) & 0xffffffffffffffff
    if w & 0x8000000000000000:
        w -= 1 << 64
    return i32(u32(i32(w >> 32)) << 1)


def bSqrt32(n):
    """0x00241c68. The accumulator carries twice the root; the final shift
    halves it. The `r <<= 1` really does sit between the two halves of the
    remainder update."""
    r = 0
    rem = 0
    for _ in range(16):
        hi = u32(rem << 2)
        r = u32(r << 1)
        t = u32(hi + (n >> 30))
        if r < t:
            rem = u32(t - r - 1)
            r = u32(r + 2)
        else:
            rem = t
        n = u32(n << 2)
    return r >> 1


class Rand(object):
    """The one-word generator, held in a box so the seed can be passed by
    reference the way the original passes a pointer."""

    def __init__(self, seed=0):
        self.seed = u32(seed)

    def randi(self, rng):
        """0x00241cc8. The value handed back is the OLD seed reduced mod
        range; the state moves afterwards."""
        s = self.seed
        if rng == 0:
            return 0            # the original traps here; the port returns 0
        t = u32(s ^ 0x1d872b41)
        u = u32(t ^ (t >> 5))
        v = u32(t ^ u32(u << 27))
        self.seed = u32(u ^ v)
        return i32(s % u32(rng))

    def setseed(self, s):
        """0x00241cb8 -- falls through into randi(1), so it always returns 0
        AND it advances the state past the value just stored."""
        self.seed = u32(s)
        return self.randi(1)

    def randf(self, f):
        """0x00241d08."""
        r = self.randi(0x7fffffff)
        k = f32(f * bits(0x30000000))       # 2**-31
        if r < 0:
            # Unreachable, but the original carries gcc's unsigned fixup.
            h = (u32(r) >> 1) | (u32(r) & 1)
            t = f32(float(i32(h)))
            return f32(k * f32(t + t))
        return f32(k * f32(float(r)))


def bFMod(a, b):
    """0x00241d80. Floored, so the result is in [0, |b|)."""
    m = f32(abs(b))
    q = f32(a / m)
    t = f32(float(trunc32(q)))
    if q < t:
        t = f32(t - 1.0)
    q = f32(q - t)
    return f32(q * m)


def bSignedMod(a, b):
    """0x00241dc0. Floored too, with the wart that an exact negative multiple
    comes back as |b| rather than 0."""
    nb = i32(0 - u32(b))
    m = nb if nb > b else b             # pmaxw b,b,-b
    if m == 0:
        return 0                        # the original traps here
    p = i32(u32(sdiv(a, m)) * u32(m))
    if a < 0:
        p = i32(p - m)
    return i32(a - p)


def _reduce(bam):
    """The quadrant fold both bSin and bSinCos open with: an angle in
    [0, 2pi) shifted into [-pi/2, pi/2) with a sign to carry back out."""
    x = f32(float(bam & 0xffff) * C_BAM_TO_RAD)
    sign = 1.0
    if C_3PI_2 <= x:
        x = f32(x - C_2PI)
    elif C_PI_2 <= x:
        sign = -1.0
        x = f32(x - C_PI)
    return x, sign


def bSinBam(bam):
    """0x00241df8. Five terms, and it overshoots to 1.00000358 at the peak."""
    x, sign = _reduce(bam)
    x2 = f32(x * x)
    x3 = f32(x * x2)
    x5 = f32(x3 * x2)
    x7 = f32(x5 * x2)
    x9 = f32(x7 * x2)
    r = f32(x - f32(x3 * C_1_6))
    r = f32(r + f32(x5 * C_1_120))
    r = f32(r - f32(x7 * C_1_5040))
    r = f32(r + f32(x9 * C_1_362880))
    return f32(r * sign)


def bSinF(rad):
    """0x00241e98."""
    return bSinBam(trunc32(f32(rad * C_RAD_TO_BAM)) & 0xffff)


def bCosBam(bam):
    """0x00241ec8."""
    return bSinBam((bam + 16384) & 0xffff)


def bSinCos(bam):
    """0x00241ef8. Same fold, then the two series interleaved -- and both
    results take the same sign, because the fold's pi shift negates sine and
    cosine alike."""
    x, sign = _reduce(bam)
    x2 = f32(x * x)
    x3 = f32(x * x2)
    x4 = f32(x2 * x2)
    x5 = f32(x3 * x2)
    x6 = f32(x4 * x2)
    x7 = f32(x5 * x2)
    x8 = f32(x6 * x2)
    x9 = f32(x7 * x2)
    x10 = f32(x8 * x2)

    rc = f32(1.0 - f32(x2 * 0.5))
    rs = f32(x - f32(x3 * C_1_6))
    rc = f32(rc + f32(x4 * C_1_24))
    rs = f32(rs + f32(x5 * C_1_120))
    rc = f32(rc - f32(x6 * C_1_720))
    rs = f32(rs - f32(x7 * C_1_5040))
    rc = f32(rc + f32(x8 * C_1_40320))
    rs = f32(rs + f32(x9 * C_1_362880))
    rc = f32(rc - f32(x10 * C_1_3628800))
    return f32(rs * sign), f32(rc * sign)


def bASin(x):
    """0x00242000. Twelve octaves of sixteen buckets, linearly interpolated.

    The octave walk looks like a binary search and is not one: it only ever
    adds, and the loop undoes its last step on the way out."""
    neg = 0
    if x < 0.0:
        x = f32(-x)
        neg = 1
    if 1.0 <= x:
        return 0xc000 if neg else 16384

    v = trunc32(f32(x * 65536.0))
    oct_ = 0
    width = 0x8000
    base = 0x8000
    if v < base:
        base = 0                        # and width stays 0x8000
    else:
        width >>= 1
        while True:
            base += width
            oct_ += 1
            if v < base:
                base -= width
                break
            if oct_ >= 11:
                base -= width
                break
            width >>= 1

    bucket = (v - base) >> (11 - oct_)
    lo = base + i32(u32(bucket) * u32(width >> 4))
    angle, _pad, slope = ASIN_TABLE[(oct_ << 4) + bucket]
    d = f32(f32(f32(x - f32(float(lo) * bits(0x37800000))) * slope) * 65536.0)
    r = i32(angle + trunc32(d))
    if neg:
        r = i32(0 - u32(r))
    return r & 0xffff


def _quadrant(q, r):
    """The four-case fixup bATan and bFixATan2 share."""
    if q == 0:
        return r & 0xffff
    if q == 1:
        return (0x8000 - r) & 0xffff
    if q == 2:
        return (r - 0x8000) & 0xffff
    return (0 - r) & 0xffff


def bATan(x, y):
    """0x00242148. atan2(y, x) in BAM -- x first. The magnitude is one bASin
    of the smaller leg over the hypotenuse, which keeps the argument inside
    the table's good range."""
    q = 1 if x < 0.0 else 0
    if y < 0.0:
        q ^= 3
    if abs(y) < abs(x):
        if y == 0.0:
            arg = 0.0
        else:
            h = f32(math.sqrt(f32(f32(y * y) + f32(x * x))))
            arg = f32(f32(abs(y)) / h)
        r = bASin(arg)
    else:
        if x == 0.0:
            arg = 0.0
        else:
            h = f32(math.sqrt(f32(f32(y * y) + f32(x * x))))
            arg = f32(f32(abs(x)) / h)
        r = (16384 - bASin(arg)) & 0xffff
    return _quadrant(q, r)


def bFixSin(bam):
    """0x00242268. The table is Q15 and both taps are doubled before the
    lerp, so "1.0" comes back as 65534."""
    a = bam & 0xffff
    i = a >> 7
    frac = (a << 9) & 0xffff
    lo = i32(SIN_TABLE[i] << 1)
    hi = i32(SIN_TABLE[i + 1] << 1)
    return i32(lo + (i32(u32(hi - lo) * u32(frac)) >> 16))


def bFixSinCos(bam):
    """0x002422b0."""
    return bFixSin(bam), bFixSin((bam + 16384) & 0xffff)


def bFixATan1(t):
    """0x00242308. Two interpolated tables, then a linear ramp from atan(32)
    to atan(256), then saturation. The seam where the tables hand over to the
    ramp is a fifth of a degree wide and is in the shipped code."""
    neg = 0
    if t < 0:
        neg = 1
        t = i32(0 - u32(t))

    if t > 0x001fffff:
        if t > 0x00ffffff:
            lo = 16383
            hi = 16383
            frac = 0
        else:
            lo = 16058                  # ATAN_HIGH[128], atan(32)
            hi = 16343                  # atan(256)
            frac = t >> 8
    elif t > 0x0003ffff:
        i = t >> 14
        lo = ATAN_HIGH[i]
        hi = ATAN_HIGH[i + 1]
        frac = (t << 2) & 0xffff
    else:
        i = t >> 11
        lo = ATAN_LOW[i]
        hi = ATAN_LOW[i + 1]
        frac = (t << 5) & 0xffff

    r = i32(lo + (i32(u32(hi - lo) * u32(frac)) >> 16))
    if neg:
        r = i32(0 - u32(r))
    return r & 0xffff


def bFixATan2(x, y):
    """0x002423e0. x first again. The (|y| >> 14) < |x| test is an overflow
    guard on bDiv, not a precision one -- past it the answer is pinned at 90
    degrees."""
    q = 1 if x < 0 else 0
    if y < 0:
        q ^= 3
    if x < 0:
        x = i32(0 - u32(x))
    if y < 0:
        y = i32(0 - u32(y))
    r = bFixATan1(bDiv(y, x)) if (y >> 14) < x else 16384
    return _quadrant(q, r)


def bToPolar(x, y):
    """0x002424a0. `mul.s` each component by itself, `add.s` x's square to
    y's, `sqrt.s`; then bATan(x, y) with the components still in $f12 and
    $f13. Returns (radius, angle)."""
    r = f32(math.sqrt(f32(f32(x * x) + f32(y * y))))
    return r, bATan(x, y)


# ------------------------------------------------------------------ scenarios

OUT = []


def emit(s):
    OUT.append(s)


def dy(num, shift):
    """The harness's float-from-a-dyadic-rational, bit for bit."""
    return f32(f32(float(num)) / f32(float(1 << shift)))


def s_inverse():
    for v in (0, 1, -1, 2, -2, 3, -3, 4, 7, 10, 16, 100, 255, 256, 1000, 4096,
              65535, 65536, 1000000, 0x10000000, 0x40000000, 0x7fffffff,
              -7, -100, -65536, -0x40000000, -0x7fffffff):
        emit("inverse %11d -> %11d" % (v, bInverse(v)))


def s_div():
    ns = (0, 1, -1, 2, -2, 5, -5, 100, -100, 65536, -65536, 1000000,
          0x7fffffff, -0x7fffffff)
    ds = (0, 1, -1, 2, -2, 3, 7, -7, 100, 256, 65536, -65536, 0x7fffffff)
    for a in ns:
        for b in ds:
            emit("div %11d %11d -> %11d" % (a, b, bDiv(a, b)))


def s_sqrt32():
    for n in range(41):
        emit("sqrt32 %10d -> %10d" % (n, bSqrt32(n)))
    for k in range(32):
        u = 1 << k
        for n in (u - 1, u, u + 1):
            n = u32(n)
            emit("sqrt32 %10d -> %10d" % (n, bSqrt32(n)))
    for k in range(1, 65):
        sq = u32(u32(k * 1013) * u32(k * 1013))
        for n in (u32(sq - 1), sq, u32(sq + 1)):
            emit("sqrt32 %10d -> %10d" % (n, bSqrt32(n)))
    for n in (0xfffffffe, 0xffffffff):
        emit("sqrt32 %10d -> %10d" % (n, bSqrt32(n)))


def s_random():
    for s in (0, 1, 12345, 0xdeadbeef, 0xffffffff):
        for rng in (0, 1, 2, 6, 100, 65536, 0x7fffffff):
            g = Rand()
            r0 = g.setseed(s)
            emit("seed %10d range %11d -> setret %d state %10d"
                 % (s, rng, r0, g.seed))
            for _ in range(6):
                r = g.randi(rng)
                emit("  randi -> %11d state %10d" % (r, g.seed))


def s_randomf():
    for s in (0, 7, 0x5f3759df):
        for sc in (0, 1, 2, -1, 100, 4096):
            g = Rand()
            f = dy(sc, 0)
            g.setseed(s)
            emit("seedf %10d scale %.9g" % (s, f))
            for _ in range(5):
                r = g.randf(f)
                emit("  randf -> %.9g state %10d" % (r, g.seed))


def s_fmod():
    for a in (0, 1, -1, 7, -7, 64, -64, 100, -100, 1000, -1000, 12345, -12345):
        for b in (1, -1, 2, -2, 6, -6, 64, 360, -360):
            x = dy(a, 2)
            y = dy(b, 0)
            emit("fmod %.9g %.9g -> %.9g" % (x, y, bFMod(x, y)))


def s_signedmod():
    for a in (0, 1, -1, 2, -2, 5, -5, 6, -6, 7, -7, 12, -12, 100, -100,
              0x7fffffff, -0x7fffffff):
        for b in (0, 1, -1, 2, -2, 3, -3, 6, 360, -360, 65536):
            emit("smod %11d %11d -> %11d" % (a, b, bSignedMod(a, b)))


EDGE_BAM = (0, 1, 16383, 16384, 16385, 24575, 24576, 24577,
            32767, 32768, 32769, 49151, 49152, 49153, 65534, 65535)


def bam_sweep(fn):
    for k in range(257):
        fn((k * 256) & 0xffff)      # the harness's (uint16_t) cast; k=256 wraps
    for b in EDGE_BAM:
        fn(b)


def s_sin():
    bam_sweep(lambda b: emit("sin %5d -> %.9g" % (b, bSinBam(b))))


def s_cos():
    bam_sweep(lambda b: emit("cos %5d -> %.9g" % (b, bCosBam(b))))


def s_sincos():
    def one(b):
        s, c = bSinCos(b)
        emit("sincos %5d -> %.9g %.9g" % (b, s, c))
    bam_sweep(one)


def s_fixsin():
    bam_sweep(lambda b: emit("fixsin %5d -> %11d" % (b, bFixSin(b))))


def s_fixsincos():
    def one(b):
        s, c = bFixSinCos(b)
        emit("fixsincos %5d -> %11d %11d" % (b, s, c))
    bam_sweep(one)


def s_sinf():
    for k in range(-64, 65):
        x = dy(k, 4)
        emit("sinf %.9g -> %.9g" % (x, bSinF(x)))
    for k in range(-256, 257):
        x = dy(k, 2)
        emit("sinf %.9g -> %.9g" % (x, bSinF(x)))


def s_asin():
    for k in range(-256, 257):
        x = dy(k, 8)
        emit("asin %.9g -> %11d" % (x, bASin(x)))
    for k in range(-256, 256):
        x = dy(2 * k + 1, 9)
        emit("asin %.9g -> %11d" % (x, bASin(x)))
    for k in range(1, 65):
        x = dy(65536 - k, 16)
        emit("asin %.9g -> %11d" % (x, bASin(x)))
        emit("asin %.9g -> %11d" % (-x, bASin(-x)))
    for num, sh in ((257, 8), (-257, 8), (64, 4)):
        x = dy(num, sh)
        emit("asin %.9g -> %11d" % (x, bASin(x)))


def s_atan():
    for ix in range(-8, 9):
        for iy in range(-8, 9):
            x = dy(ix, 2)
            y = dy(iy, 2)
            emit("atan %.9g %.9g -> %11d" % (x, y, bATan(x, y)))
    for ix in range(1, 13):
        big = dy(1 << ix, 0)
        emit("atan %.9g %.9g -> %11d" % (big, 1.0, bATan(big, 1.0)))
        emit("atan %.9g %.9g -> %11d" % (1.0, big, bATan(1.0, big)))
        emit("atan %.9g %.9g -> %11d" % (-big, 1.0, bATan(-big, 1.0)))
        emit("atan %.9g %.9g -> %11d" % (1.0, -big, bATan(1.0, -big)))


def s_fixatan1():
    for k in range(97):
        t = k * 0x5555
        emit("fatan1 %11d -> %11d" % (t, bFixATan1(t)))
        emit("fatan1 %11d -> %11d" % (-t, bFixATan1(-t)))
    for k in range(65):
        t = 0x40000 + k * 0x7000
        emit("fatan1 %11d -> %11d" % (t, bFixATan1(t)))
    for k in range(33):
        t = 0x200000 + k * 0x70000
        emit("fatan1 %11d -> %11d" % (t, bFixATan1(t)))
    for t in (0, 1, 0x7ff, 0x800, 0x801, 0x3ffff, 0x40000, 0x40001,
              0x3fff, 0x4000, 0x1ffffe, 0x1fffff, 0x200000, 0x200001,
              0xfffffe, 0xffffff, 0x1000000, 0x1000001, 0x7fffffff):
        emit("fatan1 %11d -> %11d" % (t, bFixATan1(t)))
        emit("fatan1 %11d -> %11d" % (-t, bFixATan1(-t)))


def s_fixatan2():
    vs = (0, 1, -1, 0x10000, -0x10000, 0x20000, -0x20000, 0x80000, -0x80000,
          0x400000, -0x400000, 0x10000000, -0x10000000)
    for x in vs:
        for y in vs:
            emit("fatan2 %11d %11d -> %11d" % (x, y, bFixATan2(x, y)))


WIDE = ((2893789, 2707410), (2718082, 1925942), (1020165, 694390),
        (2671451, 1521480), (2464977, 2338812), (3321659, 2144691))


def s_topolar():
    for ix in range(-8, 9):
        for iy in range(-8, 9):
            x = dy(ix, 2)
            y = dy(iy, 2)
            r, a = bToPolar(x, y)
            emit("polar %.9g %.9g -> %.9g %5d" % (x, y, r, a))
    for ix in range(1, 13):
        x = dy(1 << ix, 0)
        y = -1.0
        r, a = bToPolar(x, y)
        emit("polar %.9g %.9g -> %.9g %5d" % (x, y, r, a))
    for wx, wy in WIDE:
        for q in range(4):
            x = dy(-wx if q & 1 else wx, 16)
            y = dy(-wy if q & 2 else wy, 16)
            r, a = bToPolar(x, y)
            emit("polar %.9g %.9g -> %.9g %5d out" % (x, y, r, a))


def s_tables():
    for i in range(513):
        emit("sintab %3d -> %11d" % (i, SIN_TABLE[i]))
    for i in range(209):
        angle, _pad, slope = ASIN_TABLE[i]
        emit("asintab %3d -> %5d %.9g" % (i, angle, slope))
    for i in range(129):
        emit("atanlo %3d -> %5d   atanhi %3d -> %5d"
             % (i, ATAN_LOW[i], i, ATAN_HIGH[i]))


SCENARIOS = [
    ("inverse", s_inverse),
    ("div", s_div),
    ("sqrt32", s_sqrt32),
    ("random", s_random),
    ("randomf", s_randomf),
    ("fmod", s_fmod),
    ("signedmod", s_signedmod),
    ("sin", s_sin),
    ("sinf", s_sinf),
    ("cos", s_cos),
    ("sincos", s_sincos),
    ("asin", s_asin),
    ("atan", s_atan),
    ("fixsin", s_fixsin),
    ("fixsincos", s_fixsincos),
    ("fixatan1", s_fixatan1),
    ("fixatan2", s_fixatan2),
    ("topolar", s_topolar),
    ("tables", s_tables),
]


def model(names):
    del OUT[:]
    for name, fn in SCENARIOS:
        if names and name not in names:
            continue
        emit("scenario %s" % name)
        fn()
    return NL.join(OUT) + NL


# ------------------------------------------------------------------ mutants
#
# (name, source, before, after). The pass writes each into the source, runs
# the whole transcript, and puts the original back.

BM = "3DS Files/source/bmath.c"

MUTATIONS = [
    ("topolar-atan-swapped", BM,
     "    out->a = (uint16_t)bATan(v->x, v->y);",
     "    out->a = (uint16_t)bATan(v->y, v->x);"),
    ("topolar-atan-y-negated", BM,
     "    out->a = (uint16_t)bATan(v->x, v->y);",
     "    out->a = (uint16_t)bATan(v->x, -v->y);"),
    ("topolar-no-sqrt", BM,
     "    float r = sqrtf(v->x * v->x + v->y * v->y);",
     "    float r = v->x * v->x + v->y * v->y;"),
    # hypotf rounds once where the listing rounds three times.
    ("topolar-hypotf", BM,
     "    float r = sqrtf(v->x * v->x + v->y * v->y);",
     "    float r = hypotf(v->x, v->y);"),
    ("topolar-in-double", BM,
     "    float r = sqrtf(v->x * v->x + v->y * v->y);",
     "    float r = (float)sqrt((double)v->x * v->x"
     " + (double)v->y * v->y);"),
    ("topolar-x-twice", BM,
     "    float r = sqrtf(v->x * v->x + v->y * v->y);",
     "    float r = sqrtf(v->x * v->x + v->x * v->x);"),
    ("topolar-no-radius", BM,
     "    out->r = r;" + NL,
     ""),
    ("topolar-no-angle", BM,
     "    out->a = (uint16_t)bATan(v->x, v->y);" + NL,
     ""),
    ("topolar-returns-null", BM,
     "    out->r = r;" + NL + "    return out;",
     "    out->r = r;" + NL + "    return 0;"),
]

EQUIVALENT = {}

for _name in EQUIVALENT:
    assert any(_m[0] == _name for _m in MUTATIONS), _name

_seen = set()
for _m in MUTATIONS:
    assert _m[0] not in _seen, _m[0]
    _seen.add(_m[0])


def run_port(tmp):
    exe = hostbuild.build(tmp, SOURCES, name="bmath_test")
    r = subprocess.run([str(exe)], capture_output=True, text=True,
                       timeout=120)
    return r.returncode, r.stdout.replace(chr(13) + NL, NL)


def mutate_pass():
    ours = model([]).splitlines()
    with tempfile.TemporaryDirectory() as tmp:
        rc, port = run_port(tmp)
    if rc != 0 or port.splitlines() != ours:
        print("base already differs -- fix that before mutating")
        return 1

    survived, missing, caught = [], [], 0
    for name, rel, before, after in MUTATIONS:
        path = hostbuild.ROOT / rel
        text = path.read_text(encoding="utf-8", newline="")
        crlf = (chr(13) + NL) in text
        probe = before.replace(NL, chr(13) + NL) if crlf else before
        repl = after.replace(NL, chr(13) + NL) if crlf else after
        if probe not in text:
            missing.append(name)
            print("  %-28s PATTERN NOT FOUND" % name)
            continue
        try:
            hostbuild.write_source(path, text.replace(probe, repl, 1))
            with tempfile.TemporaryDirectory() as tmp:
                try:
                    rc, port = run_port(tmp)
                except SystemExit:
                    print("  %-28s did not compile (caught)" % name)
                    caught += 1
                    continue
                except subprocess.TimeoutExpired:
                    print("  %-28s hung the harness (caught)" % name)
                    caught += 1
                    continue
            if rc != 0:
                print("  %-28s crashed the harness (caught)" % name)
                caught += 1
                continue
            got = port.splitlines()
            n = sum(1 for a, b in zip(got, ours) if a != b)
            n += abs(len(got) - len(ours))
            if n:
                print("  %-28s caught, %d lines" % (name, n))
                caught += 1
            elif name in EQUIVALENT:
                print("  %-28s survived, equivalent by construction" % name)
            else:
                print("  %-28s SURVIVED" % name)
                survived.append(name)
        finally:
            try:
                hostbuild.write_source(path, text)
            except OSError:
                sys.exit("could not restore %s -- it still holds the "
                         "mutation %s" % (rel, name))

    real = [m for m in MUTATIONS if m[0] not in missing]
    holes = [x for x in survived if x not in EQUIVALENT]
    if missing:
        print("%d PATTERN NOT FOUND -- the tally below is over %d of %d"
              % (len(missing), len(real), len(MUTATIONS)))
    print("%d mutations, %d caught, %d equivalent, %d unexplained"
          % (len(real), caught, len(EQUIVALENT), len(holes)))
    for x in holes:
        print("  unexplained: %s" % x)
    return 1 if (holes or missing) else 0


# ---------------------------------------------------------- an extra sanity net

def selftest():
    """Two things the transcript cannot check, because the port would have to
    be wrong in the same way for them to show up."""
    bad = 0
    # bSqrt32 is exactly floor(sqrt(n)), including at the wrap points.
    ns = list(range(0, 4096))
    ns += [u32(k * k) for k in range(1, 65536, 97)]
    ns += [u32(k * k - 1) for k in range(1, 65536, 97)]
    ns += [u32(1 << k) - 1 for k in range(1, 32)]
    ns += [0xffffffff, 0xfffffffe]
    wrong = [n for n in ns if bSqrt32(n) != math.isqrt(n)]
    print("bSqrt32 vs math.isqrt: %d values, %d wrong" % (len(ns), len(wrong)))
    bad += len(wrong)
    # bASin is a piecewise-linear table; check it tracks the real thing.
    worst = 0.0
    for k in range(-20000, 20001):
        x = f32(k / 20000.0)
        got = bASin(x)
        if got >= 0x8000:
            got -= 0x10000
        want = math.asin(max(-1.0, min(1.0, x))) * 32768.0 / math.pi
        worst = max(worst, abs(got - want))
    print("bASin vs math.asin:    40001 samples, max error %.3f BAM (%.4f deg)"
          % (worst, worst * 360.0 / 65536.0))
    if worst > 3.0:
        bad += 1
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", action="append",
                    help="run only this scenario (repeatable)")
    ap.add_argument("--dump", help="write both transcripts next to this path")
    ap.add_argument("--selftest", action="store_true",
                    help="also check bSqrt32 and bASin against math")
    ap.add_argument("--mutate", action="store_true",
                    help="run the mutation pass instead")
    args = ap.parse_args()

    if args.mutate:
        return mutate_pass()

    names = args.scenario or []
    known = [s[0] for s in SCENARIOS]
    for n in names:
        if n not in known:
            sys.exit("unknown scenario: %s" % n)

    with tempfile.TemporaryDirectory() as tmp:
        exe = hostbuild.build(tmp, SOURCES, name="bmath_test")
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
    rc = 1 if diff else 0
    if diff:
        print(NL.join(diff[:120]))
        if len(diff) > 120:
            print("... %d more diff lines" % (len(diff) - 120))
    if args.selftest:
        rc |= 1 if selftest() else 0
    return rc


if __name__ == "__main__":
    sys.exit(main())
