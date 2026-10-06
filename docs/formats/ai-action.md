# AIPlan and AIAction -- what every racer AI action shares

    0x001c6028  InitAIPlans(void)
    0x001c6058  CloseAIPlans(void)
    0x001cac70  AIPlan::AIPlan(float)
    0x001cac48  AIPlan::~AIPlan(void)
    0x001cab90  AIPlan::SetTimeout(float)
    0x001cab48  AIPlan::TimeToChange(AIPlan *)
    0x001cabf0  AIPlan::GetStatus, IsNotDone, Failure, Success, IsExpired
    0x001c6118  AIAction::AIAction(int, float)
    0x001c6b30  AIAction::~AIAction(void)
    0x001cab08  AIAction::operator new(unsigned int)
    0x001cab28  AIAction::operator new(unsigned int, const char *)
    0x001caaf8  AIAction::operator delete(void *)
    0x001c6a98  AIAction::UpdateStatus(DrivingInformation *)
    0x001c64e8  AIAction::SetDesiredSpeedSlowerThanThisCar(NearbyCar *,
                    NearbyCarList *, float, float)
    0x001c6530  AIAction::SetDesiredSpeedToMaxAcceleration(Car *, float)
    0x001c6588  AIAction::SetDesiredSpeedToMaxDeceleration(Car *, float)
    0x001c65e0  AIAction::GetHeadingClassification(DrivingLocation *,
                    Car *, bool)
    0x001c69d8  AIAction::GetCollisionClassification(Collision *, Car *)
    0x001caa60  AIAction::ClearPointsToDrive(void)
    0x001caae0  AIAction::GetName(void)
    0x001ccf78  CalculateMaxDeceleration(Car *, float)

Step 11c of the racer AI. An AIAction is one thing an AI car can be
doing: passing, avoiding cars, drafting, getting unstuck, and the rest of
AIActionType. AICarController (11e) scores the actions and keeps the best
as its CurrentAction. Each frame it asks that action for the points to
drive and the speed to drive them at, and asks it through UpdateStatus
whether it is done. The actions themselves are 11d. This is the base:
- the plan's timeout and status;
- the record every action fills;
- the pool the actions come from;
- the helpers the subclasses call.

The port is `3DS Files/source/aiaction.{c,h}`. CalculateMaxDeceleration
is in `nearbycar.c`, beside CalculateMaxAcceleration.

Not ported:
- the three DoSnapshots (AIPlan's at 0x001c6088, AIAction's at 0x001c6198
  and 0x001c6268), which wait on ReplaySnapshot;
- the out-of-line accessors (0x001caa98 to 0x001caaf4), which nothing
  calls. The subclasses read the fields, and so does the port. The five
  setters among them (0x001caa70 to 0x001caa90) are empty in both images;
- GetLateralDistance, which the demo has (0x001bc900) and retail does not.

## The record

AIPlan is 20 bytes (type#1103), the same in both images. Its vptr is at
16, after the data, as g++ 2.9x puts it:

| Offset | Field | |
|---:|---|---|
| 0 | CanExpire | a bool word |
| 4 | ExpiryTimer | WorldTimer's ticks when the timeout was set |
| 8 | DeltaTime | the timeout, in seconds |
| 12 | Status | PlanStatus: NOT_DONE 0, SUCCESS 1, FAILURE 2, EXPIRED 3 |
| 16 | the vptr | |

AIAction is 608 bytes in retail. The demo's stab (type#1117) is 592:
retail put a float at 572, so everything from UseDrivingLineSpeed on is
four bytes later. The record rounds up to 608, and the subclasses' fields
move by sixteen.

| Offset | Field | |
|---:|---|---|
| 0 | AIPlan | |
| 20 | | twelve bytes of padding; PointsToDrive is 16-aligned |
| 32 | PointsToDrive | a DriveTarget, 528 bytes |
| 560 | PointsToDriveWillExecuteAction | a bool word |
| 564 | DesiredSpeed | |
| 568 | TimeToGetToDesiredSpeed | |
| 572 | DesiredSpeedTolerance | retail's, the port's name |
| 576 | UseDrivingLineSpeed | a bool word |
| 580 | AllowedToUseThrottleAndBrake | a bool word |
| 584 | AllowedToUseBoost | a bool word |
| 588 | Type | AIActionType |
| 592 | Score | the constructor's int |
| 596 | | twelve bytes of round-up |

The float at 572 is zeroed by the constructor. The subclasses that set
it pass it to the driver's SetDesiredSpeed as a third float, and
PsychoDriver's CalcThrottleAndBrake coasts within that much of the
desired speed rather than use the throttle or the brake.

The port spells both pads out (`_pad20`, `_pad596`). bVector3 has no
alignment of its own in the port, so on the host that runs the checker
PointsToDrive would otherwise land at 20.

## The pool

InitAIPlans runs as a track finishes loading
(EndGameFlowLoadingTrackSpecific). It makes "AIActionSlotPool": 640-byte
slots, 15 of them, in memory pool 16. 640 is the largest action, not
AIAction's own 608. The pool's pointer is gp-18288.

CloseAIPlans runs as the track unloads. It deletes the pool if there is
one and clears the pointer, then tail-calls DestoryTargetMarkers (the
image's spelling) on TheDriveTargetRenderer, pool or no pool.

Both operator news are bOMalloc on the pool. The named one ignores its
name. Operator delete is the pool's bFree.

`main.c` points `gInitAIPlansFn` and `gCloseAIPlansFn` (`trackflow.h`)
at the two.

## AIPlan

The constructor zeroes ExpiryTimer, writes the vptr and calls SetTimeout,
leaving Status as it was. Nothing in either image constructs a bare
AIPlan. AIAction's constructor inlines this one and sets Status itself.

SetTimeout:

    CanExpire   = 0 <= timeout          (c.le.s: -0 can expire, NaN cannot)
    DeltaTime   = timeout
    ExpiryTimer = trunc.w((float)WorldTimer * 0.00025 * 4000 + 0.5)

That is WorldTimer converted to seconds and back to ticks, rounded. A
WorldTimer past 2^24 loses bits in the float, and one from 2^31 - 64
on rounds to 2^31 and saturates in trunc.w. The port spells it `ee_trunc_w`, and the checker
runs both.

TimeToChange is true for no plan (NULL), for a plan that succeeded or
failed, and for one that has expired and can. IsExpired is the last of
those. GetStatus, IsNotDone, Failure and Success compare Status and
nothing else. None of the five tests has a caller in either image.

The destructor writes the vptr and calls `__builtin_delete` when bit 0 of
its flags is set. Its one caller, AIAction's destructor, passes 0.

## AIAction

The constructor does, in order:
- AIPlan's constructor, inline;
- AIAction's vptr;
- PointsToDrive's constructor;
- Score from its int, and AllowedToUseThrottleAndBrake 1;
- Status NOT_DONE;
- DesiredSpeed, DesiredSpeedTolerance and TimeToGetToDesiredSpeed 0;
- UseDrivingLineSpeed and AllowedToUseBoost 1.

PointsToDriveWillExecuteAction and Type are left as the allocation had
them; the subclasses set them.

The destructor writes the vptr and runs PointsToDrive's destructor with
flags 2. Then it runs AIPlan's with 0, and the pool's bFree when bit 0
of its own flags is set.

UpdateStatus sets Status NOT_DONE, then asks three questions through the
vptr. Each asks with DrivingInformation, and each answer that is true
overrides the one before:

| Slot | Asks | Status if true |
|---:|---|---|
| 56 | HasExpired | EXPIRED |
| 48 | HasFailed | FAILURE |
| 40 | HasBeenAccomplished | SUCCESS |

So an action that has both failed and been accomplished has succeeded.
The vptr is loaded again for each call, and each entry's delta is added
to `this`.

### The three speeds

SetDesiredSpeedSlowerThanThisCar(nc, list, delta, unused):

    speed = nc->TheCar's VelocityMagnitude - delta
    DesiredSpeed = speed, and then max.s(speed, 0)
    gap  = (nc->Position.y - list->MyHalfSizeD) - nc->ApparentHalfSizeD
    TimeToGetToDesiredSpeed = max.s(gap / nc->Velocity.y, 0.1)

The speed is stored twice, before and after the clamp. A speed of -0
stays -0, because max.s keeps its first operand unless the second is
greater. The gap closes at the car's apparent closing speed. A car
keeping pace (Velocity.y 0) divides by zero at 0x001c6520. There the EE
gives FLT_MAX with the sign of the operands, so the time is FLT_MAX or
0.1; IEEE's infinity or NaN would leave it infinite or NaN. The port
spells that divide `ee_div`. The last float is never read.

SetDesiredSpeedToMaxAcceleration and ToMaxDeceleration(car, t):

    v = VelocityMagnitude
    TimeToGetToDesiredSpeed = t
    DesiredSpeed = v + CalculateMax{Acceleration,Deceleration}(car, v) * t

CalculateMaxDeceleration (0x001ccf78), a free function:

    down = (FrontDownforce + RearDownforce) * 0.5
    mu   = (Tires[1].StaticFrictionCoefficient
            + Tires[0].StaticFrictionCoefficient) * 0.5
    -(((|speed| * down + 9.8 * Mass) * mu) / Mass)

Both halves are computed before the weight, and the downforce term comes
first in the sum, in retail's order.

### GetHeadingClassification

A static method: whether `car` is leaving the road at the location's
route point. The answer is OKAY, OUT_OF_ROUTE_FORWARDS or
OUT_OF_ROUTE_BACKWARDS. The route point's line gives the lateral
distance:

    lateral(p) = (p.x - rp.x) * dir.y - (p.y - rp.y) * dir.x
    l = LeftWidth + lateral        r = RightWidth - lateral

**A moving car** has |VelocityMagnitude| > 1. The test point is where
the car will be in 0.1 s (`bScaleAdd2`), and `rate` is how fast `l`
grows, (l_ahead - l_now) * 10. It is out when any of these holds:
- it is on the road (both distances above 0), drifting right
  (rate > 0.001), and r_now / rate, the time to the right edge, is at
  most 1 s;
- it is off the right edge (r_now < 0) and going further (r_ahead <
  r_now);
- it is off the left edge and going further.

An out car is FORWARDS when ForwardSpeed > 0, else BACKWARDS.

Retail has a second time-to-edge test at 0x001c6718. It asks the same
three conditions as the first, with gp-28748 for gp-28756 (both 0.001),
so it is never reached: a car drifting left is never timed. The port
leaves it out.

**A barely moving car** uses the point 2 m ahead along the way it points
(bCos then bSin of its Angle). It is FORWARDS when that point is off the
right edge and further off than the car, or the same on the left.

**Then two exceptions:**
- **FORWARDS, with the steer check asked for.** Retail asks the driver's
  GetSteerToPoint (slot 160) twice. The first answer goes through
  WorldToCar into a stack copy that nothing reads. The second goes to
  IsPointAheadOfCar with 0.5, and a point ahead makes the car OKAY.
- **BACKWARDS.** The body's x axis and the route's direction are both
  made unit (bNormalize2). A dot product above 0.342 (cos 70 degrees)
  makes the car OKAY: it is backing along the route, not off it.

### GetCollisionClassification

A static method: where on the car a collision's contact point is. The
point is taken into car space (WorldToCar), and its x, across the car,
is held against the box's y extents, along it:

    if (x < max.y * 0.95 && min.y * 0.95 < x)
        IN_FRONT if 0 < y, else BEHIND
    else
        RIGHT_SIDE if 0 < x, else LEFT_SIDE

Mixing x and y is retail's own, and the port keeps it.

## The constants

AIAction.obj's `.lit4`, and the ones built with `lui`:

| Where | Value | Port | Use |
|------:|------:|------|-----|
| gp-28764 | 0.1 | AIA_MIN_TIME_TO_SPEED | SlowerThanThisCar's floor |
| gp-28760 | 0.1 | AIA_LOOK_AHEAD_SECONDS | the moving car's look ahead |
| gp-28756, gp-28748 | 0.001 | AIA_EDGE_RATE_MIN | the drift that counts |
| gp-28752 | 99999 | AIA_NO_EDGE | no time to the edge |
| gp-28744 | 0.342 | AIA_BACKWARDS_COS | cos 70 degrees |
| gp-28740 | 0.95 | AIA_BOX_SHARE | the box's share that is front or back |
| gp-28528 | 0.00025 | AIA_TICKS_TO_SECONDS | SetTimeout |
| lui 0x3f80 | 1 | AIA_MOVING_SPEED, AIA_EDGE_SOON | |
| lui 0x4120 | 10 | AIA_RATE_SCALE | 1 / 0.1 s |
| lui 0x4000 | 2 | AIA_SLOW_LOOK_AHEAD | |
| lui 0x3f00 | 0.5 | AIA_STEER_AHEAD | IsPointAheadOfCar's margin |
| lui 0x457a | 4000 | AIA_SECONDS_TO_TICKS | SetTimeout |

## The tables

| | Retail | Port's constant (the demo's) | Entries |
|---|---|---|---:|
| `_vt$6AIPlan` | 0x002b7cd0 | 0x0029b160 | 3 |
| `_vt$8AIAction` | 0x002b7c90 | 0x0029b120 | 8 |

AIAction's slots: 8 the destructor, 16 DoSnapshot, 24
CalculatePointsToDrive, 32 GetName, 40 HasBeenAccomplished, 48 HasFailed
and 56 HasExpired. Retail has `__pure_virtual` at 24, 40, 48 and 56. The
port's tables have NULL there and at the DoSnapshots. GetName answers ""
(0x00331170), and every action overrides it.

## The checker

`tools/nearbycar_check.py` runs retail's image in mipsemu as the model,
over the port's harness (`tools/src/nearbycar_test.c`). For 11c it adds:
- `aiaction.c` to the harness's sources;
- four AIActions of the script's;
- 22 ops (lowercase letters);
- six kinds of scenario: s_plans, s_update, s_life, s_speed, s_heading
  and s_collide, with s_ai_edges after them.

Stubbed on both sides, each printing its arguments:
- the slot pool's bNewSlotPool, bDeleteSlotPool, bOMalloc and bFree;
- DestoryTargetMarkers;
- `__builtin_delete` (the port's bFree, through bmem's free hook);
- the three tests UpdateStatus asks. They answer the script's values
  from a test table at 0x01210000, whose deltas (0, 8 and -4) show that
  `this` is adjusted;
- each car's driver's GetSteerToPoint, answering the script's point.

The model divides as the EE does. The one divide by zero the script takes
is 0x001c6520, and the model stops if any other site takes the EE's
path.

Its numbers:
- 58 scenarios, 9,667 ops and 16,061 lines, with 0 differ;
- 220 mutations, all caught. 11c's share is 121.

The first mutation pass left nine alive, all gaps in the script:
- sl-gap-assoc: the gap's two subtractions against one. s_speed's
  scratch cars ran with MyHalfSizeD 0, and its list's cars mostly fell to
  the 0.1 s floor. s_ai_edges adds forty gaps with MyHalfSizeD set and
  times above the floor.
- Six of the moving car's edges, each needing an exact value. s_ai_edges
  puts a car on the straight route at (20, 0), where the lateral
  distance is exactly -y:
  - hd-r-pos, hd-l-only, hd-r-out-le: r_now exactly 0, drifting right;
  - hd-l-pos: l_now exactly 0, 0.8 s to the right edge;
  - hd-l-out-le: l_now exactly 0, drifting off it;
  - hd-rate-min: drifting right at 0.0005 m/s, 0.6 s from the edge.
- hd-soon: the time to the edge exactly 1.0f. A search in GetHeading's
  float order found y = -6.999996 with vy = -1, and y = -6.000002 with
  vy = -2.
- hd-back-route: route directions are unit, so making them unit again
  changed nothing. s_ai_edges lays a route whose direction is (2, 0) and
  backs a car along it at 60 to 250 degrees.
