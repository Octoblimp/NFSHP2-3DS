# The Zone Preview course

The three splines the Zone Preview camera flies along, laid on a
`PreviewRoute`: retail `PreviewRoute::MakeSplines` (`0x00166570`) and the
free functions it calls, from `zonecameras.cpp` (`0x00164e58` to
`0x0016579c`), with two methods of other classes it needs. The demo's
MakeSplines is `0x00161c20` (2244 bytes, no NULL checks); its
DownSampleXY takes no stops. Ported in `previewspline.c` (TASKS 80b).
`zonepreview.c` calls MakeSplines from the mover's constructor, and
`previewstops.c` calls DownSampleXY with its stops.

## The calls

| retail | port | what |
| --- | --- | --- |
| `0x00166570` PreviewRoute::MakeSplines | `preview_route_make_splines` | the walk, the walls, the two ends, the slopes and the smoothing, below |
| `0x00164e58` LinearSeek | `preview_linear_seek` | `from` towards `to` by `step`, onto `to` when it is no more than `step` away |
| `0x00164ea8` EnforceHeightGap(Spline *, Spline *, int, float) | `preview_enforce_height_gap_at` | point `i` of the spline no more than `gap` above point `i` of the reference |
| `0x00164f20` EnforceHeightGap(Spline *, Spline *, int) | `preview_enforce_height_gap` | the smallest gap over a span about `i`, then the span held to it |
| `0x00165150` DownSampleXY | `preview_down_sample_xy` | the XY smoothed through a third of the points, with stops pinned |
| `0x001656b0` EnforceMaximumSlope | `preview_enforce_maximum_slope` | each point's z capped by its neighbours', forwards then back |
| `0x00189460` Spline::SetControlPoint | `spline_set_control_point` | point `i` becomes `v`, all four lanes; no bounds check, no Dirty |
| `0x0018faf0` | `graph_get_inverse` | a Graph read the other way round, new in retail |

The last two belong in `spline.c` and `graph.c`; they are in
`previewspline.c` until those modules take them.

MakeSplines has two callers: the mover's constructor (`0x00162190`), with
`this + 108`, `+ 204`, `+ 252` and `+ 300` (the look spline, the two eye
splines and `EyeParameter`), and `VisibleDrivingLine`'s (`0x00174fe8`),
with a look spline alone and NULL for the rest. Every spline and the
Linear may be NULL. The splines get their points with `AddControlPoint`,
so they should come empty.

## MakeSplines

| value | where | what |
| --- | --- | --- |
| 10 | `lui 0x4120` | a control point every 10 along the road |
| 12 | `lui 0x4140` | the walk's interest box |
| 1.5 | `lui 0x3fc0` | the look spline above the ground |
| 0.5 | `lui 0x3f00` | the eye-forward spline above the look spline |
| 10 | the step's register | the eye-backward spline above it |
| 4 | `lui 0x4080` | the route's offset's seek, a step |
| 100 | `slti 100` | the samples against the walls |
| 0.01010101 | gp-30692, -30684, -30680 | their step, 1/99 |
| 10.7 | gp-30688 | their interest box |
| 0.4 | gp-30676, -30672 | the eye splines' slope |
| 0.3333 | gp-30668, -30664, -30660 | the smoothing's share, not a third |

Nothing happens when the route's `pPoints` is NULL.

**The walk.** Starting at route point 0, `along` 0 and `next` 0, while
there is a route point after this one and `next` is short of the route's
`fDistance`:

1. The point `along` past route point `i` and the route's `fOffset`
   across it (`PreviewRoutePoint::GetPosition`, `0x00164428`), with the
   interest box 12 about it and its z the ground's
   (`GetElevation`) plus 1.5, goes on the look spline; 0.5 higher on the
   eye-forward one and 10 higher on the eye-backward one.
2. `dist = next`, `next += 10`, `along += 10`.
3. While `next` is short of `fDistance`, there is a route point after
   `i`, and `along` is past route point `i`'s `fLength`: `along` loses
   that length, `i` moves on, and the route's offset takes the new
   point's `fRouteGap`.
4. The route's offset seeks route point `i`'s `fOffset`, 4 a step.

Then `fDistance` becomes `dist`, the last control point's distance along
the road. The control points' fourth lanes are what the image's stack held
(`TrackRoutePoint::GetPosition` fills a stack vector's; the eye points'
are never written); the port's are 0. Nothing reads them.

**The walls**, with all three splines. At each sample `k` of 100, at
`t = last * k * 0.01010101` on the look spline (`last` the spline's last
parameter, below; the products in that order):

- the look point, the interest box 10.7 about it, its z the ground's plus
  1.5;
- the eye-forward spline's point at `t`, its z the look point's plus 0.5;
  `ConstrainToTopology(tc, look, eye, 1, 0)` (`0x0015fd80`, both ways, one
  side), which may move both; the forward gap is the eye's z less the
  look point's;
- the same for the eye-backward spline with 10, the backward gap.

Then, sample by sample, the four control points `at - 1` to `at + 2`
(`at = cvt.w.s(t)`) of the eye-forward spline are held to the forward gap
(EnforceHeightGap with a gap), and then the eye-backward's to the
backward gap.

**The two ends**, with the Linear, the look spline and the eye-forward
one: `first` and `last` are the eye-forward spline's last parameter times
the Linear at 0 and at 1, truncated. EnforceHeightGap over a span at each,
on the eye-forward spline, then on the eye-backward one when it is there.

**The rest**: EnforceMaximumSlope at 0.4 on each eye spline, then
DownSampleXY at 0.3333 with no stops on the look spline, the eye-forward
and the eye-backward one, each that is there.

`last`, a spline's last parameter, the image works out inline at every
use: `n` for a loop, `n - 1` for a clamped or extrapolated spline, 0 for
any other type.

## The free functions

**LinearSeek.** `step` becomes `|to - from|` when that is no more, then
`from - step` when `to < from`, `from + step` when `from < to`, else
`from`.

**EnforceHeightGap with a gap.** Nothing for an `i` below 0 or not below
the spline's count (the reference's is not checked). Point `i` is copied
whole, and when `gap < p.z - ref[i].z`, its z becomes `ref[i].z + gap` and
the copy goes back (SetControlPoint), the other lanes as they were.

**EnforceHeightGap over a span.** For an `i` in the first half
(`i < n / 2`, C's division) the span is 0 to `i + 2`, else `i - 2` to
`n - 1`. The gap starts at 1000 (`lui 0x447a`) and takes the smallest
`b.z - a.z` of the two curves (GetPoint, so past either end the
extrapolation) at each whole parameter of the span; then every point of
the span is held to it, which the bounds check keeps to the spline's
own.

**EnforceMaximumSlope.** For `i` from 1 up, point `i`'s z is capped at
point `i - 1`'s plus `slope` times their distance in XY; then for `i`
from `n - 1` down to 1, point `i - 1`'s at point `i`'s plus the same.
Each pass reads the point it has just written, so a drop runs on down
the line. No Dirty flag.

## DownSampleXY

`(Spline *, float fraction, const float *stops, int numStops)`. `count`
is `fraction * n` rounded up (`cvt.w.s`, and 1 more when that is short).
The knees, (index, parameter) pairs, are `(0, 0)`, each stop at
`bRound((count - 1) * stop / last)` and the stop, and
`(count - 1, last)`. bRound is inline (`0x00165328`): down when the
fraction is under a half, else up, so -1.5 rounds to -1 and 1.5 to 2.

The coarse points are the spline at the knees' Graph (`GetValue`,
`0x0018f9f0`) of each index `0` to `count - 1`, as an extrapolating
spline of their own. Then for each control point `i`, at
`t = i * last / (n - 1)` (in that order), the point becomes the coarse
spline's at the Graph read the other way round at `t`, with the
spline's own z at `t`. The points are rewritten while the loop still
reads the spline; only their z is read back, and at a whole `t` that is
the point's own. No Dirty flag.

The frame (`s8`):

| Offset | what |
| --- | --- |
| below | the coarse points, `count * 16`, an alloca |
| +0 | the knees, five bVector2 (the constructor loop from 4, `0x00165250`) and 8 bytes |
| +48 | the Graph (`addiu s6,s8,48`, `0x001651f8`) |
| +64 | the coarse spline |
| +112, +128 | the two points |

Four stops put the closing knee in the 8 bytes after the five; a fifth
would put it on the Graph, so four is the most (`PREVIEW_MAX_STOPS`).
The one caller with stops, `0x00165a70` (`0x00166514`), passes at most
four.

**The Graph read the other way round** (`0x0018faf0`, called only from
`0x00165528`) is GetValue's mirror: with fewer than two knees the first
knee's *y*; below or at the first knee's y the first x; at or past the
last's the last x; in the first segment `[y0, y1)` that holds `y`,
`x0 + (y - y0) / dy * dx`, or the segment's midpoint in x when `dy` is
no more than `1e-6` (gp-29948, the same word as GetValue's gp-29952).
A `y` no segment holds, a NaN, gives the first knee's y again.

**A short spline.** With 3 points or fewer `count` is 1, and GetPoint on
a one-point extrapolating spline reads the slot past it (the image's: its
knees) and the slot before it (below its stack pointer, a callee's
frame), each through the extrapolation with a weight of 0. The port keeps
a spare of zeros at each end; the two differ only if the image's stack
held an infinity or a NaN there. A one-point spline divides 0 by 0 for
its `t`: the EE gives the largest float, IEEE a NaN, so the port's z
comes back NaN. MakeSplines makes one only when its walk stops after
one point; the mover's routes are 320 long.

Not done: a NULL `stops` with a count above 0 (the image's knees between
are stack words; the port's are 0), and a negative fraction (the alloca
wraps and the knee loop does not end).

## On the 3DS

The coarse points are a variable-length array on the stack while they
are 64 or fewer (1 KB); past that, the 3DS's 32 KB stack is no place for
them and they are `malloc`'d, freed before the return (not `bMalloc`;
they are the function's own). With no room the spline is left as it is.
A route of 320 at a point every 10 gives about 11.

## The check

`tools/previewspline_check.py` runs the image's MakeSplines and the
seven functions above in mipsemu, with ConstrainToTopology,
GetPosition, Spline's constructors, `AddControlPoint`, `GetPoint` and
destructor, Graph's GetValue and `Linear::GetValue` as the image has
them, against a host build of `previewspline.c` over the port's own
`zonecam.c`, `previewroute.c`, `spline.c`, `graph.c` and `average.c`.
bMalloc, bFree, SetInterestBBox, GetElevation and ConstrainToTopology's
member (`0x001528b0`) are stubs printing what they get on both sides and
answering from a script. The script runs LinearSeek both ways and on its
edges; the Graph lookup over 0 to 6 knees, flat, close and out of order,
at each knee, between, past both ends and at a NaN; both
EnforceHeightGaps on every spline type at each end, in and past them;
EnforceMaximumSlope on 0 to 20 points at 0.4, 0, below 0 and others; DownSampleXY on
0 to 12 points of each type, long splines to 260 (the heap), whole and
not whole fractions, and 0 to 4 stops in order and not, at the ends,
past them, negative and on a half; and 46 MakeSplines on winding routes:
short walks of 0 to 3 points, a NULL route, each spline and the Linear
missing, each spline type, a growing buffer, and the flight's ends off
both ends of the splines. Each spline prints with the slot either side
of its points. Facts checked in the image: MakeSplines's two callers and
VisibleDrivingLine's NULLs, DownSampleXY's four callers and the no stops
of MakeSplines's three, the lookup's one caller, the knees' five and the
frame's +48 and +64, the two epsilons, and the three 1/99 steps.

    python tools/previewspline_check.py           # 52 scenarios, 3248 ops, 48851 lines, 0 differ; 8 facts
    python tools/previewspline_check.py --mutate  # 114 mutations, 113 caught, 1 equivalent

The equivalent one (`d-spare`) fills the spare before the coarse points
with another finite value: it is read only with a weight of 0.
