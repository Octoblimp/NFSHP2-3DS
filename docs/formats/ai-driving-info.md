# DrivingInformation -- what an AI car knows as it drives

    0x00193898  NearbyCarList::BuildArray(DrivingLocation *, float)
    0x001940c8  NearbyCarList::ClearArray
    0x00193d90  NearbyCarList::GetCarsIndexInArray(Car *)
    0x00193dd8  NearbyCarList::GetNearbyCar(Car *)
    0x00193e20  NearbyCarList::GetCarAhead(Car *)
    0x00193e68  DrivingInformation::Clear
    0x001941e0  DrivingLocation::Clear
    0x00239bb0  DrivingLocation::SetRoute(TrackRoute *, TrackRoutePoint *,
                                          int, bool)
    0x00239bc8  DrivingLocation::SetRoutePoint(TrackRoutePoint *)
    0x00239bd0  DrivingLocation::SetDrivingLine(int, bool)
    0x00239be0  DrivingLocation::SetRelaxedSwitch(bool)
    0x00239bf8  DrivingLocation::GetNumSecondsLeftInRelaxedSwitch
    0x00239c48  DrivingLocation::AreWeInARelaxedSwitch
    0x00239c80  DrivingLocation::IsClear
    0x001cce50  CalculateMaxAcceleration(Car *, float)
    0x001ccfd8  CanICatchThisCar(NearbyCar *, Car *, float, bool)
    0x001ccde8  DoWeCareAboutThisCar(NearbyCar *, NearbyCarList *)
    0x001ccbc0  GetCurrentCurvatureOfDrivingLine(DrivingLocation *)
    0x001cb450  HighlightDrivingLine(DrivingLocation *, int)

Step 11a of the racer AI. A racer or a traffic car carries a
DrivingInformation: the cars around it (a NearbyCarList), where it drives
(a DrivingLocation) and which way round the traffic it has chosen to go (a
DrivingChoice). Every frame, TrafficDriver::Think and AICarController::Think
rebuild the list with BuildArray. The five free functions come from the
AI's utility object, beside the route helpers in `ai-route.md` and the
three in `drivetarget.c`.

The port is `3DS Files/source/nearbycar.{c,h}`,
`drivinglocation.{c,h}` and `drivingchoice.h`. It is cross-checked by
`tools/nearbycar_check.py` against `tools/src/nearbycar_test.c`, with the
retail image running in mipsemu as the oracle. The image also runs
everything beneath these functions:

- the car's IsPoofed, WorldToCar (through CarState's cached
  RelCoordMatrix), GetForwardAcceleration and GetCarSpaceBoundingBox;
- CalculateLookAheadDistance and CompareDistances;
- GetAccelerationTable and Table::GetValue;
- the route point's GetPosition;
- bATan, bCos, bNormalize and the e-matrix calls;
- bMemSet and bMemCpy.

The only stub is the belt mover's gravity, which
[belt-mover.md](belt-mover.md) checks on its own. 99 mutations are caught,
and none are excused.

## The records

NearbyCar, 28 bytes, is one other car as this car sees it:

| Off | Field | |
|----:|-------|-|
| 0 | Position | bVector2, in the car's space |
| 8 | Velocity | bVector2, the other's less the car's, turned to the car's heading |
| 16 | ApparentHalfSizeL | its half length, seen along the car's y |
| 20 | ApparentHalfSizeD | its half width, seen along the car's x |
| 24 | TheCar | |

NearbyCarList, 464 bytes:

| Off | Field |
|----:|-------|
| 0 | MyCar |
| 4 | NumCarsInArray |
| 8 | Array[16] |
| 456 | MyHalfSizeL, the car's own bounding box's y maximum |
| 460 | MyHalfSizeD, its x maximum |

DrivingLocation, 16 bytes:

| Off | Field |
|----:|-------|
| 0 | Route (the port's pRoute) |
| 4 | RoutePoint (pRoutePoint) |
| 8 | DrivingLine, a whole word |
| 12 | LastRelaxedDrivingLineSwitchTime, a Timer |

DrivingChoice, 12 bytes: Type (CHOICE_NONE 0, CHOICE_DRIVING_LINE_0..3 1..4,
CHOICE_LEFT_SIDE_OF_CAR 5, CHOICE_RIGHT_SIDE_OF_CAR 6), pCar, and
UseExtraLateralDistance. Its methods are step 11b.

DrivingInformation, 492 bytes, is the three in that order, at 0, 464 and
480.

The demo kept DrivingLine in the word at 8 as well. `drivetarget.c`'s
DrivingLocation overload of AddPointToTarget reads only its low byte
(`lb`), which is why the stand-in had an `int8_t`. The port now keeps the
word and reads `(int8_t)` there.

## BuildArray

1. With no MyCar, or a NULL location, it does nothing at all. The image
   loads the car's DistanceAroundTrack in the branch's delay slot first,
   from address 2036 when the car is NULL. That load harms nothing, and the
   port does not make it. The location is never read for anything else,
   and neither is the float.
2. It zeroes the 448 bytes of Array.
3. The look-ahead is CalculateLookAheadDistance: the speed times
   AIDriverSecondsToLookAhead (2), at least AIDriverDefaultLookAhead (20).
   A TRAFFIC_CONTROL car multiplies it by TrafficDriverLookaheadFactor (3,
   gp-20496).
4. It walks pCurrentWorld's CarList. The car itself is on that list and is
   not skipped: at its own origin it is always within reach, so it is
   always in its own list. Once 16 are kept, the walk runs on to the end
   doing nothing.
5. A car is tried when `(IsPoofed ^ 1) & RenderingEnabled` is not 0, with
   the poofed word and the sign-extended rendering byte both taken whole.
   A poofed word of 2 with a rendering byte of 1 is tried.
6. For each car tried:
   - its position goes into the car's space by WorldToCar;
   - its velocity less the car's is taken, in all four lanes;
   - `dist` is the length of the position's x and y;
   - `round` is `|CompareDistances(its DistanceAroundTrack, the car's)|`.
   The position, the velocity's x and y and the car go into the next free
   entry before either test, so a car not kept leaves them there.
7. A car is kept when `dist <= look` or CanICatchThisCar says yes, and
   `round <= look * 3`.
8. For a kept car:
   - its velocity is turned by eRotateZ of `16384 - bATan(the car's
     velocity)`;
   - its bounding box gives `hl = (max.y - min.y) / 2` and
     `hd = (max.x - min.x) / 2`;
   - with `c = bCos(its angle - the car's)` and `s2 = 1 - c^2`, the apparent
     sizes are `L = c^2 hl + s2 hd` and `D = c^2 hd + s2 hl`.
9. The kept ones are bubble sorted by Position.y, the greatest (furthest
   ahead) first. The sort runs over a copy of all 16 on the stack, through
   an array of pointers, with `n` full passes of `n - 1` compares each, and
   then the first `n` are copied back. The compare is `c.lt.s`, so equal
   cars and NaNs keep their order.
10. MyCar is stored again, and the two half sizes are set from the car's
   own bounding box maxima. They are not halved.

The image calls CalculateMaxAcceleration for the car and hands the answer
to CanICatchThisCar, which never reads it. The port leaves the call out,
because CalculateMaxAcceleration reads only and writes nothing.

## The lookups

GetCarsIndexInArray searches the first NumCarsInArray entries for the car
and returns the first index that matches, or -1. GetNearbyCar returns that
entry, or NULL. GetCarAhead returns the entry before it, the car just
ahead: NULL when the car is first (`blez`) or missing.

ClearArray zeroes the count and both half sizes, and leaves the array
alone. DrivingInformation::Clear is that ClearArray, inline, then the
location's Clear and the choice's three words set to 0.

## DrivingLocation

Clear sets the time to 0, the line to -1 and both pointers to NULL.
SetRoute stores the route and the point, then tail-calls SetDrivingLine,
which stores the line and tail-calls SetRelaxedSwitch. That one stores
WorldTimer when its bool word is non-zero, and 0 when it is zero.

GetNumSecondsLeftInRelaxedSwitch is

    left = 3.0 - (float)(int32)(WorldTimer - time) * 0.00025

and it returns `left` when `0 <= left`, else 0, so a NaN gives 0. The
difference is converted as a signed word, so a switch time "in the future"
gives more than three seconds. 0.00025 is the tick at gp-26780.
AreWeInARelaxedSwitch is `0 < left`.

IsClear is `Route == NULL`, and nothing else.

## CalculateMaxAcceleration

    v     = speed / BoostFactor
    accel = GetAccelerationTable(RideInfo.Type)->GetValue(v)
    drag  = ((1 - DraftFactor) * Aero.Drag) * (v * v)
    if (Control.SpeedLimiter * 0.447027 <= v && drag < accel)
        accel = drag
    grade = BeltMover::GetAccelerationDueToGravity    in BELT_MOVEMENT
          = -Gravity * (BodyMatrix.v0.z / |v0|)        otherwise
    return (accel * fBeltAccelCoef - drag / Body.Mass) + grade

Notes on the terms:

- 0.447027 is miles an hour to metres a second, an anonymous `.lit4`
  (0x3ee4e0c2).
- The cap compares a drag force with an acceleration and keeps the force,
  as the image does. With real drag figures it only takes at a crawl.
- The normalise is VU0's `vrsqrt`. It is an exact divide by a square root,
  of `(x^2 + y^2) + z^2`.
- fBeltAccelCoef (gp-16600) is 1.0. Gravity (gp-19912) is 9.8.

BeltMover's is in [belt-mover.md](belt-mover.md). nearbycar.c sits below
the mover in the link, so it reaches it through `gBeltMoverGravityFn`,
which main.c points at beltmover.c's.

## CanICatchThisCar

    dist    = |Position|,  closing = |Velocity|
    diff    = mine - its forward acceleration    when the two bodies'
              x axes point the same way (x and y dot > 0)
            = mine + its                          otherwise
    t       = AIActionPassMaxTimeAheadToMakeAttempt (3, gp-18164)
    return  dist < closing * t + (diff * t) * (t * 0.5)

`mine` is the car's own GetForwardAcceleration. The image also works out
`|Position.x|` when Position.y is between -ApparentHalfSizeD and three of
it, and never uses the result. When `maxAccel < 0` it calls
CalculateMaxAcceleration and drops that answer as well. The bool is never
read.

## DoWeCareAboutThisCar

No for a NULL entry, or the list's own car. Otherwise yes when

    -((ApparentHalfSizeD + MyHalfSizeD) + bias) < Position.y

with `bias` set to -0.5 for a player's car and 0 otherwise. In words: the
other car's rear is ahead of the car's front, with half a metre's slack
for a player.

## GetCurrentCurvatureOfDrivingLine

1. It returns 0 when the location is clear, or when the route has fewer
   than 13 points from the location's point (`NumPoints - idx < 13`, with
   the index from the 112-byte divide in `ai-route.md`).
2. It takes the points at idx, idx + 6 and idx + 12. Each is placed on the
   location's driving line with GetPosition(0, lateral), where `lateral =
   (offset << 8) * 2^-16`.
3. The two chords, a - b and b - c, are normalised.
4. Their cross product comes from VU0's `vopmula`/`vopmsub`, with both z
   set to 0.
5. It returns the length of that product, negated when its z is 0 or
   more. So a straight line gives -0.

## HighlightDrivingLine

When `carIndex` is CameraFollowThisCarInstead (gp-21528), it stores the
route's number (`lh`, or -1 when clear) and the line into
HighlightDrivingLineInRouteNumber and HighlightDrivingLineNumber. Only the
route debug drawing reads them.

## Not ported

Nothing in retail calls these:

- NearbyCar's operator= (0x001937b0);
- GetLateralOffsetFromCarInDrivingLineSpace (0x001cd5c8);
- DrivingLocation's GetLineSpeed, GetLinePosition,
  DoesThisRoutePointMatchThisRoute, IsDrivingLineOkay, operator= and
  GetTextDescription.

The DoSnapshots belong to the replay.
