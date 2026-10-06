# CarCollisionPredict -- which car an AI car's target runs it into

    0x001e5e60  CarCollisionPredict::WhoWillThisDriveTargetHit(
                    DriveTarget *, NearbyCarList *, DrivingLocation *,
                    float, float *)
    0x001e6010  CarCollisionPredict::IsThisCarStoppedDirectlyInFrontOfMe(
                    NearbyCar *, NearbyCarList *)
    0x001e60a0  CarCollisionPredict::WillIHitThisCar(DriveTarget *,
                    DrivingLocation *, Car *, Car *, float, float *)
    0x001e6860  CarCollisionPredict::MakeOBBsForDriveTarget(DriveTarget *,
                    OBB *, Car *, float)
    0x001e72f8  WhenWillOverlapOccur2D(OBB &, OBB &, bVector4 &,
                    bVector4 &)
    0x001e7238  TimeIntervalForSeparatingAxis(float, float, float,
                    float &, float &)
    0x001e6ac0  IntervalOverlap(float, float, float, float, float &,
                    float &)

Step 11b-4a of the racer AI. Before an AI car settles on a DrivingChoice
(`ai-driving-choice.md`), it asks which car the DriveTarget it would drive
(`car-drive-target.md`) runs it into, and when.

Each car's path is turned into a chain of boxes, one per point of its
target. The two cars are then walked along their chains together, each at
its own speed, one leg at a time. At each step the question is when the
two current boxes would first overlap on the ground if both kept going as
they are. The first overlap within the step is the hit.

The port is `3DS Files/source/carcollisionpredict.{c,h}`.

Retail's callers all go through WhoWillThisDriveTargetHit:

- AIActionAvoidCars::CalculateScore;
- AIActionPullOver's and AIActionAvoidRoadBlock's CalculatePointsToDrive;
- DrivingChoice::IsDriveable (0x00242100).

The class has no fields: the .mdebug gives it one byte. Its one object,
TheCarCollisionPredictor, has a constructor and destructor
(0x001e7908, 0x001e78f8) that do nothing else. Nothing reads `this`, so
the port's functions take none.

The image has four more functions in the same object, and nothing calls
them. The port leaves them out:

| Address | Function |
|---|---|
| 0x001e6ba8 | SeparatingAxisTest |
| 0x001e6ce0 | OBBOverlap2D |
| 0x001e6f00 | OBBOverlap3D |
| 0x001e7648 | TimeToImpact |

The demo's Who, IsStopped and Will differ from retail's. The port is
retail's.

## The constants

CarCollisionPredict.obj's `.lit4`, and the few built with `lui`:

| Where | Value | Port | Use |
|------:|------:|------|-----|
| gp-28120, -28108, -28080 | 99999 | CCP_NO_HIT | no hit: Who's best to start, Will's hit to start and its test |
| gp-28116 | 1234 | CCP_NOT_YET | Who's time before a car is tried; never read |
| gp-28112, -28088 | 0.001 | CCP_STILL | my car too slow to try; the floor under both speeds |
| gp-28104, -28100 | 1.3 | CCP_TRAFFIC_SCALE | a traffic car's boxes |
| gp-28096, -28092 | 1.3 | CCP_BACKING_SCALE | a car backing up blind |
| gp-28084 | 0.001 | CCP_LEG_DONE | which car reached its point |
| gp-28076 | 0.001 | CCP_SAME | the hit is not 99999 |
| gp-28072 | 0.0001 | CCP_AXIS_STILL | a closing speed too small to divide by |
| gp-28068, -28060 | 9999 | CCP_NEVER | an axis that never closes |
| gp-28064 | -9999 | CCP_ALWAYS | an axis that is always closed |
| gp-28056, -28052 | 99999 | CCP_NO_OVERLAP | no overlap |
| `lui 0x40a0` | 5 | CCP_STOPPED_SPEED | stopped |
| `lui 0x41b8` | 23 | CCP_STOPPED_AHEAD | how far ahead a stopped car counts |
| `lui 0xbe80` | -0.25 | CCP_ON_ROAD | out of bounds, but still on the road |
| `lui 0x4000` | 2 | CCP_SLOW | under this, a box is not widened |
| `lui 0x447a` | 1000 | CCP_TUNING_SCALE | my box, as traffic, with the tuning mode on |

## Who

WhoWillThisDriveTargetHit answers NULL, and leaves `*when` alone, when:

- there is no location, or the location is clear;
- the target has no points, or more than 20.

Otherwise it tries each car on the list that DoWeCareAboutThisCar
(0x001ccde8) passes. Each car gets a time and a yes or no:

1. A car stopped directly in front of me is a yes, at 0.
2. A no when my car is going no faster than 0.001 m/s (the speed's
   absolute value), or when the car is the one my controller leaves out
   (CarToExcludeFromCollisionPrediction, at controller+516).
3. Otherwise, WillIHitThisCar.

A yes whose time is below the best so far, which starts at 99999, becomes
the answer. A tie keeps the earlier car. The world's
CollisionPredictionID (World+408) goes up by one for every car tried. The
increment is 0x0014e568, inlined. At the end, `*when` is the best time:
99999 with no hit.

## Stopped in front

IsThisCarStoppedDirectlyInFrontOfMe takes the list entry's place in my
car's frame (x across, y ahead). A car is stopped in front of me when all
of these hold:

- its |VelocityMagnitude| is 5 m/s or less;
- |x| < MyHalfSizeL + ApparentHalfSizeL;
- y < (MyHalfSizeD + ApparentHalfSizeD) + 23.

There is no lower bound on y. A stopped car far behind passes, but
DoWeCareAboutThisCar has already left those out.

## Will I hit this car

WillIHitThisCar copies my target and the other car's own
(`other->pCarDriver->MyDriveTarget`) and works on the copies.

My copy:

- for a traffic car (TheDriverType 3) with more than -0.25 out of bounds,
  FillWithCurrentAcceleration replaces it;
- otherwise BlendWithCurrentAcceleration bends it.

The other's copy is touched only when the other is traffic:

- filled on the same test;
- otherwise blended, unless its action is JUST_DRIVE (5).

The location is never read.

Box scales start at 1, and at 1.3 for a car under TRAFFIC_CONTROL. The
speeds are the VelocityMagnitudes.

A car backing up blind goes straight. Backing up means ForwardSpeed < 0.
Blind means any of:

- its action is GET_UNSTUCK (7) or ACCIDENT_RECOVERY (10);
- it has no action, which counts as NONE (11);
- its copy has no points.

For the other car, it must also be under AI or TRAFFIC control. Such a
car's copy becomes StraightLinePredict's single point, its speed the
absolute value and its scale 1.3.

Then:

- each speed is floored at 0.001 (`max.s`);
- a speed under 2 puts that scale back to 1;
- my scale is 1000 when I am traffic and AITrafficTuningMode is on.

Forty boxes are constructed, twenty a car, and MakeOBBsForDriveTarget fills
each car's from its copy. GetFirstPoint gives each car its first point (i
and j). Both start where they are.

The walk runs while both i and j are inside their targets and the time so
far is within `maxTime`. The time is tested before each step, so the last
step can run past it. Each step:

1. My leg runs from where I am to box i's Position, and the other's from
   where it is to box j's. Their lengths are `sqrtf`, and each time is
   length / speed.
2. The step is the smaller time.
3. d is the other's place less mine. v is the other's velocity less mine.
   Each velocity is its leg normalised to its speed (bNormalize2To).
4. If WhenWillOverlapOccur2D of box i and box j comes at or before the
   step, the hit is the time so far plus that, and the walk stops.
5. Otherwise each car moves along its leg by `(step * speed) / length`
   of it. When my time is within 0.001 of the step, my leg is done and i
   moves on; otherwise j does.

A leg of 0 divides 0 by 0. A car already at its next point does that,
for one: a target's point repeated, or a car on its point. On the EE that
is FLT_MAX, and FLT_MAX times the 0 still to go leaves the car where it
is. The port spells both divides `ee_div`.

The answer is yes when the hit is under 99999 and not within 0.001 of it.
The second test can never matter: the float below 99999 is 0.0078 away.
Then the boxes and the copies are destroyed.

Two of the walk's corners are retail's own:

- **A hit at 9999.** An axis closing at under 0.0001 m/s, with the boxes
  apart on it, answers (9999, 9999). The overlap of the intervals then
  sits at 9999, and the boxes "meet" at 9999 s. A step that long only
  happens when both cars crawl, near the 0.001 m/s floor. When it
  does, Will says yes at 9999 and Who takes the car.
- **A miss past 99999.** On such a step, a 99999 from When2D added to the
  time so far comes out past 99999. That is a no.

## The boxes

MakeOBBsForDriveTarget does nothing for:

- a NULL target, a NULL box array or a NULL car;
- a target with no points.

The half sizes are the car-space bounding box's `fabsf((max - min) * 0.5)`
on each axis, times the scale. The scale can be negative, and then so are
they.

Box 0 sits on point 0 and lies along the car (bSinCos of its Angle):

- A0 is (cos, sin);
- A1 is (-sin, cos);
- A2 is (0, 0, 1).

Box i sits on point i and lies along the leg back to point i - 1:

- A0 is that direction, normalised with bNormalize2;
- A1 is its left normal;
- A2 is (0, 0, 1).

Every pad is 0. NumPoints is read again on each pass.

## When the boxes overlap

WhenWillOverlapOccur2D takes two boxes, d (b's centre less a's) and v
(b's velocity less a's). Only x and y are read.

It uses the four cosines between a's first two axes and b's. Each of the
four axes (a's A1 and A0, b's A1 and A0) gets a reach. The reach is the
axis' own half size plus the other box's two shadows on it, summed
`(own + first) + second`.

TimeIntervalForSeparatingAxis turns the reach, d and v along each axis
into the times when the boxes overlap on that axis:

- when |v| < 0.0001, it is all time (-9999, 9999) if |d| is within the
  reach, else never (9999, 9999);
- otherwise it is `-(r + d) / v` to `(r - d) / v`, in order.

IntervalOverlap chains the four:

- it sorts the four ends with a three-pass bubble sort, strict `<`;
- the second end must lie in both intervals;
- if it does, the overlap is the second end to the third.

If any link fails, both ends are 99999. The answer:

- the start, if it is after 0;
- 0, if the overlap is going on now (starts before 0 and ends after it);
- 99999 otherwise. That includes an overlap that starts at exactly 0 (or
  -0), and one that ended in the past.

For a box MakeOBBs makes, the cosine of a's A0 against b's A1 is exactly
the negative of a's A1 against b's A0. The two reaches that use them
would come out the same either way round. Only the direct test, with axes
no rotation makes, tells them apart.

## Divergences

- **Static storage.** Retail keeps both copies and the forty boxes on its
  stack: a 4720-byte frame. The port keeps them in static storage.
  Nothing here recurses or runs off the main thread.
- **The next point, read past the end.** The image keeps each car's next
  point in a local. It reloads that from the box past the one it leaves,
  before it tests the index, so at the end of a chain it reads a word it
  never uses. The port reads the box at the top of the pass, once the
  index has been tested.
- **The EE's divide.** The two `(step * speed) / length` divides are
  `ee_div` (0x001e65ec and 0x001e65f4).

## Cross-check

`tools/drivingchoice_check.py` checks these with DrivingChoice, in the
same harness (`tools/src/drivingchoice_test.c`). The model is the retail
image in mipsemu, with the EE's divide.

Beneath these functions, the image runs everything as shipped:

- DriveTarget's copy constructor, destructor, Fill and Blend with the
  current acceleration, and GetFirstPoint;
- StraightLinePredict;
- OBB's constructor and destructor;
- GetCarSpaceBoundingBox;
- DoWeCareAboutThisCar;
- bSinCos, bNormalize2 and bNormalize2To.

The only divides by zero the script takes are the walk's two and
DoSmoothOffsetChange's slope. The checker stops if any other site takes
the EE's path. Car::GetAmountOutOfBounds is a stub that prints a line, so
both sides ask it the same questions in the same order.

The ops `A`, `Z` and `S` set up a car's acceleration, angle and box, the
car my controller leaves out, and the target's count. Ops `1` to `7` call
the seven functions. `4` dumps every box, all four lanes of each axis.

| Scenario | What it covers |
|----------|----------------|
| s_predict | my car on a target along a route; cars following, oncoming, crossing on a second route, alongside, stopped, behind and backing up; every mode and action either side of each test; the tuning mode; Who's bounds on the count |
| s_parts | IntervalOverlap, TimeIntervalForSeparatingAxis and When2D at every edge: ends that touch, -0 against 0, closing speeds either side of 0.0001, boxes that touch at -0 and at 0, axes no rotation makes. MakeOBBs over every length, NULLs, and a box inside out on each axis |
| s_meet | two cars that do meet, a second or more on: head on, catching up, at a crossing, either backing into the other (negative speeds among them), both at one speed on the route's points so their legs end together, and both crawling apart for a step past 99999. Who over the same two |
| s_stopped | the stopped test either side of 5 m/s both ways, of the box across and of 23 m ahead, and far behind |

With DrivingChoice's scenarios, the script runs 98 scenarios, 61,530 ops
and 97,604 lines, with 0 differ.

The mutation pass makes 207 mutations of `carcollisionpredict.c`, and
all are caught, 2 of them by a crash. They cover:

- every constant, `max.s` and the blind actions;
- every test's sense and bound, and each store;
- each field read, each car swapped for the other;
- the `ee_div`s spelled IEEE's way;
- the sort, its comparison and its swap.

None needed an argument, though not at first. The first pass left 25
alive, and every one was a gap in the script:

- Hits a second or more on were rare. Most hits were at 0, where the
  boxes already overlap, and there the path ahead does not matter. That
  hid the backing-up path, the blends and the step's edges. s_meet now
  makes them on purpose.
- No car was stopped near 23 m ahead or far behind, and none went
  backwards faster than 5 m/s: s_stopped.
- No box was inside out on x where its half sizes were dumped.
- No pair of axes was other than a rotation, and only that tells a's A0
  against b's A1 from a's A1 against b's A0.
- No -0 met a 0 in an order the sort's `<` and `<=` treat apart.

With DrivingChoice's 385, the pass makes 592 mutations: 590 caught (24
by a crash or a hang) and 2 equivalent, both DrivingChoice's
(`ai-driving-choice.md`).
