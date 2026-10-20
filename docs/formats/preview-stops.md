# The Zone Preview stops

Where the Zone Preview camera pauses on its way out: the cops, spike
strips and helicopter of a cop race, or the leaders, airborne cars and
crashes of a race without cops. Retail's `0x00165a70` and its helpers
(`0x001657a0` to `0x00165a38`), from `zonecameras.cpp`, with five methods
of other classes it needs. New in retail: the demo's preview has no
stops. Ported in `previewstops.c` (TASKS 80b). The mover's constructor
(`zonepreview.c`, `0x00162190`) calls it once, with at most 4 stops, after
MakeSplines (`docs/formats/preview-splines.md`).

## The calls

| retail | port | what |
| --- | --- | --- |
| `0x00165a70` | `preview_route_find_stops` | the stops, onto the look spline, below |
| `0x001657a0` | `pause_centre` | a stop's centre, the mean of its points |
| `0x00165828` | `pause_try_add` | a point joins a stop when within 20 of each of its points |
| `0x00165908` | `add_stop_point` | a point into the first stop that takes it, else a stop of its own |
| `0x001659d0` | `preview_stop_compare` | the HeapSort compare: a's parameter less b's |
| `0x001659e0` | `seen_add` | a cop onto the seen list, room for 6 |
| `0x00165a38` | `seen_has` | the cop on the seen list |
| `0x00167748` | (inline) | the stops freed: each stop's points, then the stop |
| `0x0018a160` Spline | `spline_approach_cosine` | the cosine between the way from a point to the spline and the spline's way |
| `0x0018a238` Spline | `spline_find_approach_param` | where on the spline that cosine is `target` |
| `0x00190088` Linear::GetInverse | `linear_get_inverse` | `(y - b) / m`, or `b` when `abs(m) <= 0.001` |
| `0x00152690` TopologyCoordinate | `topology_segment_blocked` | a segment through the topology, in steps of at most 30 |
| `0x00241960` tSpikeStrip | `tspikestrip_get_centre` | the mean of the elements' positions, the sum for fewer than 2 |

The last five belong in `spline.c`, `average.c`, `topology.c` and
`copmanager.c`; they are in `previewstops.c` until those modules take
them.

Retail returns the count; the constructor drops it. Its first argument,
the route, is not read. Its ninth, `maxStops`, is on the caller's stack,
and its two arrays are on its own, sized at the call: `maxStops` entries
of 32 bytes (the parameter, then the centre at +16) and a byte per look
control point but the last. `look` needs a control point: with none the
byte array's size is -1, and retail's stack runs away.

## What it reads

| where | what |
| --- | --- |
| gp-15620 | pCopManager; with none, the race's stops |
| manager +8, +16 | nNumCops, Cops[7] |
| manager +44 | the pursuits; a pursuit's roadblock at +20 (GetActiveRoadBlock, GetNumActiveRoadBlocks) |
| manager +80 | the spike strips: roadblock ID +24, elements +40, element positions +128 every 112 |
| cop +4, +16 | its car, DesiredLogicState |
| roadblock +0, +4, +104 | its two cops, nIndexIntoLoadedData |
| gp-22120 | pCurrentWorld: collisions +16, Helicopter +24, AICarPos +32, CopCarPos +36, CarTable +44 |
| helicopter +728, +832 | Plan, CurrentPos |
| car +28, +80, +96, +956 | its RacingCar (RacePosition +10, a byte), GeometryPosition, Position, nWheelsTouchingGround |
| collision +0, +32 | the next, CurrentContactPoint |
| gp-22272 | pCurrentRace, for GetRacingCar |

## The stops

A stop is a list of points (`PreviewPause`, 16 bytes; its points
`PreviewPausePoint`, 32, the position at +16, each bMalloc'd 16-aligned).
A point joins the first stop all of whose points lie within 20 of it, else
starts one on the end.

With a cop manager, in order:

1. Each spike strip's centre. The cops of each active roadblock whose
   `nIndexIntoLoadedData` is the strip's roadblock ID are seen.
2. Each cop in `Cops[0..nNumCops)` not seen, by the jump table at
   `0x002b1ff0`: SPEED_TRAP (3), DRIVING_ON_PATROL (5), CAUGHT_SPEEDER (7)
   and GUARD_LOCATION (8) at its car's GeometryPosition; ROAD_BLOCK (4) at
   its car's, or halfway between its first active roadblock's two cops'
   cars when both are there and closer than 10, and that roadblock's cops
   are seen; any other state, none.
3. The helicopter, when its Plan is below START_CHASE (3), unsigned, or
   BOMBING_RUN (4).

The seen list holds 6; a seventh is not seen.

Without one: the first car from `CarTable[AICarPos]` to `CopCarPos` in
first place, then each in second place or with no wheel on the ground, at
its Position; then each two-car collision's CurrentContactPoint. These
start stops and never join one: a point within 20 of a stop is dropped.

Then, for each stop in the order found, until `maxStops`:

1. Its centre's parameter `t` on the eye-forward spline, where the cosine
   is -0.6 within 0.01.
2. `x = last(look) * lookParam(eyeParam⁻¹(t / last(eyeForward)))`, where
   `last` is n for a loop, n - 1 for the other two and 0 for anything
   else. Floored: truncated, less 1 when that was above.
3. That control point, or the one before when it is taken or out of the
   array; neither, the stop is dropped.
4. Dropped unless strictly between `last(look) * lookParam(0)` and
   `last(look) * lookParam(1)`.
5. Without a cop manager, dropped when the topology blocks the segment
   from the eye-forward spline at `t` to the centre.
6. Kept when the centre is within 60 of that point: the control point is
   taken.

The kept stops are HeapSorted by parameter into `stops`; past the count,
`stops` is left alone. The look-ahead spline (empty, as the mover makes
it) gets each look control point, or for a stop's the stop's centre, and
DownSampleXY smooths it in XY at 0.3333 with the stops pinned. The stops
are freed, each one's points then itself.

## The helpers

`spline_find_approach_param` walks the control points: where the cosine
less the target changes sign between `i - 1` and `i`, the pair whose
midpoint is nearest the point wins (the first on a tie). With none, it
returns `last + 1` when the last sign was below zero, else -1. Otherwise
it halves from the pair's lower end, at most 10 times, while the cosine is
more than `tol` off: the sign to beat starts as the last control point's
and moves with the upper end.

`spline_approach_cosine` normalises the way from the point to the spline
and the spline's derivative with VU0's `vrsqrt`, and dots them, x and y
then z.

`topology_segment_blocked` sets one interest box halfway along a segment
shorter than 30 (radius half its length) and asks SegmentIntersects with
radius 0.5. A longer one goes in `ceil(len * 0.033333335)` steps from `b`
to `a`, a box at each step's middle, stopping at the first hit. Its
interest boxes have no velocity.

## The values

| value | where | what |
| --- | --- | --- |
| 20 | `0x00165880` | a point joins a stop within this of each point |
| 10 | `0x00165d38` | a roadblock's cops' cars closer than this, the stop between them |
| 6 | `0x00165a10` | the seen list |
| -0.6, 0.01 | gp-30704, gp-30700 | the approach cosine and its tolerance |
| 60 | `0x001663c8` | a stop farther than this from the camera's point is dropped |
| 0.3333 | gp-30696 | DownSampleXY's fraction |
| 0.001 | gp-29944 | GetInverse's flat slope |
| 30, 0.033333335, 0.5 | `0x001526f4`, gp-31332, `0x00152710` | the topology's step, its inverse and SegmentIntersects's radius |

## On the 3DS

The port's arrays are VLAs, as retail's stack. Its centres' fourth lane
starts from 0 where retail's starts from a stack word; nothing reads it
but the look-ahead spline's points, whose fourth lane nothing reads.
HeapSort is `heap_sort` in `trackroute.c`, which mallocs its holding slot
where retail bMallocs it.

## The check

`tools/previewstops_check.py` runs the image's `0x00165a70` and the five
other classes' methods in mipsemu, with GetActiveRoadBlock,
GetNumActiveRoadBlocks, GetRacingCar, Spline's `GetPoint`,
`GetDerivative` and `AddControlPoint`, `Linear::GetValue`, HeapSort and
the list's destructors as the image has them, against a host build of
`previewstops.c` over the port's own `spline.c`, `copmanager.c`,
`race.c` and `trackroute.c`. bMalloc, `__builtin_delete`,
IsTwoCarCollision, SetInterestBBox, SegmentIntersects and DownSampleXY
are stubs printing what they get on both sides and answering from a
script; HeapSort's holding slot is unprinted. The script runs GetInverse
on and about the flat slope; the spike centre on 0 to 20 elements; the
blocked segment from 0 to 300 long, exactly 30, 60 and 90 along each
axis, with scripted hits; the cosine and the approach on each spline
type, splines of 1 to 3 points, points before, beside and past them,
tolerances of 0 to 0.5, a hairpin whose nearer crossing pair picks the
arm, and a target met exactly at a halving; and the stops: random cop
races with every state, plan and roadblock shape, a seen list
overflowing, roadblock pairs at 9.99, exactly 10, 3 and 25, a cop in two
active roadblocks, random races with leaders, airborne cars, collisions
and blocked segments, stops spread past `maxStops`, stops 36 to 52 off a
straight road (either side of the 60 cut), Linears that land every stop
on one control point (the floor's edges, the taken point and the one
before, below zero, both bounds met exactly), clamped and looped splines
of 10 and 30 points, and the float edges: segments exactly 30.0 long
whose one step does not land back on their start, cars 20 apart by
retail's order of the squares' sum and not by the other (both ways), and
cars stacked 25 apart in z.

    python tools/previewstops_check.py           # 58 scenarios, 2051 ops, 7846 lines, 0 differ
    python tools/previewstops_check.py --mutate  # 136 mutations, 134 caught, 2 equivalent

The two equivalent ones (`blk-dir-pad`, `blk-cur-pad`) change the
blocked segment's and its step's fourth lane. That lane reaches only
SetInterestBBox, which takes x and y, and SegmentIntersects, which takes
x, y and z.
