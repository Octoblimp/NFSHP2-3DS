# `eMathE.obj` -- the engine's matrix layer

`0x0011b9a0 .. 0x0011c7b8`, 3.6 KB, twenty-six symbols. It sits on top of
`bMatrix.obj` (`docs/formats/bmath.md` covers the layer below) and everything
above it is written in terms of these rather than the `b*` ones: the camera,
the car simulation, the AI, the collision code.

Almost every line of it is VU0 macro mode -- COP2 opcodes in the EE
instruction stream -- so none of it could be read until `tools/vudis.py`
existed. That decoder is checked against sixteen hand-derived words and then
against the whole image: 3087 COP2 words in `.text`, 41 distinct mnemonics,
nothing undecoded.

The port is `3DS Files/source/emath.c`, cross-checked by
`tools/emath_check.py` (2416 transcript lines, 39 mutations, none surviving).

## Where things are

| address | symbol | what |
|---------|--------|------|
| `0x11b9a0` | `eMathInit` | fills the two globals below |
| `0x11b9e0` | `eNormalizedDirection` | **has a bug**; see below |
| `0x11ba18` | `eIdentity` | |
| `0x11ba68` | `eZeroMatrix` | |
| `0x11bab0` | `eMulMatrix` | `*o = *m1 * *m2` -- **opposite order to `bMulMatrix`** |
| `0x11bb28` | `eMulVector4` | `o = v * m` |
| `0x11bb68` | `eMulVector3` | same, with `w` forced to 1 |
| `0x11bb98` | `eRotTransPers` | transform then projective divide |
| `0x11bc00` | `eGetClipFlags` | VU0's six clip bits |
| `0x11bc68` | `eCreateAxisRotationMatrix` | Rodrigues; the only user of the sine *table* |
| `0x11bd68` | `eCreateLookAtMatrix` | the view matrix |
| `0x11bf48` | `eReflectVector` | **empty**: `jr ra; nop`, zero callers |
| `0x11bf50` | `eSin` | range reduction + 9th-order odd polynomial |
| `0x11c048` | `eRotateX` | |
| `0x11c110` | `eRotateY` | |
| `0x11c1d8` | `eRotateZ` | |
| `0x11c2a0` | `eTranslate` | |
| `0x11c310` | `eCreateTranslationMatrix` | |
| `0x11c368` | `eTransposeMatrix` | all sixteen elements |
| `0x11c3f0` | `eInvertTransformationMatrix` | `T(-t) * R^T` |
| `0x11c4e8` | `eVectorStarMatrix` | row *i* of `o` is `v` cross row *i* of `m` |
| `0x11c5d0` | `eOrthonormalizeMatrix` | Gram-Schmidt from rows 0 and 1 |
| `0x11c6a0` | `eInvertRotationMatrix` | transpose, then **clears the corner too** |
| `0x11c6e8` | `eIsPointInPoly` | crossing number on the xy plane |
| `0x2dc580` | `eMathIdentityMatrix` | |
| `0x2dc5c0` | `eMathZeroMatrix` | |

Conventions are `bMatrix.obj`'s: row-major, 64 bytes, row *i* at offset 16*i*,
the translation in row 3, and a point is a **row on the left**, so `v * m`.
Angles are BAMs, 65536 to the turn.

## The three traps

### `eMulMatrix` and `bMulMatrix` take their operands in opposite orders

`eMulMatrix(o, a, b)` is `o = a * b`. `bMulMatrix(o, a, b)` is `o = b * a`.

Both are the same eight-quadword VU0 loop. The only difference is which
argument is loaded into `vf4..vf7` -- the operand that gets broadcast, one
component at a time, as the multiplier -- and which into `vf8..vf11`:

    eMulMatrix  0x11bac0   lq a1 -> vf04..vf07     lq a2 -> vf08..vf11
    bMulMatrix  0x242708   lq a2 -> vf04..vf07     lq a1 -> vf08..vf11

Nothing in the symbol names or the argument types warns you. A caller reading
`eMulMatrix(&o, &view, &proj)` gets `view` applied first; a caller reading
`bMulMatrix(&o, &view, &proj)` gets `proj` applied first. The port keeps both
spellings and implements `eMulMatrix` as `bMulMatrix(o, m2, m1)`, with the
swap commented at the call so nobody "fixes" it.

### `eNormalizedDirection` divides a 3-D vector by its 2-D length

`0x11b9e0` computes `to - from` and normalises it -- except that the length it
divides by is the square root of `dx*dx + dy*dy`. The `dz*dz` term is
computed, written into a different lane of the accumulator, and never read:

    vmul.xyz  vf02,vf03,vf03     vf2   = d*d
    vadday.x  ACC, vf02,vf02y    ACC.x = d.x^2 + d.y^2
    vaddaz.z  ACC, vf00,vf02z    ACC.z = d.z^2          <- dead
    vmaddw.x  vf01,vf00,vf00w    vf1.x = ACC.x + 0
    vrsqrt    Q,   vf00w,vf01x

This is the only normalise in the image written with the accumulator form.
Every other one -- about fifty sites, including `bNormalize`, and including
the two inside this same object file -- sums three components with the
`vaddy.x` / `vaddz.x` chain, which is what makes the odd one out legible as a
mistake rather than as a 2-D helper with a misleading name.

It never shipped visibly: the only caller is `OLDeRenderLightFlare`, and
nothing calls that. The port keeps the arithmetic as it is.

### `eInvertRotationMatrix` leaves 1.0 out of the corner

`0x11c6a0` calls `eTransposeMatrix` and then stores zero over the fourth
column (`m[0][3]`, `m[1][3]`, `m[2][3]`), over row 3 -- and over `m[3][3]` as
well. The result has a zero in the bottom-right, so it is not a valid
transform on its own; feeding it to `eMulVector3`, which forces `w` to 1,
gives a `w` of 0 out. Callers use it only for the 3x3 part.

## `eSin`

Range reduction with two `while` loops and two folds, then an odd polynomial
in x:

    while (2pi < x) x -= 2pi;        0x40c90fdb
    while (x < 0)   x += 2pi;
    if (pi <= x)   { x -= pi; sign = -1; }
    if (pi/2 <= x)   x = pi - x;     0x3fc90fdb
    return sign * (x + x^3*C3 + x^5*C5 + x^7*C7 + x^9*C9);

with `C3 = 0xbe2aaaa4`, `C5 = 0x3c08873e`, `C7 = 0xb94fb21f`,
`C9 = 0x362e9c14` -- a minimax fit, not the Taylor coefficients
(`-1/6` is `0xbe2aaaab`, so `C3` is seven ulps away from it). The sum is
accumulated strictly left to right; in float that is not the same number as
any other order, and reordering it moves 208 lines of the transcript.

The reduction really is a loop and not a modulo, which matters for the large
inputs the camera can produce.

`eSin` is *not* `bSinF`: `bMath.obj` has its own sine, off a table, and the
two disagree in the last few bits. `eCreateAxisRotationMatrix` is the one
function in this file that uses the table one.

### One ulp of pi/2

`eRotateX`, `eRotateY` and `eRotateZ` get their cosine as `eSin(theta + pi/2)`
and load `0x3fc90fdc` for that `pi/2`, from `gp-32396`, `gp-32388` and
`gp-32380`. `eSin` itself compares against `0x3fc90fdb`, from `gp-32420`.
That is one ulp apart, both spellings are in the image, and collapsing them
changes the last bit of every cosine the rotations produce -- 342 transcript
lines. The port keeps them as separate constants, `E_ROT_HALF_PI` and
`E_HALF_PI`, with a comment saying so.

## `eCreateLookAtMatrix`

    negUp = -up
    dir   = normalize(target - eye)
    right = negUp cross dir
    newUp = dir cross right
    normalize(right); normalize(newUp)

then those three go into the matrix **as columns**:

    | right.x  newUp.x  dir.x  0 |
    | right.y  newUp.y  dir.y  0 |
    | right.z  newUp.z  dir.z  0 |
    |    0        0       0    1 |

and the result is `eMulMatrix(m, T(-eye), that)` -- translate first, then
rotate. With the row-vector convention, writing the basis as columns is what
makes the matrix the *inverse* of the camera's placement, which is what a view
matrix is.

`up` is negated on the way in. The engine's world has Z down; negating `up`
is what puts the horizon the right way up on screen, and it is also why
`right` comes out of `negUp cross dir` rather than `dir cross up`.

`Camera::SetCameraMatrix` is the exact inverse of this and agrees with it: it
recovers `Direction` as the normalised third column and `Position` as
`-(M * T)`.

## `eGetClipFlags`

Transforms `v` by `m` with `w` forced to 1 (the `vmaddw` reads `vf00.w`, the
hardware constant 1, not the vector's own `w`), then runs `vclipw.xyz` and
reads the result with `cfc2 v0,vi18` / `andi 0x3f`.

`vclipw` pushes six bits per execution and the clip register keeps the last
four executions; masking with `0x3f` takes only the newest. The comparisons
are against the absolute value of `w` and are **strict**:

| bit | set when |
|-----|----------|
| `0x01` | `x` is greater than `abs(w)` |
| `0x02` | `x` is less than `-abs(w)` |
| `0x04` | `y` is greater than `abs(w)` |
| `0x08` | `y` is less than `-abs(w)` |
| `0x10` | `z` is greater than `abs(w)` |
| `0x20` | `z` is less than `-abs(w)` |

A point exactly on a plane is inside. The absolute value matters: with a
negative `w` the naive form would report everything outside.

## `eIsPointInPoly`

The standard crossing-number test, with `j` trailing `i` and starting at
`n-1`, and a half-open `y` comparison:

    if ((poly[i].y <= pt.y && pt.y < poly[j].y) ||
        (poly[j].y <= pt.y && pt.y < poly[i].y))
        if (pt.x < (poly[j].x - poly[i].x) * (pt.y - poly[i].y)
                   / (poly[j].y - poly[i].y) + poly[i].x)
            inside = !inside;

Half-open is what makes a horizontal ray through a vertex cross once rather
than twice. `n = 0` returns 0 without touching `poly[-1]`, because the loop is
`for (i = 0; i < n; i++)` and never runs.

## Cross-check

`tools/emath_check.py` drives `tools/src/emath_test.c` and an independent
Python model -- both written from the listings, neither from the other --
through nine scenarios and diffs the transcripts line by line. Every number is
a float32 printed with `%.9g`, which round-trips, so a one-ulp difference is a
changed line rather than something a tolerance absorbs.

    python tools/emath_check.py            # 9 scenarios, 2416 lines, 0 differ
    python tools/emath_check.py --mutate   # 39 mutations, 0 survived

The one place the port cannot be bit-exact against the hardware is anything
through `VRSQRT`, which is a reduced-precision unit rather than an IEEE
divide-and-root. That is the same compromise `bmath.c` makes, for the same
reason, and it is bit-exact between the port and the model.

The mutation list deliberately does *not* contain a strict/non-strict flip of
the `pi/2` fold in `eSin`: `E_PI` and `E_HALF_PI` have the same mantissa in
the image, so `E_PI - E_HALF_PI` is `E_HALF_PI` exactly and the fold is the
identity at the only input where the two spellings disagree. It is an
equivalent mutant, and an equivalent mutant in a mutation list is a
permanently failing test. Dropping the fold entirely is not equivalent, and
that is what the list tests instead.
