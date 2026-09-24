# QuickSpline

`quickspline.cpp` (0x00227e98 .. 0x00228e4c). An Overhauser (Catmull-Rom)
spline through a buffer of `bVector4` control points. The track paths, the
player's driving line and the belt mover are all built on it. It is the
first piece of task 27's debt to be paid, and it has to come before
`TrackPathManager::Init` and `RealController`.

Ported to `3DS Files/source/quickspline.{c,h}`. Cross-checked by
`tools/quickspline_check.py` against `tools/src/quickspline_test.c`. Every
method but `DoSnapshot` runs as shipped in mipsemu, and so do the `bFMod`,
`bMulMatrix` and `bTransposeMatrix` beneath them.

## Who builds one

All three users call the allocating constructor, and all use the one basis
the enum has:

| Caller | End type | Points |
|--------|----------|--------|
| TrackPathManager::Init (0x001f50e0) | LOOP for a closed path, EXTRAPOLATED for an open one | the path's point count, then `CalibrateLength(16)` |
| RealController (0x002247e0) | EXTRAPOLATED | 4 |
| BeltMover (0x001f1d60) | EXTRAPOLATED | 20 |

Nothing constructs a `LINE` spline. Nothing calls the constructor that
takes a caller's buffer. Both are ported anyway: they are in the object,
and each costs a few lines.

## The record

40 bytes. It has no vtable.

| Off | Field | Type |
|----:|-------|------|
| 0 | EndPointType | int32_t: LOOP 0, LINE 1, EXTRAPOLATED 2 |
| 4 | BasisType | int32_t: OVERHAUSER 0 |
| 8 | MaxParam | float |
| 12 | MinParam | float |
| 16 | Length | float |
| 20 | ControlPointsDirty | int8_t (`lb`) |
| 21 | BufferWasAllocated | int8_t |
| 22 | MinControlPoints | int8_t: 3 for LOOP, else 2; set and never read |
| 24 | MaxControlPoints | uint16_t |
| 26 | NumControlPoints | uint16_t |
| 28 | pControlPointBuffer | bVector4 * |
| 32 | pControlPoints | bVector4 *: the buffer plus one |
| 36 | pBasisMatricies | bMatrix4 *: the three matrices, or NULL |

The enum values come from the stabs (`QUICKSPLINE_LOOP:0,` and so on). On a
64-bit host the first pointer's own alignment pushes it from 28 to 32, so
the header's layout assert places the three pointers with a formula instead
of fixed offsets.

## The parameter and the w lane

Control point `i` sits at `t = i`, one unit per segment. The segment from
`i` to `i+1` is evaluated from the four points `cp[i-1] .. cp[i+2]`.

`w` is not a coordinate. `CalibrateLength` writes each point's distance
along the curve into its `w`, so a `GetPoint` returns arc length in `w`
alongside the position in `xyz`. Callers read distance out of the same
evaluation.

`SetNumControlPoints` sets the range:

| Type | MinParam | MaxParam |
|------|---------:|---------:|
| any, with 0 points | 0 | 0 |
| LOOP | 0 | n |
| LINE | 0 | n - 1 |
| EXTRAPOLATED | -9999999 | 9999999 (gp-27168, -27164) |
| any other value | unchanged | unchanged |

The count is stored as sixteen bits before it is tested, so 65536 means no
points. The allocating constructor also cuts the count to sixteen bits
before it works out the size.

## The buffer

The allocating constructor asks
`bMalloc((max + 3) * 16, "..\indep\src\quickspline.cpp", 77, 16)`. That is
one vector before the caller's points and two after, and `pControlPoints`
is the buffer plus one. The image never clears the block (the loop that
follows the call is `bVector4`'s constructor, inlined to nothing).

`FixupEndpoints` writes around the caller's points, lazily, whenever
`GetPoint` or `FindClosestParam` finds `ControlPointsDirty` set:

| Type | cp[-1] | cp[n] | cp[n+1] |
|------|--------|-------|---------|
| LOOP | cp[n-1] | cp[0] | cp[1] |
| LINE | cp[0] | cp[n-1] | not written |
| EXTRAPOLATED | (cp[1] - cp[0]) * -1 + cp[0] | (cp[n-1] - cp[n-2]) * 1 + cp[n-1] | not written |

The multiplies by -1 and 1 are real `vmulx` instructions in the image, and
the port keeps them.

With a non-zero `Length`, the `w` lanes are rewritten so that distance
carries on past the ends:

* **LOOP.** A lap back and a lap on: `cp[-1].w = cp[n-1].w - L`,
  `cp[n].w = L + cp[0].w`, `cp[n+1].w = L + cp[1].w`.
* **LINE and EXTRAPOLATED.** Mirrored, but not symmetrically. The front
  reflects **cp[1]** about zero: `lwc1 $f0,28(a1)` is `cp[1].w`, not
  `cp[0].w`. The back reflects `cp[n-1]` about `L`, as `(L + L) - cp[n-1].w`.

The test is `c.eq.s`, so a `Length` of -0.0 also counts as none.

For n = 1 the LOOP copies run in order, each a load and then a store. So
`cp[n+1] = cp[1]` reads what `cp[n] = cp[0]` has just written.

## The basis matrices

These are three `bMatrix4` at 0x00314490, built by the first spline anyone
constructs: `Init` tail-calls the builder, and the flag at gp-16120 guards
it. The image spreads them over fifty `swc1`s. Written as rows of the four
points' weights against `(1, t, t^2, t^3)`, and before the halving, they
are:

    position              first derivative       second derivative
    ( 0, -1,  2, -1)      (-1,   4,  -3, 0)      (  4,  -6, 0, 0)
    ( 2,  0, -5,  3)      ( 0, -10,   9, 0)      (-10,  18, 0, 0)
    ( 0,  1,  4, -3)      ( 1,   8,  -9, 0)      (  8, -18, 0, 0)
    ( 0,  0, -1,  1)      ( 0,  -2,   3, 0)      ( -2,   6, 0, 0)

Each row is then halved by a `vmulx` against 0.5, and each matrix is
transposed in place.

The second and third matrices are exactly the first one's derivatives, row
by row. The first row, for example, is ½(-t + 2t² - t³), then
½(-1 + 4t - 3t²), then ½(4 - 6t). The checker compares all 48 floats
against the image's own table anyway.

`EvaluateSpline(t, basis, pts)` builds `v = (1, t, t*t, t*(t*t))`. It
multiplies `v` through the basis to get the four weights, then multiplies
the weights through the four points taken as a matrix.

A spline whose basis is not OVERHAUSER gets `pBasisMatricies = NULL` and
faults on its first evaluation. The port keeps that fault.

## GetPoint

1. Run the fixup if the points are dirty, and clear the flag.
2. With no points, answer zero.
3. `ClampParam`: LOOP wraps with `bFMod(t, MaxParam)`. LINE holds t to
   `[MinParam, MaxParam - 1e-7]` with `max.s` / `min.s`. EXTRAPOLATED
   passes t through.
4. Floor by truncating and then correcting: `whole = cvt.w.s(t)`, then
   `whole -= 1` if `t < whole`. The fraction is `t - whole`, and the segment
   is `cvt.w.s(whole)`.
5. For EXTRAPOLATED, when the segment is below 0 or at or past n - 1,
   `GenerateExtrapolatedControlPoints(seg - 1)` makes up the four points.
   Otherwise the four points are `cp[seg-1 ..]`.

The last segment of an EXTRAPOLATED spline counts as off the end because it
needs `cp[n+1]`, and the fixup never wrote one. `GenerateExtrapolated...`
copies `cp[k]` for `-1 <= k <= n`. Below -1 it answers
`(cp[0] - cp[1]) * -k + cp[0]`, and above n it answers
`(cp[n-1] - cp[n-2]) * (k - n + 1) + cp[n-1]`: a straight line through the
end pair.

**cvt.w.s saturates.** An EXTRAPOLATED `t` of 3e9 floors to INT_MAX. The
index sums after it are `addu` / `subu` and wrap. The port does both
explicitly (`ee_trunc_w`, and wrapping helpers `add32` / `sub32`).

### Reads past the points

Two paths make `GetPoint` read a vector nothing has written.

**LOOP at t = n.** For a `t` a hair below a multiple of n, `bFMod` can
answer exactly `n`: -1e-6 against n = 100 comes back as 100.0. The segment
is then n, which reads `cp[n+2]`, one vector past the end of the block.

**LINE at t >= MaxParam, for n >= 4.** `MaxParam - 1e-7` rounds straight
back to `MaxParam` once `MaxParam` is 3 or more: the gap below 3.0 is
2.4e-7, and the epsilon is less than half of it. The clamp therefore does
nothing, the segment is n - 1, and the read is `cp[n+1]`, which a LINE
fixup never writes. The epsilon only holds for n = 2 and 3. No shipped code
builds a LINE spline, so the image never shows it.

In both cases the stray point lies at the segment's start, where the
position and tangent bases give it a weight of exactly zero. On the EE,
which has no NaN, garbage times zero is zero, so the answer cannot move. On
the 3DS, a NaN in that memory would propagate through the zero. The port
therefore allocates **one vector more** than the image and zeroes the whole
block, so both reads land on a defined zero. The second-derivative basis
weights the stray point by -1. There the image reads garbage and the port
reads zero.

The checker's model gives the image a block with sixteen zeroed bytes past
its request, and the dump prints that slack vector for every heap buffer.

A LINE spline with a single point reads `cp[-2]`, before the block. The
checker's grid leaves that case out.

## The searches

`FindClosestControlPoint` scans every point, and the first nearest wins
(`c.lt.s`). It answers -1 when there are no points.

`FindClosestControlPoint(p, start)` walks forward from `start` while each
point is **strictly** nearer (`c.le.s best,d` stops on a tie). Then it
walks backward from `start - 1`, whatever the forward walk did, against the
best distance the forward walk left behind. The distance is
`sqrt((dx*dx + dy*dy) + dz*dz)`, lane by lane. It ignores `w`.

`FindClosestParam(p, guess, tolerance)` is a Newton-secant search for the
`t` at which `p - point(t)` is perpendicular to the tangent:

* The error is the projection of `p - point(t)` on the tangent, divided by
  the tangent's length. The search stops when `|err| < tolerance`. It also
  stops, returning `t` as it stands, on a zero tangent or a zero secant.
* The first step's slope is the tangent's length. After that it is
  `(prevErr - err) / prevStep`.
* The step is clamped to `±limit` (`max.s`, then `min.s`) and the new `t`
  goes through `ClampParam`. A step whose sign is against the previous
  one's halves `limit`, which starts at 1.
* It runs at most 998 iterations and answers the last `t`.

## CalibrateLength(samples)

For each point `i`:

1. Store the running total in `cp[i].w`.
2. Raise the dirty flag.
3. If `i < MaxParam`, sum `samples` chords across the segment, at
   `i + j/samples` for `j = 1 .. samples`.

The flag goes up on every pass, so every segment's first `GetPoint` reruns
the fixup against the `w` values written so far and against the `Length`
from before the call. `Length` is set to the total at the end, and the flag
is raised once more.

A LINE spline's last point starts no segment (`!(i < MaxParam)`).

## bFMod's saturation

The checker found this: `ClampParam(3e9)` on a LOOP spline came back as
5.1e9 on the host. `bFMod` truncated its quotient with a C `(int32_t)`
cast, which is undefined past 2^31 and gives 0x80000000 on x86. The EE's
`cvt.w.s` saturates to 0x7fffffff instead.

`bFMod` and `bSinF` now truncate with `ee_trunc_w`. `bmath_check` gained
quotients and angles past 2^31, and its model's `trunc32` now saturates as
the EE does.

## Not ported

`DoSnapshot` waits on ReplaySnapshot.
