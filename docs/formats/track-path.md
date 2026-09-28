# `TrackPath.obj` -- how far round the lap

    TrackPath.obj    0x001f4fd8 .. 0x001f6058    4.2 KB

A TrackRoute (`docs/formats/track-route.md`) is where a car can drive. A
TrackPath is how far round the lap a position is. Anything that asks who is
ahead, which lap a car is on, or how far it is to the finish asks the
TrackPath:

- Car keeps a `TrackPathCoordinate` at offset 1840.
- `CompareDistances` has seventeen callers.
- `Signpost::SetDistances`, `TrackRoute::SetFirstAndLastPoints` and
  `TrackRoutePoint::GetDistanceAway` all measure with one.

The port is `3DS Files/source/trackpath.{c,h}`. It is cross-checked by
`tools/trackpath_check.py` against `tools/src/trackpath_test.c`.
Everything in the object runs as shipped in mipsemu except the two
`DoSnapshot`s and `PlotToCaffeine`. So does QuickSpline beneath it
(`docs/formats/quickspline.md`).

## The data

The track is a graph of points. Each path is a run of consecutive points
with a distance at each end. `TrackPathManager::Init` fits a QuickSpline
through each path's points and calibrates its arc length. After that, a
position is measured in four steps:

1. Find the nearest point.
2. Find the closest parameter on that path's spline.
3. Read the arc length out of the spline's `w` lane.
4. Scale it onto the lap.

### The chunk

`0x80034147` is a container of two sub-chunks. Their payloads are the two
tables, loaded in place:

| Sub-chunk | Payload |
|-----------|---------|
| first (`0x00034148` on the disc) | the `TrackPath` table, `size / 40` records |
| second (`0x00034149`) | the `TrackPathPoint` table, `size / 20` records |

`Loader` (0x001f5288) finds the sub-chunks by position, not by type. It
takes the paths from the first sub-chunk, then steps past that payload's
size and takes the points from whatever sub-chunk starts there. It never
reads either sub-chunk's type or the container's own size. Both counts
come from a `divu`; no count field exists anywhere. The port does the
same.

TRACKB12 (`extracted/TRACKS/TRACKB12.BUN`, container at 0x007a8270) has one
looping path of 55 points and a table of 56. The 56th point closes the
loop: it repeats point 0's position with distance 0. It sits outside the
path's range, so nothing but a search that runs past `End` would ever
see it.

### `TrackPathPoint`, 20 bytes

| Off | Field | Type |
|----:|-------|------|
| 0 | Position | bVector2 |
| 8 | PathNumber | int8_t: index into the path table |
| 9 | DontSwitch | int8_t: never read here |
| 10 | NeighbourNumbers[3] | int16_t: point indices, -1 for none |
| 16 | Distance | float: distance round the track |

### `TrackPath`, 40 bytes

| Off | Field | Type |
|----:|-------|------|
| 0 | PathNumber | int8_t |
| 1 | Looping | int8_t: any non-zero byte is a loop (`movn`) |
| 2 | BeginPointNumber | int16_t |
| 4 | EndPointNumber | int16_t: one past the last point |
| 6 | NumPoints | int16_t |
| 8 | BeginDistance | float |
| 12 | EndDistance | float |
| 16 | DistanceRatio | float: arc length to lap distance |
| 20 | BeginPosition | bVector2 |
| 28 | EndPosition | bVector2 |
| 36 | pQuickSpline | QuickSpline *: zero in the bundle, written by Init |

A loaded path *is* the chunk's bytes, so the record has to be 40 bytes on
every machine that loads it, and a pointer is not four bytes everywhere.
The port therefore keeps the word as a handle: zero, or a slot number plus
one into a table of 64 splines. `trackpath_path_spline()` turns the handle
back into the spline. Init still tests the word the way the disc does, and
Close still zeroes it. The table is not a real limit: the one track on hand
has one path. The checker loads and unloads seventy times so that a Close
that forgot to give its handle back would run the table dry.

### `TrackPathManager`, 24 bytes, at 0x00313768

| Off | Field |
|----:|-------|
| 0 | TrackLength |
| 4 | ReverseTrackDirection |
| 8 | NumPaths |
| 12 | pPaths |
| 16 | NumPoints |
| 20 | pPoints |

### `TrackPathCoordinate`, 40 bytes

| Off | Field |
|----:|-------|
| 0 | Position (bVector2) |
| 8 | pTrackPoint |
| 12 | SplineParam |
| 16 | RatioAroundTrack |
| 20 | DistanceAroundTrack |
| 24 | PathDirection (bVector2) |
| 32 | pCaffeineObj, 64 bits: two words, both zeroed by the constructors |

## Building and tearing down

**Init** (0x001f5048) first reads `TrackLength = pPaths[0].EndDistance`.
The load sits ahead of the count test and its store is in the branch's
delay slot, so it happens even when there are no paths, provided a table
exists. With no table at all the image reads address 12; the port stores
zero.

Then, for each path whose word is still zero, Init:

1. calls `bMalloc(40, "..\indep\src\trackpath.cpp", 73, 16)`;
2. constructs a QuickSpline in that block: LOOP for a looping path,
   EXTRAPOLATED otherwise, basis OVERHAUSER, sized to `NumPoints`;
3. stores the spline in the word;
4. calls `SetNumControlPoints(NumPoints)`;
5. copies each point's x and y in, with z and w zero and the dirty flag
   raised on every point;
6. calls `CalibrateLength(16)`.

A second Init builds nothing, because every word is already set.
`InitTrackPaths` after the loader's own Init is exactly that case.

**Close** (0x001f51b8) deletes each path's spline with the destructor's
flags 3, which frees the buffer and then the spline, and zeroes the word.
**Load** (0x001f5238) stores the four table fields and runs Init.
**Unload** (0x001f5250) runs Close, then zeroes everything except
`ReverseTrackDirection`, which keeps whatever the last track set.
**Unloader** (0x001f52f8) checks the container type and unloads. The
destructor is Close, plus a delete when flags bit 0 is set.

## The searches

**FindClosestPoint** (0x001f53c8) walks every path's `[Begin, End)` and
compares 2D distances (`sqrt.s` of the x and y squares). `c.lt.s` keeps
the first of equals. A negative index would be a NULL point read at
address 0 in the image; the port skips it. No bundle has one.

**FindClosestAdjacentPointOnSamePath** (0x001f54a8) tries up to three
candidates in this order:

1. The point itself.
2. The point before it. At the path's first point, a looping path
   supplies its last point (`End - 1`) instead; an open path supplies
   nothing.
3. The point after it. At the path's last point, a looping path supplies
   its first point (`Begin`) instead; an open path supplies nothing.

It keeps the first of equals, so the point itself wins a tie, and the one
before beats the one after. The index comes from the pointer difference
times 0xcccccccd, shifted right by 2 (`sra`): an exact divide by 20 for
any pointer into the table.

## UpdatePosition(pos) -- 0x001f5620

1. **Choose a start.** If the coordinate has no point, or `pos` is more
   than 128 units from the coordinate's last Position, do a full search.
   Otherwise start from the last point.
2. **No points at all.** Set Position to `pos`, PathDirection to (1, 0),
   and both the ratio and the distance to zero. Leave the point and the
   parameter alone, and return.
3. **Adjacent search** from the start point.
4. **Neighbour links.** For k = 0, 1, 2, move to link k if it is strictly
   nearer. Each link is read from the point that is nearest *so far*, not
   from the start point. If the first link switches points, the next two
   links are the new point's.
5. **The guess.** If the point changed, store it and restart the search
   from its own parameter, `index - Begin`, through `cvt.s.w`. Otherwise
   carry on from the last `SplineParam`.
6. **The parameter.** `FindClosestParam` on the path's spline, with the
   point `(pos.x, pos.y, 0)` and the tolerance 0.05 (gp-28124, 0x3d4ccccd).
   The point's fourth lane is a stack slot nothing writes.
   FindClosestParam reads only x, y and z.
7. **Three `GetPoint`s** at that parameter:
   - basis 0, into a temporary that nothing reads;
   - basis 1, for the tangent, whose x and y are normalised into
     PathDirection;
   - basis 0 again, for `w`.

   The port leaves out the first. It could only rerun FindClosestParam's
   endpoint fixups, and those are already clean.
8. **Distance.** `BeginDistance + w * DistanceRatio`. When the track
   runs in reverse, the direction is negated and the distance becomes
   `TrackLength - distance`.
9. **Store** SplineParam, Position, PathDirection and the distance. The
   ratio is `distance / TrackLength` by `div.s`. A track whose first path
   ends at distance zero divides by zero there. The EE gives FLT_MAX with
   the XOR of the signs, 0/0 included, so the port writes this division as
   `ee_div`.

A path with no spline would fault in the image. That can only happen in
the port, when the handle table is full, and there the port stores the
position and stops.

## UpdatePosition(along, side, path) -- 0x001f5928

The inverse, roughly. It finds a point `along` the track, offset by `side`
along `(dir.y, -dir.x)`, and measures that with the function above. Its only
caller is `CalculateRacerPositions` (0x00147a40). That function lays out
the starting grid when a track lacks enough position markers:

- it walks `along` from 10 to 100 in steps of 10;
- it then places racers two abreast, at `100 + 17 * (i / 2)` and ±3 to
  either side.

The walk starts from the coordinate's point. A fresh coordinate starts from
the first point of path `path` instead. If there is no path table, the
coordinate is reset: position zero, direction (1, 0), distance zero, ratio
zero. The walk takes the path's first and last points once and never
leaves the path. Each step does one of three things:

- **Step back.** If `along < pt.Distance` and there is a point before, move
  to it.
- **Step forward.** Otherwise, if `pt.Distance < along` and the next point's
  `Distance < along`, move to the next point.
- **Stop.** Otherwise, take the direction to the next point, or from the
  previous one at the path's end, and normalise it.

**It walks one step, not many.** The step count starts at `NumPoints`, is
decremented after each step, and the loop repeats only when the count is
*zero* (`beq a1,zero`). With any other count the walk leaves after one
step, before a direction has been worked out. So a walk that steps builds
its position from whatever direction the *previous call* left in the first
eight bytes of the frame. That reads like `--left == 0` written where `!= 0`
was meant. The port keeps it, and keeps that direction in a static.
`CalculateRacerPositions` calls it in a loop from one frame with nothing in
between, so "the previous call's direction" is exactly what the image
gets. Before the first call, the image's slot holds whatever an earlier
function left at that depth; the port's holds zero. The checker hands the
image zeros there, then carries the slot from call to call.

The position is `pt.Position + dir * along`, then `+ (dir.y, -dir.x) *
side`. The step uses all of `along`, not just the part past the point's
own distance.

**Two NULL reads the port does not follow:**

- `next->Distance` is loaded without testing `next`. At a path's last
  point, with `along` beyond that point's distance, the image reads
  address 16. It then walks to NULL and reads address 0.
- A point with neither a previous nor a next point takes its direction
  from address 0.

On the console both are the kernel's first page. The port stops at the
point, or measures along a zero direction. The checker's model traps both
reads, so no scenario can quietly depend on them. No shipped call gets
there: the grid stops at 151 units of a lap of thousands.

## The comparisons

| Function | Wrap |
|----------|------|
| `CompareDistances` (0x001f5b70) | `d = a - b`; `d < -len/2` adds `len`, else `len/2 < d` subtracts it |
| `ComparePercentDistances` (0x001f5bc0) | the same over ±50, wrapping by 100 |
| `CompareRatios` (0x001f5c28) | the same over ±0.5, wrapping by 1; nothing calls it |

`d == -len/2` fails the first test, goes on to the second, and comes back
unchanged.

## The coordinate

The constructor (0x001f5c90) zeroes everything except PathDirection.x,
which is 1.0. The one that takes a position (0x001f5cc8) then calls
`UpdatePosition(pos)`. The member `UpdatePosition`s (0x001f5dd0,
0x001f5df8) forward to TheTrackPathManager. The `along` one passes path 0,
through a tail jump that leaves the frame where it was.

`gTrackPathDistanceFn` is the port's, not the disc's. `trackroute_check.py`
sets it to a closed form so that TrackRoute's arithmetic can be checked
without a spline under it. It is NULL on the handheld, and
`trackpath_check.py` leaves it NULL.

## Retail's three

Retail's TrackPath.obj is the demo's plus three functions. The rest
match. Car's constructor ([car](car.md)) calls the second and the third,
and ResetToRoutePoint the third.

**FindClosestPoint(pos, dist)** (0x00207d48) is FindClosestPoint with a
different score. Each point scores its 2D distance plus a quarter of
`|CompareDistances(point.Distance, dist)|`, that is, how far round the
lap the point is from `dist`, the short way. On a reversed track `dist`
is first measured from the other end, as `TrackLength - dist`
(`sub.s $f21,$f0,$f21`), not `dist - TrackLength`. The first of equals
wins, as before. The distance term matters where the track crosses
itself or runs beside itself: of two legs equally near, it picks the one
at the right distance round the lap.

**ResetPosition(pos)** (0x00208838) is the demo's twelve bytes from
Car.obj, moved into TrackPath.obj. It drops the point, then calls
UpdatePosition.

**ResetPosition(pos, dist)** (0x00208848) drops the point and runs the
weighted search. If the search finds a point, it first updates the
coordinate at that point's own Position, so the coordinate holds that
point. Then it updates at `pos`. The second update starts from the seeded
point only if `pos` is within 128 of it, per step 1 of UpdatePosition.
Farther away, it searches afresh and the seed does nothing. With no
points, it is the plain reset.

## What is not ported

- `DoSnapshot`, both of them (0x001f5330, 0x001f5d40). They wait on
  ReplaySnapshot.
- `PlotToCaffeine` (0x001f5e10), a debug plot into the Caffeine editor
  that nothing calls.
- The static constructor and destructor (0x001f6000, 0x001f5ff0). C zeroes
  TheTrackPathManager, and nothing tears the manager down at exit.

## Checking it

    python tools/trackpath_check.py
    python tools/trackpath_check.py --mutate

The model is `Emu(ieee=True, eediv=True)`: IEEE single, except that a
`div.s` by zero gives the EE's answer. Every division QuickSpline does is
guarded, so the switch matters only for the ratio.

The scenarios cover:

- the three comparisons, over their boundaries;
- an empty manager;
- a looping path, an open path, and a pair joined by neighbour links:
  walked forwards and backwards, jumped, reversed, and walked with
  `UpdatePosition(along, side)`;
- integer-coordinate ties for both searches;
- a chain of links through all three slots;
- non-monotonic distances for the walk's tests;
- seventy loads;
- a zero-length track;
- the loader over built chunks, including ones whose sizes do not divide
  evenly;
- TRACKB12's own chunk, when `extracted/` has it.

The script runs twice: on the demo's image, and on retail's
(`retail_model.RetailEmu`), whose TrackPath.obj is paired with the demo's
by `retail_match`. The retail run adds scenarios for retail's three:
- the weighted search at points round a loop and beside an open road
  whose distances overlap the loop's;
- distances at 0, `-0`, past either end, NaN and infinity;
- the reversed track, including points halfway between two others, where
  only the distance term decides and the reversal flips the answer;
- integer ties, equal to the bit;
- both resets from a stale point.

The demo's ResetPosition (0x00134f18, in Car.obj) runs in both.

```
demo image:   4946 ops, 4746 lines, 0 differ
retail image: 5557 ops, 5095 lines, 0 differ
```

The mutation pass edits `trackpath.c` and `trackpath.h` in place, so
nothing that includes either may be built while it runs:

```
trackpath_check --mutate  204 mutations, 201 caught, 3 equivalent, 0 unexplained
```
