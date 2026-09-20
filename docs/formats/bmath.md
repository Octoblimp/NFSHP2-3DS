# bMath, bVector, bMatrix, bQuaternion

**Status: decode notes. Nothing here is ported yet.** This is the raw material
for task 19, written down at the end of Session 11 so the disassembly does not
have to be redone. Every rule below carries the address it came from; where a
claim rests on something weaker than a direct reading, it says so.

Four contiguous objects, 10.3 KB of `.text`, 73 functions:

| object | range | functions | decoded |
|--------|-------|-----------|---------|
| `bVector.obj` | `0x00240198`-`0x002411f0` | 38 | all |
| `bQuaternion.obj` | `0x002411f0`-`0x00241bc8` | 9 + 1 initialiser | 3 of 9 |
| `bMath.obj` | `0x00241bc8`-`0x002424f8` | 19 | all |
| `bMatrix.obj` | `0x002424f8`-`0x00242890` | 7 | all |

Types, from `docs/mdebug_structs.txt`:

```
bVector2      8 B   float x, y
bVector3     16 B   float x, y, z, pad
bVector4     16 B   float x, y, z, w
bMatrix4     64 B   bVector4 v0, v1, v2, v3      (row-major, row i at +16i)
bQuaternion  16 B   float x, y, z, w
bPolar        8 B   float r; unsigned short a
bFixVector2   8 B   int x, y                     (Q16)
bFixVector3  12 B   int x, y, z                  (Q16)
```

Angles are **BAM**: a 16-bit binary angle, `0x4000` = 90 degrees. The two
conversion constants appear all over the engine and are float32 literals, not
the exact ratios: `RAD_TO_BAM = 10430.37793` (`0x4622f9b4`) and
`BAM_TO_RAD = 9.587380191e-05`. `32768/pi` is `10430.378350...`, so the shipped
constant is 3.3e-5 low. That difference is load-bearing in at least one place
-- see the atan tables below.

---

## bMath.obj

### Integer

**`bInverse(int x)`** `0x00241bc8`

```c
x == 0 ? 0x7fffffff : (0x7fffffff / x) * 2
```

Approximately `2**32 / x`, so it pairs with a `>> 16` to give a Q16 reciprocal.

**`bDiv(int a, int b)`** `0x00241bf8`

```c
if (b == 0) return a == 0 ? 0 : (a > 0 ? 0x7fffffff : 0x80000000);
return (int)(((int64_t)a * (0x7fffffff / b)) >> 16) * 2;
```

**`bSqrt32(unsigned n)`** `0x00241c68` -- 16-iteration restoring integer square
root. The accumulator holds twice the root, hence the `srl v0,a1,1` on the way
out:

```c
unsigned r = 0, rem = 0;
for (int i = 0; i < 16; i++) {
    unsigned hi = rem << 2;          /* 0x00241c78, before rem is clobbered */
    r <<= 1;                         /* 0x00241c7c, before the compare      */
    unsigned t = hi + (n >> 30);
    if (r < t) { rem = t - r - 1; r += 2; }
    else       { rem = t; }
    n <<= 2;
}
return r >> 1;
```

The loop is 11 instructions at `0x00241c78`-`0x00241ca8`. The `r <<= 1` sits
between the two halves of the `t` computation, which is why it is written out
that way above. Run against `math.isqrt` over `0..3999` plus 40,000 random
32-bit values plus the boundaries: **0 mismatches** -- it is exactly the
floor integer square root, no approximation. That also settles the scaling
question, because `bNormalize` on a `bFixVector2` (`0x00240a48`) does
`bInverse(bSqrt32(x*x+y*y))` followed by a Q16 multiply, which only lands on
unit length if `bSqrt32` returns the root itself and not half of it.

### Random

**`bSetRandomSeed(unsigned s, unsigned* seed)`** `0x00241cb8` --
`*seed = s; return bRandom(1, seed);`. Falls straight through into `bRandom`.

**`bRandom(int range, unsigned* seed)`** `0x00241cc8` -- returns
`oldSeed % range` (unsigned remainder), then advances the seed with a
three-step xorshift:

```c
unsigned t  = s ^ 0x1d872b41;
unsigned u  = t ^ (t >> 5);
unsigned t2 = t ^ (u << 27);
*seed = u ^ t2;
```

**`bRandom(float f, unsigned* seed)`** `0x00241d08` --
`f * 4.656612873e-10f * (float)bRandom(0x7fffffff, seed)` (the constant is
`2**-31`).

The default seed lives at `bDefaultSeed` `0x00324f90`.

### Modulo

**`bFMod(float a, float b)`** `0x00241d80` -- a *floored* modulo, always in
`[0, |b|)`:

```c
float m = fabsf(b);
float q = a / m;
return (q - floorf(q)) * m;
```

**`bSignedMod(int a, int b)`** `0x00241dc0` -- the integer equivalent, with
`|b|` computed by `pmaxw` against the negation. One quirk, kept: when `a` is an
exact negative multiple of `b` it returns `|b|`, not `0`.

### Trigonometry -- the float side

**`bSin(unsigned short bam)`** `0x00241df8` -- range-reduce, then a five-term
Taylor series. This is the same function already ported as `banim_bsin` in
`3DS Files/source/banim.c`; when `bmath.c` lands, `banim.c` must lose its copy
and call this one. The series **overshoots**: at the peak it returns
`1.00000358`, and the frontend's bloom animation depends on that value, so it
is ported rather than replaced with `sinf`.

**`bSin(float radians)`** `0x00241e98` -- `bSin((unsigned short)(int)(x * RAD_TO_BAM))`.

**`bCos(unsigned short a)`** `0x00241ec8` -- `bSin((unsigned short)(a + 16384))`,
preceded by a dead divide-by-360 guard the compiler left behind.

**`bSinCos(float* s, float* c, unsigned short bam)`** `0x00241ef8` -- the same
reduction, then sin (to `x**9`) and cos (`1 - x**2/2 ... - x**10/3628800`)
interleaved, both scaled by the same `+/-1` sign. The add/subtract order is
interleaved between the two series in the original; transcribe it literally or
the float32 cross-check will not match.

**`bASin(float x)`** `0x00242000` -- table-driven, and the most intricate
function in the object.

```c
int neg = 0;
if (x < 0.0f) { x = -x; neg = 1; }
if (x >= 1.0f) return neg ? 0xc000 : 16384;      /* saturate at +/-90 deg */

int v = (int)(x * 65536.0f);

/* Find the octave: a1 climbs 0x8000, 0xC000, 0xE000, ... while it stays
   below v. a0 is the octave's width, halving each step. Capped at 11. */
int oct = 0, base = 0x8000, w = 0x8000;
if (v >= base) {
    w >>= 1;
    for (;;) {
        base += w; oct++;
        if (v < base)  { base -= w; break; }
        if (oct >= 11) { base -= w; break; }
        w >>= 1;
    }
} else {
    base = 0;                       /* octave 0 spans [0, 0x8000) */
}

int bucket = (v - base) >> (11 - oct);           /* 0..15 */
int lo     = base + bucket * (w >> 4);           /* bucket's left edge, Q16 */
int idx    = (oct << 4) + bucket;                /* 0..191 */

int r = bASinTable[idx].angle
      + (int)((x - (float)lo * 1.52587890625e-05f)   /* 2**-16 */
              * bASinTable[idx].slope * 65536.0f);
return neg ? (-r) & 0xffff : r & 0xffff;
```

`bASinTable` is at `0x003152a0`, 1672 bytes, 192 of its 209 8-byte entries
used: `{ unsigned short angle; unsigned short pad; float slope; }`. `slope` is
the *secant* slope over the bucket expressed in turns per unit x (entry 0 is
`0.1592`, which is `1/(2*pi)`), so the `* 65536.0f` turns it into BAM.

Checked against `math.asin` over 20,001 samples of `[-1, 1]`: **max error 1.93
BAM = 0.0106 degrees**. That is the evidence the decode above is right; it is
not a claim about the port, which has to match the table exactly, not
approximately.

**`bATan(float x, float y)`** `0x00242148` -- returns `atan2(y, x)` in BAM. Note
the argument order: the *first* argument is the x axis. Quadrant code first,
then one of two `bASin` calls, then a fixup:

```c
int q = (x < 0.0f);
if (y < 0.0f) q ^= 3;
float h = sqrtf(x*x + y*y);
int r = (fabsf(y) < fabsf(x)) ? bASin(fabsf(y) / h)
                              : 16384 - bASin(fabsf(x) / h);
switch (q) {
case 0: return  r                 & 0xffff;
case 1: return (0x8000 - r)       & 0xffff;
case 2: return (r - 0x8000)       & 0xffff;
case 3: return (-r)               & 0xffff;
}
```

`sqrt.s` on the R5900 is `sqrt.s fd, ft` -- the operand is in the **ft** field,
not fs. `tools/mipsdis.py` got this wrong until Session 10 and made this
function read as a bug. See HANDOFF Session 10.

### Trigonometry -- the fixed-point side

**`bFixSin(unsigned short a)`** `0x00242268`

```c
int i    = a >> 7;                       /* 0..511 */
int frac = (a << 9) & 0xffff;
int lo   = bSinTable[i]     << 1;
int hi   = bSinTable[i + 1] << 1;
return lo + (((hi - lo) * frac) >> 16);
```

`bSinTable` `0x00315928`, 1026 bytes, 513 signed 16-bit entries (512 plus a
wrap guard). Peak `32767` at index 128, trough `-32768` at 384, `0` at 512.
The `<< 1` means the result is Q16-ish: 1.0 comes out as 65534, not 65536.

The table is *approximately* `round(sin(2*pi*i/512) * 32767)` but not exactly:
the error drifts 0 -> +3 (at i=256) -> -6 (at i=511) before being forced back to
0 at 512. A two-parameter fit lands on amplitude 32767 with an angular step
31 ppm short of `2*pi/512`, which reproduces every entry to within 1 LSB, but
no clean constant explains that step and the generator was not identified.
**The port should embed the 513 shipped values verbatim rather than compute
them.** Extract with:

```python
import struct, sys; sys.path.insert(0, 'tools'); import mipsdis
v = struct.unpack("<513h", mipsdis.Elf().read(0x315928, 1026))
```

**`bFixSinCos(int* s, int* c, unsigned short bam)`** `0x002422b0` --
`*s = bFixSin(bam); *c = bFixSin((unsigned short)(bam + 16384));`

**`bFixATan(int t)`** `0x00242308` -- `atan` of a Q16 tangent, in BAM. Four
ranges:

| range of `t` | source |
|---|---|
| `t <= 0x0003ffff` (tan <= 4) | `bFixATanTableLow`, index `t >> 11`, frac `(t << 5) & 0xffff` |
| `<= 0x001fffff` (tan <= 32) | `bFixATanTableHigh`, index `t >> 14`, frac `(t << 2) & 0xffff` |
| `<= 0x00ffffff` (tan <= 256) | linear ramp `16058 + ((16343 - 16058) * (t >> 8) >> 16)` |
| above | saturates to `16383` |

Sign is stripped first and reapplied as `(-r) & 0xffff`. Both tables are 258
bytes, 129 unsigned 16-bit entries, at `0x00315d30` (Low) and `0x00315e38`
(High); High's first 16 entries are populated but unreachable, because the
`t > 0x3ffff` guard means the index never drops below 16.

Both tables reproduce **exactly**, all 129 entries each, as

```python
lo[i] = int(math.atan(i / 32.0) * 10430.3779296875)
hi[i] = int(math.atan(i /  4.0) * 10430.3779296875)
```

-- double-precision `atan`, times the *float32-rounded* BAM constant,
truncated. The evidence that the constant is the rounded one rather than
`32768/pi`: `atan(1.0)` sits exactly on 8192, and both tables store 8191 there
(`lo[32]`, `hi[4]`). With the exact ratio that entry rounds up and the model
mismatches; with `10430.3779296875` it does not. One entry, but it is the only
one that can tell the two apart, and it decides. The port can generate these or
embed them; embedding avoids depending on the host libm.

There is a seam between range 2 and range 3: at `t = 0x001fffff` the tables
give `atan(32) = 16058` and the ramp gives `16093`, a 0.19-degree jump. It is
in the shipped code.

**`bFixATan(int x, int y)`** `0x002423e0` -- `atan2(y, x)` in BAM, same argument
order and the same quadrant fixup as the float `bATan`:

```c
int q = (x < 0); if (y < 0) q ^= 3;
x = abs(x); y = abs(y);
int r = ((y >> 14) < x) ? bFixATan(bDiv(y, x)) : 16384;
/* ...then the identical four-case fixup */
```

The `(y >> 14) < x` guard is an overflow guard on `bDiv`, not a precision one:
it only trips once `y/x` exceeds 2**14, well past the point where `bFixATan`
saturates anyway.

**`bToPolar(bPolar* out, const bVector2* v)`** `0x002424a0`

```c
out->r = sqrtf(v->x * v->x + v->y * v->y);
out->a = bATan(v->x, v->y);
return out;
```

(Stores the angle first, at `+4`, then the radius. Order does not matter here.)

---

## bVector.obj

### Float

**`bNormalize(bVector2* o, const bVector2* v)`** `0x00240198` -- divides each
component by the length; when the length is exactly `0.0f` it writes
**`(1, 0)`**, not `(0, 0)`.

**`bNormalize(bVector2* o, const bVector2* v, float len)`** `0x002401f0` --
normalises to length `len` by dividing through by `length / len`. Same
degenerate case, and it still writes `(1, 0)` -- not `(len, 0)`. Quirk, keep.

**`bNormalize(bVector3* o, const bVector3* v, float len)`** `0x00240250` --
computes `x*x + y*y + z*z` on VU0 (`vmul.xyz`, `vaddy.x`, `vaddz.x`, then
`qmfc2` the x lane back), so the summation order is `(x*x + y*y) + z*z`. Unlike
the 2D pair it takes the reciprocal once and multiplies. Degenerate case writes
**`(len, 0, 0)`** -- different again from the 2D versions.

**`bScaleAdd(bVector2* o, const bVector2* a, const bVector2* b, float s)`**
`0x002402d0` -- `o = a + b*s`.

**`bEqual(const bVector2* a, const bVector2* b, float eps)`** `0x00240300`,
**`bEqual(const bVector3*, ...)`** `0x00240350` -- per-component
`fabsf(d) > eps` fails; note *strictly* greater, so `eps` is inclusive.

### Bounding boxes -- bVector2

* `bInitializeBoundingBox(mn, mx)` `0x00240cb8` -- `mn = (FLT_MAX, FLT_MAX)`,
  `mx = (-FLT_MAX, -FLT_MAX)` from the literals at `0x00324f84`/`0x00324f88`.
* `bInitializeBoundingBox(mn, mx, p)` `0x00240ce0` -- `mn = mx = *p`.
* `bExpandBoundingBox(mn, mx, p)` `0x00240d00` -- `min.s`/`max.s`.
* `bExpandBoundingBox(mn, mx, p, r)` `0x00240d40` -- expands by `p +/- r`.
* `bExpandBoundingBox(mn, mx, lo, hi)` `0x00240d90`.
* `bBoundingBoxIsInside(mn, mx, p, eps)` `0x00240dd8` -- `p` inside the box
  grown by `eps`, with a strict `<` on each of the four tests.
* `bBoundingBoxIsInside(mn, mx, innerMn, innerMx)` `0x00240e50` -- true when
  `[innerMn, innerMx]` is contained in `[mn, mx]`, tests inclusive (`c.le.s`).
* `bBoundingBoxOverlapping(mn, mx, oMn, oMx)` `0x00240eb8` -- tests exclusive
  (`c.lt.s`), so boxes that only touch do not overlap.

### Bounding boxes -- bVector3

Same eight, `0x00240f20`-`0x00241138`, but the three-component ones run on VU0
with whole 128-bit `vmini`/`vmax`, so **the `pad` lane takes part**:

* `bInitializeBoundingBox(mn, mx)` `0x00240f20` loads `bVector3FLT_MAX`
  (`0x00315280`) into `mn` and `vf0 - that` into `mx`. `bVector3FLT_MAX` is
  filled by `_GLOBAL_$I$bNormalize...` at `0x002411d0`, which writes `FLT_MAX`
  to x, y and z only -- `pad` stays `0.0f`. `vf0` is the VU constant
  `(0,0,0,1)`, so `mx` comes out `(-FLT_MAX, -FLT_MAX, -FLT_MAX, 1.0f)`.
* `bExpandBoundingBox(mn, mx, p, r)` `0x00240f80` builds the radius vector on
  the stack but only writes `sp[0..2]`; `sp[3]` is whatever was there. So the
  `pad` lane of both corners is fed uninitialised stack. Harmless as long as
  nothing reads `.pad`, but the port cannot reproduce it and should not try --
  operate on x/y/z and say so.

### Fixed point (Q16)

`fixmul(a, b)` throughout means `(int)(((int64_t)a * b) >> 16)`, which the
compiler emits as `mult` + `dsll 16` + `dsra32` on the 64-bit product.

* **`bLength(const bFixVector2*)`** `0x002403c0`,
  **`bLength(const bFixVector3*)`** `0x00240448` -- pre-scale so the sum of
  absolute components fits in 16 bits (`s += 2` until `(sum >> s) <= 0xffff`),
  square the shifted components, `bSqrt32`, shift back by `s`. `|x|` is
  computed as `pmaxw(x, -x)`.
* **`bDistBetween(const bFixVector2*, const bFixVector2*)`** `0x002404f0`,
  **3D** `0x00240580` -- same idea but with a fixed choice of two shifts: `>> 16`
  when the absolute-sum exceeds `0x00ffffff`, otherwise `>> 8`.
* **`bScale`** `0x00240640` (2D) / `0x00240710` (3D),
  **`bScaleAdd`** `0x002406a0` / `0x002407a0`,
  **`bDot`** `0x00240848` / `0x002408a8`,
  **`bCross`** `0x00240938` (3D only) -- all plain `fixmul`.
* **`bNormalize(bFixVector2*, const bFixVector2*)`** `0x00240a48`,
  **3D** `0x00240b58` -- pre-scale as in `bLength`, `bSqrt32`, then
  `fixmul(component, bInverse(length))`. Zero length writes
  `(0x10000, 0)` / `(0x10000, 0, 0)`, i.e. `(1.0, 0)` in Q16 -- consistent with
  the float 2D version.

---

## bMatrix.obj

**`bIdentity(bMatrix4* m)`** `0x002424f8` -- builds the identity with
`por`/`pexew`/`pexcw`/`pextlw` on a 128-bit GPR. Just the identity.

**`bOldIdentity(bMatrix4* m)`** `0x00242528` -- the same, written scalar.

**`bInvertMatrix(bMatrix4* o, const bMatrix4* m)`** `0x00242578` -- a full
affine inverse: adjugate over determinant for the upper 3x3, then
`o.row3 = -(m.row3 * o3x3)`. Writing `m` as rows `(a,b,c)`, `(d,e,f)`,
`(g,h,i)` and translation `(tx,ty,tz)`:

```
D = a*(e*i - f*h) - b*(d*i - f*g) + c*(d*h - e*g)      /* in that order */
k = 1.0f / D

o00 =  (e*i - f*h)*k   o01 = -(b*i - c*h)*k   o02 =  (b*f - c*e)*k
o10 = -(d*i - f*g)*k   o11 =  (a*i - c*g)*k   o12 = -(a*f - c*d)*k
o20 =  (d*h - e*g)*k   o21 = -(a*h - b*g)*k   o22 =  (a*e - b*d)*k

o30 = -(tx*o00 + ty*o10 + tz*o20)
o31 = -(tx*o01 + ty*o11 + tz*o21)
o32 = -(tx*o02 + ty*o12 + tz*o22)
o03 = o13 = o23 = 0    o33 = 1
```

The negated entries are produced by multiplying with `-k` rather than negating
afterwards (`neg.s $f1,$f9` at `0x00242630`), which matters for float32 parity
only at the sign of zero.

**`bMulMatrix(bMatrix4* o, const bMatrix4* m1, const bMatrix4* m2)`**
`0x002426f8` -- VU0 macro mode, four rows of

```
vmulax  ACC, vf8,  vf4x      ; vf8..vf11 = *m1 (the second argument)
vmadday ACC, vf9,  vf4y
vmaddaz ACC, vf10, vf4z
vmaddw  vf12, vf11, vf4w     ; vf4..vf7  = *m2 (the third argument)
```

so `o.row[i] = sum_j m2[i][j] * m1.row[j]`, i.e. **`*o = *m2 * *m1`** -- the
arguments multiply right-to-left. This is decoded from the instruction
encodings, not yet cross-checked against a caller, so verify it before relying
on it. The four COP2 words are `0x4be441bc`, `0x4be448bd`, `0x4be450be`,
`0x4be45b0b`; the fields are `dest = bits 24..21`, `ft = 20..16`, `fs = 15..11`,
`fd = 10..6`, `function = 5..0`, and for functions `0x3c`-`0x3f` the real
opcode is the Special2 entry at index `(fd << 2) | (function & 3)`.

**`bMulMatrix(bVector4* o, const bMatrix4* m, const bVector4* v)`**
`0x00242770` -- `*o = *v * *m` (row vector on the left), three `vnop`s for the
VU pipeline, then one 128-bit store.

**`bMulMatrix(bVector3* o, const bMatrix4* m, const bVector3* v)`**
`0x002427b0` -- same, but it copies `*v` through the stack and forces `w = 1.0f`
first, so this is the full affine transform including translation. It reads 16
bytes from `v` and writes 16 bytes to `o`, which is why `bVector3` is padded.

**`bTransposeMatrix(bMatrix4* o, const bMatrix4* m)`** `0x00242808` -- reads all
sixteen floats before writing any, so `o == m` is safe.

---

## bQuaternion.obj

Three of nine decoded.

**`bQuaternion::bQuaternion(const bMatrix4&)`** `0x002411f0` -- Shepperd's
method, with the usual two branches. The trace test goes through the soft-float
`fptodp`/`dpcmp` pair, i.e. the source compared a `double`:

```c
float trace = (m00 + m11) + m22;
if ((double)trace > 0.0) {
    float s = sqrtf(trace + 1.0f);
    q.w = s * 0.5f;
    float k = 0.5f / s;
    q.x = (m12 - m21) * k;
    q.y = (m20 - m02) * k;
    q.z = (m01 - m10) * k;
} else {
    static const int next[3] = { 1, 2, 0 };     /* 0x002a3060, verified */
    int i = (m00 < m11) ? 1 : 0;
    if (m[i][i] < m22) i = 2;
    int j = next[i], k = next[j];
    float s = sqrtf((m[i][i] - (m[j][j] + m[k][k])) + 1.0f);
    float q4[4];
    q4[i] = s * 0.5f;
    if ((double)s != 0.0) s = 0.5f / s;         /* branch-likely at 0x002413b8 */
    q4[3] = (m[j][k] - m[k][j]) * s;
    q4[j] = (m[i][j] + m[j][i]) * s;
    q4[k] = (m[i][k] + m[k][i]) * s;
    q.x = q4[0]; q.y = q4[1]; q.z = q4[2]; q.w = q4[3];
}
```

Note the guard is `s != 0` and it leaves `s` un-reciprocated when `s == 0`,
rather than zeroing the three outputs.

**`bQuaternion::GetMatrix(bMatrix4*)`** `0x002414b0` -- the standard
quaternion-to-matrix expansion off `x+x`, `y+y`, `z+z`, writing the fourth row
and column as `(0,0,0,1)`. The exact add/subtract order is at
`0x002414bc`-`0x00241564`; transcribe literally.

**`bIdentityQuaternion`** `0x00315290`, set to `(0, 0, 0, 1)` by
`_GLOBAL_$I$bIdentityQuaternion` at `0x00241ba0`.

Not yet decoded: **`bSlerp`** `0x00241570` (384 B, uses VU0 -- the listing is in
`dis_bquat.txt` from `0x002415a8`), **`bConjugate`** `0x002416f0`,
**`bLength`** `0x00241728`, **`bNormalize`** `0x00241758`, **`bMult`**
`0x00241798`, **`bQuaternionToMatrix`** `0x00241800`, **`bMatrixToQuaternion`**
`0x002418c0` (732 B, the largest in the object -- presumably the same Shepperd
branch as the constructor, but confirm rather than assume).

---

## Reproducing the dumps

```bash
python tools/mipsdis.py --addr 0x240198 --count 1046   # bVector.obj
python tools/mipsdis.py --addr 0x2411f0 --count  630   # bQuaternion.obj
python tools/mipsdis.py --addr 0x241bc8 --count  588   # bMath.obj
python tools/mipsdis.py --addr 0x2424f8 --count  230   # bMatrix.obj
```

Data tables:

| symbol | address | size | contents |
|--------|---------|------|----------|
| `bASinTable` | `0x003152a0` | 1672 B | 209 x `{u16 angle; u16 pad; float slope}`, 192 used |
| `bSinTable` | `0x00315928` | 1026 B | 513 x `s16` |
| `bFixATanTableLow` | `0x00315d30` | 258 B | 129 x `u16` |
| `bFixATanTableHigh` | `0x00315e38` | 258 B | 129 x `u16` |
| `bVector3FLT_MAX` | `0x00315280` | 16 B | runtime-initialised |
| `bIdentityQuaternion` | `0x00315290` | 16 B | runtime-initialised |
