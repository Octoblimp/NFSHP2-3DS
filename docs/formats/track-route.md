# `TrackRoute.obj` -- the centreline, and the signs along it

Everything that drives without a controller needs to know where the road is.
`TrackRoute.obj` is that knowledge: a set of numbered routes, each a run of
points spaced about 24 units apart, each point carrying a position, a
direction, a width either side, two slopes, and twenty-one *driving lines* --
lateral offsets and speeds that the AI and the traffic follow.

    TrackRoute.obj    0x001b6f60 .. 0x001b9428     9.9 KB

The port is `3DS Files/source/trackroute.c` and `trackroute.h`, cross-checked
by `tools/trackroute_check.py` (1353 transcript lines, 58 mutations, one of them equivalent and argued for in that file). The port follows retail
(`SLES_507.31`) where retail changed the object: see "Retail", below. It sits on `bvector.c`
(`docs/formats/bmath.md`), on `bchunk.c` (`docs/formats/bchunk.md`), and on
`trackpath.c` (`docs/formats/track-path.md`) for the distance round the lap.

## A correction to the task list

`TASKS.md` entry 24 asked for "`espEmptyLayer` -- 'Esp' spline/track-layer
format". There is no such format. **Espresso** is bware's live remote editor
protocol, spoken over `bFunk` to a PC-side server; **Caffeine** is the thing
on the other end of it. The evidence is in the image:

| where | what |
|-------|------|
| file `0x1a40c8` (VA `0x2a30c8`) | the string `EspressoServer` |
| file `0x1a4142` | `Espresso version conflict.  Caffeine = %d, Espresso = %d` |
| mdebug | `EspressoFunctions:t306=eEF_IsCaffeineRunning:0,EF_InitCommunication:...,EF_LoadWorld:3,EF_ReloadWorld:4,...` |
| mdebug | `UpdateToCaffeine__10TrackRoute`, listed beside `EraseDrivingLine` |

`EspClient.obj` is a client for that server. `TrackRoute::UpdateToCaffeine`
(`0x1b7de8`) pushes a route down the wire to the editor; its only caller is
`TrackRouteEditor::Service`, which is dead in the retail build. None of it is
a file format and none of it is ported. What *is* on the disc, and what this
document describes, is the TrackRoutes chunk.

## Where things are

| address | what |
|---------|------|
| `0x1b6f60` | `Signpost::GetNewRoute` |
| `0x1b6f88` | `Signpost::GetNewRoutePoint` |
| `0x1b6fc8` | `ReverseSigns` |
| `0x1b7080` | `Signpost::IsRacingRoute` |
| `0x1b7090` | `Signpost::SetDistances` -- the double indirection, below |
| `0x1b7120` | `GetSignpostIndex` |
| `0x1b7168` | `TestSignpostConsistency`; the asserts went out with NDEBUG |
| `0x1b7290` | `TrackRoutePoint::TrackRoutePoint` |
| `0x1b72e0` | `GetPosition` (2D) |
| `0x1b7358` | `GetPosition` (3D), two VU0 fmas |
| `0x1b73e0` | `SetWidth`, clamped to `[1, 64]` |
| `0x1b7448` | `GetSignpost` |
| `0x1b7460` | `SwapPointData` -- 48 bytes, not 112 |
| `0x1b74c0` | `ReversePoint` |
| `0x1b75d8` | `ReverseTrafficRoutePoint` |
| `0x1b75f0` | `GetDistanceAway` |
| `0x1b7660` | `TrackRoute::TrackRoute` |
| `0x1b7760` | `AddPoint` |
| `0x1b7818` | `GetPointNumber` |
| `0x1b7858` | `GetRelativePoint` |
| `0x1b78d8` | `CalculatePointDirection` |
| `0x1b79e0` | `MovePoint` -- the elevation bug, below |
| `0x1b7a90` | `FindClosestPoint` |
| `0x1b7c78` | `FindClosestPointAhead` |
| `0x1b7d28` | `EraseDrivingLine` |
| `0x1b7de8` | `UpdateToCaffeine`; not ported |
| `0x1b8200` | `HasDrivingLineData` |
| `0x1b8280` | `ReverseRoute` |
| `0x1b84e8` | `ReverseTrafficRoute` |
| `0x1b8548` | `SetFirstAndLastPoints` |
| `0x1b86c8` | `DistanceIsWithinRoute` |
| `0x1b8738` | `TrackRouteManager::TrackRouteManager` |
| `0x1b87e8` | `AddRouteToRightList` |
| `0x1b8848` | `TrackRouteManager::Loader` |
| `0x1b88e8` | `TrackRouteManager::Unloader` |
| `0x1b8a00` | `ReverseRoutes` |
| `0x1b8ce0` | `TrackRouteManager::FindClosestPoint` |
| `0x1b8e60` | `TrackRoutesLoader` -- the chunk hook |
| `0x1b8ec8` | `TrackRoutesUnloader` |
| `0x1b8f20` | `SignpostsPresent` |
| `0x1b8f30` | `HeapSort` |
| `0x1b9170` | `CompareSignposts` |
| `0x1b9188` | `InitTrackRoutes` |
| `0x1b9428` | `CloseTrackRoutes`; empty |
| `0x3241d0` | `SignpostArray` (gp-18976) |
| `0x3241d4` | `NumSignposts` (gp-18972) |
| `0x3219f8` | `1/24`, the reciprocal point spacing |
| `0x3219fc` | `999.0`, `EraseDrivingLine`'s "no lap time" |

`gp` is `0x328bf0` in this image.

## The chunks

Two, both inside the track bundle, both plain payloads with the standard
eight-byte `bChunk` header (`docs/formats/bchunk.md`).

| type | what |
|------|------|
| `0x00034121` | `TrackRoutes` -- the routes, as truncated memory images |
| `0x00034122` | `Signposts` -- a flat array of 12-byte records (8 in the demo) |

Neither chunk has a count field. The signpost count is the payload size
divided by twelve, a `divu` in retail where the demo shifted by three. The
route count is however many records the walk finds before it runs off the
end.

In retail `TRACKB12.BUN` (`extracted-retail/`): the routes chunk is at
`0x797780`, 302008 bytes, 17 routes. The signposts chunk is at `0x7e1340`,
672 bytes, 56 signposts. The demo's `extracted/TRACKS/TRACKB12.BUN` has the
same routes at `0x7af66c` and the same 56 signs in 448 bytes at
`0x7f922c`.

### TrackRoutes: memory images with the tail cut off

The loader does not parse anything. It casts the chunk's bytes to
`TrackRoute *` and registers the result, so the records on disc are exactly
the in-memory layout -- except that the 1024-entry point table is truncated
to the points the route actually has. The stride is therefore

    115752 - (1024 - NumPoints) * 112

and the walk reads `NumPoints` out of each record to find the next one. The
routes are never copied; a `TrackRoute *` the game holds points into the
bundle, which is why `Unloader` unlinks them and does not free them.

    TrackRoute, 115752 bytes

    offset  size   field
    0       4      bTNode::pNext        -- list link, garbage on disc
    4       4      bTNode::pPrev        -- list link, garbage on disc
    8       2      Version              -- 1 on every shipped route
    10      2      RouteNumber
    12      4      Type                 -- 0 racing, 1 traffic
    16      4      NumPoints
    20      4      MaxPoints            -- equals NumPoints on disc
    24      4      Flags                -- bit 0 MemoryImageLoaded,
                                           bit 1 Reversed,
                                           bit 2 DontTakeTarget (retail)
    28      4      CurrentlyTuningDrivingLine
    32      4      fStartDistance       -- recomputed at init
    36      4      fEndDistance         -- recomputed at init
    40      1008   DrivingLineInfo[21]
    1048    8      BBoxMin              -- bVector2
    1056    8      BBoxMax              -- bVector2
    1064    ...    TrackRoutePoint[NumPoints]

The two list pointers are 32-bit EE pointers that the loader immediately
overwrites when it links the route. The port declares them as `uint32_t` and
never dereferences them, which is what keeps `sizeof(TrackRoute)` at 115752
on a 64-bit host; there is a compile-time assert on that in the header,
because a record overlaid on chunk bytes that is the wrong size is a silent
disaster rather than a loud one.

`fStartDistance` and `fEndDistance` are zero on disc. `InitTrackRoutes`
overwrites both.

    DrivingLineInfo, 48 bytes

    offset  size   field
    0       4      Flags        -- bit 0 IsValid, bit 1 IsFake
    4       4      LineTime     -- 999.0 means "no lap recorded"
    8       40     DriverName

    TrackRoutePoint, 112 bytes

    offset  size   field
    0       8      Position             -- bVector2, x and z of the world
    8       4      Elevation            -- the world's y, kept apart
    12      8      Direction            -- bVector2, unit
    20      4      Length               -- to the next point
    24      4      LeftWidth            -- [1, 64]
    28      4      RightWidth           -- [1, 64]
    32      4      BankSlope
    36      4      ForwardSlope
    40      4      DistanceAroundTrack
    44      4      Bits
    48      42     DrivingLineOffsets[21]   -- int16, Q8
    90      21     DrivingLineSpeeds[21]    -- uint8, whole units
    111     1      RouteNumber

Position is two-dimensional and elevation is a separate float, which is why
`GetPosition` comes in a 2D and a 3D flavour and why the 3D one has to
assemble `(x, elevation, y)` by hand.

The flag word:

    bits 0-7    SignNumber      0xff = no signpost here
    bits 8-13   RoadBlockNumber 0x3f = none
    bit  14     NoHelisheet
    bit  15     Posted
    bits 16-21  TerrainType
    bits 22-27  RadarTrapNumber 0x3f = none
    bit  28     PostedBackwards
    bits 29-31  unused

The constructor sets `SignNumber`, `RoadBlockNumber` and `RadarTrapNumber` to
all-ones and clears `NoHelisheet`, `Posted` and `PostedBackwards` in a single
read-modify-write, then zeroes the two slopes -- and touches nothing else.
Position, widths, direction and the driving lines keep whatever the memory
held. That is deliberate and the harness relies on it: it fills a point with
a known pattern before construction and prints what survived.

### The driving-line scales

An offset is Q8: the stored `int16` divided by 256 is a lateral displacement
in world units. A speed is whole units. Both are read in the listing as a
shift into the high half of a word followed by a multiply by `2**-16`, which
is the EE's usual way of turning a small integer into a float without a
`cvt.s.w`:

    offset = (float)(stored <<  8) * 0x37800000   // 2**-16, net 1/256
    speed  = (float)(stored << 16) * 0x37800000   // net 1/1

The Q8 reading is confirmed from the consumer rather than inferred:
`RealController::CalculateLateralPostionAndVelocityWRTDrivingLine`
(the misspelling is theirs)
(`0x224ff8`) divides the same field by 256.0 and passes the result as a
lateral argument. On track 12 the offsets run to about +/-4200, which is
+/-16 units of road, and the speeds to about 101.

Racing routes use them; traffic routes (50, 51, 60, 61 on track 12) have all
offsets zero and a flat speed.

### Signposts

    Signpost, 12 bytes in retail, 8 in the demo

    offset  size   field
    0       1      NewRoute     -- route number, < 50 means racing
    1       1      Flags
    2       2      NewPoint     -- index into that route's point table
    4       4      Distance     -- uninitialised on disc
    8       4      AIHint       -- retail only: 0, 1 or 2

    Flags: bits 0-2 Sign, bit 3 Backwards, bit 4 NoStakeout,
           bit 5 Hairpin, bit 6 Cloaked

A signpost marks a junction: standing at `NewPoint` on `NewRoute`, the road
branches, and `Sign` says what the AI makes of it. The .mdebug declares
Signpost's predicates in this order: IsFaster, IsSlower, AlwaysTake, IsStop,
IsEquivalent, IsDontTake. Those are Sign 0 to 5, and retail's
`AICarController::SignPostDecision` bears out the three it tests alone.
It takes 2 at once, takes 4 on a coin flip, and never takes 5.

    Sign   0 Faster  1 Slower  2 AlwaysTake  3 Stop  4 Equivalent  5 DontTake

`AIHint` is retail's. Across all 30 retail tracks it is 0 (1,628 signs),
1 (264) or 2 (128). Only 2 is tested, in SignPostDecision: a car that takes
such a sign keeps its index (controller +684). `ExecuteCurrentAction` then
holds it to the far point's driving-line speed until `DoStickyDecisions`
drops the sign behind it. What 0 and 1 mean is not read anywhere. The AI's
retail pass will name the field properly; `trackroute.h` calls 2
`SIGNPOST_AIHINT_HOLD_LINE_SPEED`.

`Distance` is **not** meaningful on disc -- track 12's values range from
`1.4e-45` to `5.6e+14` and are plainly whatever the editor's heap held.
`Signpost::SetDistances` fills them at load.

### The double indirection in `SetDistances`

The obvious implementation would take sign `i`, look at its target point, and
measure that point's distance around the track. The disc does not do that. It
takes sign `i`, looks at its target point, reads the **sign number stored in
that point**, and measures the distance of *that* second sign's target point:

    p      = signs[i].GetNewRoutePoint()
    other  = SignpostArray[p->Bits & 0xff]
    target = other.GetNewRoutePoint()
    signs[i].Distance = DistanceAroundTrack(target->Position)

This looks like a bug and is not. On track 12 the signs come in pairs: the
point named by sign `i` carries sign number `i ^ 1` -- the same junction
approached from the other direction -- so a pair ends up sharing one
distance, which is exactly what a junction wants. All 56 signs resolve in
range; the probe in `tools/` checks this and reports no problems.

The port adds one bounds check the disc does not have (`if the point's sign
number is >= NumSignposts, skip`). It cannot trigger on shipped data and
costs a compare.

## What `InitTrackRoutes` does

Called once the track-specific bundles are in, from
`EndGameFlowLoadingTrackSpecific` (`0x164684`):

1. If the race runs backwards, reverse every route (slots 50-69 get
   `ReverseTrafficRoute`, which only mirrors distances; everything else below
   70 gets the full `ReverseRoute`) and reverse every sign.
2. Retail only: every DontTake sign (`(word & 0x700) == 0x500`) sets
   `DontTakeTarget` on its `NewRoute`. The store goes through
   `GetNewRoute`'s result unchecked. The port skips a sign whose route is
   not loaded, which no retail track has.
3. `SetFirstAndLastPoints` on every registered route.
4. `SetDistances` on every sign.
5. Sort the signs by distance with `HeapSort`, then rewrite every point's
   `SignNumber` through the resulting permutation so the indices still point
   at the right signs.

Step 5 is why `GetSignpostIndex` can be a linear scan that stops at the first
sign whose distance is not below the query: after the sort the array is in
track order.

`HeapSort` (`0x1b8f30`) is Numerical Recipes' heapsort transcribed one for
one, one-based indices and all, with the held-out element in a `malloc`'d
slot rather than a local. The comparison function returns a `float`, not an
`int`.

## `SetFirstAndLastPoints` and the two buckets

A route can straddle the start line, so its span is not simply
`[min, max]` of its points' distances. The routine walks the points, watches
for a jump of more than half a lap between consecutive ones, and flips
between two buckets each time it sees one. If it never flipped, the span is
bucket zero's min and max. If it did, the span is the **larger** of the two
minima and the **smaller** of the two maxima -- the wrapped reading.

Point zero seeds the jump test but is never put in a bucket. A one-point
route therefore comes out with `fStartDistance = TrackLength` and
`fEndDistance = 0`, which `DistanceIsWithinRoute` then reports as containing
only those two distances. Nothing on the disc has a one-point route.

## Two shipped quirks the port keeps

**`MovePoint` sets elevation from `pos->x`.** The listing stores the same
register into `Position.x` and into `Elevation`; `pos->z`, which is what the
caller passes as the height, is never read. Only the track-route editor calls
`MovePoint`, so the bug never ran in a shipped build. Kept, and flagged by a
mutation in the checker (`movepoint-elevation-fixed`) so that anyone who
"corrects" it finds out.

**`GetPosition` (3D) does not write `pad`.** The VU0 macro-mode ops work on
four lanes, but the `w` lane's two inputs are stack slots the function never
initialises, so the fourth component of the output is whatever was there. The
port leaves `pad` alone rather than inventing a value.

## What is not ported

`UpdateToCaffeine` (`0x1b7de8`), for the reason at the top.

`TrackPathCoordinate::UpdatePosition` (`0x1f5dd0`, into `0x1f5620`) used to
be a hole here: `SetFirstAndLastPoints`, `SetDistances` and
`TestSignpostConsistency` all measure through it, and it needs
`QuickSpline.obj`. Both are ported now (`docs/formats/track-path.md`,
`docs/formats/quickspline.md`), so on hardware these run for real.
`gTrackPathDistanceFn` stays as a test seam. It is `NULL` on hardware. In
this checker it is a closed-form ramp, built only from add, multiply and
compare so that the model reproduces it bit for bit. That keeps TrackRoute's
own arithmetic checkable without a spline under it. `trackpath_check.py`
checks the real measurement.

## Retail

The retail image changed eight of the object's functions (`docs/retail.md`,
the audit). Four only step through the signs by retail's 12:
`GetSignpost` (retail `0x1c14f8`), `ReverseSigns` (`0x1c1060`),
`SetDistances` (`0x1c1138`) and `GetSignpostIndex` (`0x1c11d8`). The others:

- `TrackRoutesLoader` (`0x1c2f18`) divides the signpost payload by 12.
- `TrackRoute::TrackRoute` (`0x1c1710`) clears `DontTakeTarget` with the
  other two flags. Its register use around the bounding box changed, and
  the arguments did not.
- `InitTrackRoutes` (`0x1c3250`) gains step 2 above, and its sort gathers
  12-byte signs.
- `HeapSort` (`0x1c2ff8`) differs only in the line number it passes to
  `bMalloc`: 1156, the demo's 1148.

`TrackRoute` itself is unchanged: `TrackRouteManager::Loader` (retail
`0x1c2900`) still steps by 115752 less the missing points, and the audit
has it `same`.

Nothing in retail reads `DontTakeTarget`: no load of route +24 is followed
by a test of bit 2 anywhere in the image. The port sets and clears it
anyway, because retail does.

Retail's signpost globals are `SignpostArray` at gp-18376 (`0x331128`) and
`NumSignposts` at gp-18372 (`0x33112c`), with gp `0x3358f0`.

## Checking it

    python tools/trackroute_check.py
    python tools/trackroute_check.py --mutate

The harness is `tools/src/trackroute_test.c` and the model is
`tools/trackroute_check.py`, written from the disassembly rather than from
the C. Eleven scenarios, 1353 lines, every float printed as `%.9g` so a
one-ulp disagreement is a changed line. The model is retail's where retail
changed the object. The last scenario loads retail `TRACKB12`'s and
`TRACKB21`'s own routes and signs from `extracted-retail/`. It runs the
loader, both inits and the unloader over them: 56 and 78 signs, and on
`TRACKB21` its one DontTake sign marking route 17. A disc sign's `Distance`
before `SetDistances` can be a NaN (two on `TRACKB21`), so the transcript
spells NaN as `nan` on both sides.

The model represents every record as a byte image with accessors at the
offsets the listing's loads and stores use, for the same reason the port has
a `sizeof` assert: on a format that is loaded by casting, a field at the
wrong offset has to be a visible failure.
