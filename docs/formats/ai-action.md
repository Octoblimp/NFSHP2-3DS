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
whether it is done. The actions themselves are 11d, with a section each
at the end: the five small ones (11d-1), Pass and AvoidCars (11d-2),
PullOver and IJustGotHit (11d-3a), and GetUnstuck and AvoidRoadBlock
(11d-3b). This is the base:
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

## The small actions (11d-1)

    0x001c73c0  AIActionJustDrive::AIActionJustDrive(int, float)
    0x001c7458  AIActionJustDrive::CalculateScore(DrivingInformation *)
    0x001c7460  AIActionJustDrive::HasBeenAccomplished, HasExpired
                (0x001c7468), HasFailed (0x001c74b0)
    0x001c74b8  AIActionJustDrive::CalculatePointsToDrive
    0x001c7690  AIActionDraft::AIActionDraft(int, float)
    0x001c7720  AIActionDraft::CalculateScore(DrivingInformation *, Car *)
    0x001c7750  AIActionDraft::HasBeenAccomplished, HasExpired
                (0x001c7758), HasFailed (0x001c77a0)
    0x001c77a8  AIActionDraft::CalculatePointsToDrive
    0x001c8028  AIActionNudgeCar::AIActionNudgeCar(int, float, Car *)
    0x001c80d8  AIActionNudgeCar::CalculateScore(DrivingInformation *,
                    Car **), then the tests and CalculatePointsToDrive
                    to 0x001c815c
    0x001c8160  AIActionBlock::AIActionBlock(int, float, Car *)
    0x001c8210  AIActionBlock::CalculateScore(DrivingInformation *,
                    Car **), then the tests and CalculatePointsToDrive
                    to 0x001c8294
    0x001ca1f0  AIActionAccidentRecovery::AIActionAccidentRecovery(int,
                    float)
    0x001ca2a8  AIActionAccidentRecovery::CalculateScore(
                    DrivingInformation *)
    0x001ca2f0  AIActionAccidentRecovery::SortOfParallelToTrack(Car *,
                    float)
    0x001ca398  AIActionAccidentRecovery::HasBeenAccomplished, HasExpired
                (0x001ca3e8), HasFailed (0x001ca430)
    0x001ca438  AIActionAccidentRecovery::CalculatePointsToDrive
    0x001ca5b8  AIActionAccidentRecovery::GetName, then the destructors:
                AccidentRecovery 0x001ca5c8, JustDrive 0x001ca7f8 (its
                GetName 0x001ca7e8), Block 0x001ca858, NudgeCar
                0x001ca8b8, Draft 0x001ca918

The first five of the eleven actions, in `3DS Files/source/aiactions.{c,h}`.
AIDriver's ChooseNewAction (11f) scores the actions with their static
CalculateScores, news the best one from the pool and makes it the
controller's CurrentAction. The DoSnapshots wait on ReplaySnapshot.

`AIDriverAvoidCarsImpactTimeThreshold` (gp-18168, 2.0f, AIDriver.obj's
`.sdata`) is defined here, since JustDrive is the first to read it. It is
the longest time to a hit that still lets a choice count as driveable.
Nothing writes it.

### The records

Each subclass's fields sit sixteen bytes later than the demo's stabs put
them, after retail's 608-byte base:

| Action | Type | 608 | 612 | GetName |
|---|---:|---|---|---|
| JustDrive | 5 | LastDecisionReevaluationTime, a Timer | | "Just Drive" |
| Draft | 2 | | | AIAction's, "" |
| NudgeCar | 4 | CarToNudge | | AIAction's |
| Block | 3 | CarToBlock | | AIAction's |
| AccidentRecovery | 10 | MyCreationTime, a Timer | HaveResetYet, a bool word | "Accident recovery" |

Each constructor runs AIAction's, then sets Type, its vptr and its
fields. JustDrive's time starts at 0. AccidentRecovery's starts at 0 from
the Timer's own constructor and is then set to WorldTimer: the action
remembers when it was made. NudgeCar and Block keep the car they are
handed. Nothing in these five reads it.

Each destructor writes its vptr, runs AIAction's destructor with 0, and
frees the slot when bit 0 of its flags is set.

### The scores

| Action | CalculateScore |
|---|---|
| JustDrive | 0 |
| Draft | 200 when NearbyCarList::GetCarAhead finds a car ahead of the car it is handed, else -1 |
| NudgeCar | 300, and the car out-argument NULL |
| Block | 400, and the car out-argument NULL |
| AccidentRecovery | 500 for a car with fewer than two wheels down (`slti`, signed) that is not sort of parallel to the track at 0.707, else -1 |

### The tests

None of the five ever fails.

JustDrive, Draft and AccidentRecovery expire alike:

    DeltaTime < (WorldTimer - ExpiryTimer) * 0.00025  &&  CanExpire

The tick difference is a signed word, converted. The `c.lt.s` makes a
NaN timeout never expire.

NudgeCar and Block test the other way round, with `c.le.s`:

    if (seconds <= DeltaTime) not expired
    else if (PointsToDriveWillExecuteAction) not expired
    else CanExpire

So a NaN timeout goes on to the other two tests, and an action that has
been asked for its points never expires. Both are always accomplished,
so UpdateStatus gives SUCCESS on the first frame.

AccidentRecovery is accomplished once it has reset the car. Before that,
it is accomplished when all four wheels are down (`nWheelsTouchingGround`
exactly 4) and the car is sort of parallel to the track at 0.707. JustDrive
and Draft are never accomplished.

### SortOfParallelToTrack

A static method. It asks GetElevation at the car's position for the
ground's normal. The terrain type is asked for and not read. Then it
makes the body's z axis (BodyMatrix.v2, the car's up) unit in VU0:

    q = 1 / sqrt((x*x + y*y) + z*z)          vrsqrt
    up = (x, y, z, w) * q                    all four lanes
    threshold < (up.x*n.x + up.y*n.y) + up.z*n.z

The comparison is `c.lt.s`, so a NaN is not parallel. The port writes
the normalise as plain floats. VU0's `vrsqrt` is not IEEE, and a zero up
axis would divide by zero. The checker's up axes are never zero, and
their lengths are near 1.

### JustDrive's points

    if 3 <= (WorldTimer - LastDecisionReevaluationTime) * 0.00025:
        LastDecisionReevaluationTime = WorldTimer
        if the choice is not DRIVING_LINE_0:
            try DRIVING_LINE_0 with IsDriveable (not preferred, towards
                the line, AIDriverAvoidCarsImpactTimeThreshold) into a
                target of its own
            when driveable: the choice becomes it, the location's line
                becomes line 0's, and the target is copied to
                PointsToDrive
    if that did not happen:
        a choice that is not a line becomes DRIVING_LINE_0, and the
            location's line line 0's
        BuildDriveTarget for the choice, towards the line
    DesiredSpeedTolerance 0
    PointsToDriveWillExecuteAction, UseDrivingLineSpeed,
        AllowedToUseThrottleAndBrake and AllowedToUseBoost 1

Line 0's line is GetDrivingLine's for DRIVING_LINE_0, the car's class
times two, set with a relaxed switch.

The time is stored in the delay slot of the choice's test, so it is
stored whenever three seconds have gone, even for a car already on line
0. A car always waits three seconds between tries.

IsDriveable takes three floats. Retail passes 0 in f12 and the threshold
in f13, and leaves f14 as its caller had it. Every BuildDriveTarget in
the five actions gets 0 in f12 and a stale f13. None of the stale ones
is read (see ai-driving-choice.md), and the port passes 0.

### Draft's points

    a choice that is not a line becomes DRIVING_LINE_0, as JustDrive's
    BuildDriveTarget for the choice, towards the line
    DesiredSpeedTolerance 0; AllowedToUseBoost, UseDrivingLineSpeed and
        AllowedToUseThrottleAndBrake 1
    nc = GetCarAhead(list, MyCar)
    if nc and |nc.Position.x| < MyHalfSizeL + nc.ApparentHalfSizeL
          and nc.Position.y < 6:
        speed = nc's VelocityMagnitude - (20 - nc.Position.y)
        if speed < DesiredSpeed:
            DesiredSpeed = speed; TimeToGetToDesiredSpeed 0;
            UseDrivingLineSpeed 0
    PointsToDriveWillExecuteAction 1

The speed is only ever lowered, and DesiredSpeed is the action's own: 0
from the constructor, then whatever an earlier call left. So a new Draft
slows only behind a car going slower than 20 m/s less the gap, and then
asks for a speed below 0. Behind a faster car it keeps its 0 and uses
the driving line's speed.

### NudgeCar's and Block's points

PointsToDriveWillExecuteAction 1, and nothing else. Their target stays
empty, as the constructor made it.

### AccidentRecovery's points

    a choice that is not a line is set from the location (SetChoice with
        a DrivingLocation, 0x001cacc8)
    BuildDriveTarget for the choice, parallel to the line
    TimeToGetToDesiredSpeed, DesiredSpeed and DesiredSpeedTolerance 0
    UseDrivingLineSpeed 0, PointsToDriveWillExecuteAction 1,
        AllowedToUseThrottleAndBrake 0
    if 5 <= (WorldTimer - MyCreationTime) * 0.00025 and not HaveResetYet:
        PleaseResetMeLater(MyCar); HaveResetYet 1

BuildDriveTarget's answer is not read. The reset is asked once. The next
UpdateStatus finds the action accomplished.

### The constants

| Where | Value | Port | Use |
|------:|------:|------|-----|
| gp-28708, gp-28704, gp-28696, gp-28676, gp-28672, gp-28536, gp-28532 | 0.00025 | AIA_TICKS_TO_SECONDS | ticks to seconds, one per function |
| gp-28700 | 99999 | AIJD_NO_HIT | IsDriveable's hit time, first |
| gp-28544, gp-28540 | 0.707 | AIAR_UPRIGHT | sort of parallel |
| gp-18168 | 2 | AIDriverAvoidCarsImpactTimeThreshold | |
| lui 0x4040 | 3 | AIJD_REEVALUATE_EVERY | |
| lui 0x40c0 | 6 | AIDR_CLOSE | |
| lui 0x41a0 | 20 | AIDR_GAP | |
| lui 0x40a0 | 5 | AIAR_RESET_AFTER | |

### The tables

Eight entries each, in AIAction's slots (8 the destructor, 16
DoSnapshot, 24 CalculatePointsToDrive, 32 GetName, 40
HasBeenAccomplished, 48 HasFailed, 56 HasExpired):

| | Retail | Port's constant (the demo's) |
|---|---|---|
| `_vt$17AIActionJustDrive` | 0x002b7b10 | 0x0029afa0 |
| `_vt$13AIActionDraft` | 0x002b7bd0 | 0x0029b060 |
| `_vt$16AIActionNudgeCar` | 0x002b7b90 | 0x0029b020 |
| `_vt$13AIActionBlock` | 0x002b7b50 | 0x0029afe0 |
| `_vt$24AIActionAccidentRecovery` | 0x002b79d0 | 0x0029ae60 |

Draft, NudgeCar and Block have AIAction's GetName (0x001caae0). The
port's DoSnapshots are NULL. `aiactions_install_vtables` installs the
five, from `main.c`.

### The checker

`tools/drivingchoice_check.py` runs these, not `nearbycar_check`: the
actions build drive targets, and drivingchoice_check has the routes, the
walk and the choices already. For 11d-1 it adds:
- `aiaction.c` and `aiactions.c` to the harness's sources;
- an action slot (AB) and a DrivingInformation (INFO). `@J` copies the
  script's list, location and choice into INFO;
- the `@` ops. They construct an action into the slot, call its
  CalculatePointsToDrive, UpdateStatus, tests, GetName and destructor
  through retail's vptrs, run the static scores and
  SortOfParallelToTrack, set a car's up axis, the normal under it and its
  wheels down, and poke the action's fields;
- s_actions, five actions in a row on s_choose's world. The script ties
  its clock steps to the action's own times (the timeout, JustDrive's
  last try, AccidentRecovery's creation). It puts the car ahead at
  Draft's edges, and tilts the car about the 0.707 line.

Stubbed on both sides, each printing its arguments:
- the slot pool's bNewSlotPool, bDeleteSlotPool, bOMalloc and bFree;
- DestoryTargetMarkers;
- GetElevation, which answers the script's normal under the car;
- PleaseResetMeLater.

s_act_edges, one scenario at the end, runs the exact cases that random
actions miss:
- NudgeCar's and Block's HasExpired, each asked before any points, at a
  timeout that cannot expire (-1), at exactly the timeout and just either
  side of it. The timeout is 4000 ticks for 1 s, from a clock SetTimeout
  keeps exact. It also runs a NaN poked over a timeout that can expire.
  PointsToDriveWillExecuteAction is poked to 0 first, or the slot's fill
  would answer the points test before HasExpired was ever asked.
- AccidentRecovery's score and accomplishment, with the ground's normal at
  0.45, 0.5 and the float above it, 0.51, 0.6, 0.69, 0.75 and the float
  above 0.707, under each wheel count.

The first mutation pass left seven alive. Four were gaps in the script,
which s_act_edges now closes: the slot's fill, the -1 timeout, the exact
4000 ticks and the normals between 0.5 and 0.707. The other three are
equivalent:
- jd-every: no tick count gives exactly 3.0f. 11999 ticks give 2.99975f
  and 12000 give 3.0000002f, so `<` and `<=` never differ.
- jd-pref: the preferred scale only reaches the score, which JustDrive
  doesn't read. For DRIVING_LINE_0, the left-out car is NULL either way.
- jd-a: IsDriveable hands the float to BuildDriveTarget, which doesn't
  read it.

Its numbers:
- 352 scenarios, 142016 ops, 178348 lines, 0 differ.
- 136 mutations for 11d-1: 133 caught (1 by a crash) and 3 equivalent.
  Across the whole checker, 877 mutations: 863 caught, 14 equivalent and
  0 unexplained.

## Pass and AvoidCars (11d-2)

    0x001c6ba0  AIActionAvoidCars::AIActionAvoidCars(int, float, Car *,
                    float, bool, bool)
    0x001c6cf8  AIActionAvoidCars::CalculateScore(DrivingInformation *,
                    Car **, DrivingChoice *, float *, bool *, bool *)
    0x001c6e78  AIActionAvoidCars::HasBeenAccomplished, HasExpired
                (0x001c6ee8), HasFailed (0x001c6ef0)
    0x001c6ef8  AIActionAvoidCars::CalculatePointsToDrive
    0x001c78f8  AIActionPass::AIActionPass(int, float, Car *, float)
    0x001c79d8  AIActionPass::CalculateScore(DrivingInformation *, Car **,
                    DrivingChoice *, float *)
    0x001c7b90  AIActionPass::HasBeenAccomplished, HasExpired (0x001c7d00),
                HasFailed (0x001c7d48)
    0x001c7e28  AIActionPass::SideOfCarIsOkay(NearbyCar *, DrivingChoice *,
                    bool)
    0x001c7ea8  AIActionPass::CalculatePointsToDrive
    0x001ca978  AIActionPass::GetName, then its destructor 0x001ca988,
                AvoidCars' GetCarToAvoid 0x001ca9e8, GetName 0x001ca9f0
                and destructor 0x001caa00

The two big ones that build on DrivingChoice's choosing (11b-4b). Pass
goes round a car ahead it can catch; AvoidCars steers off a hit my own
target is heading for.

### The records

| Action | Type | 608 | 612 | 616 | 620 | 624 | 628 | 632 | GetName |
|---|---:|---|---|---|---|---|---|---|---|
| Pass | 0 | CarToPass | AmountToProjectIntoFuture | MyCreationTime | | | | | "Pass" |
| AvoidCars | 1 | CarToAvoid | SecondsToImpact | IsMyDrivingChoiceOkay | LastDecisionReevaluationTime | MyCreationTime | MinLifetime | UsedPreferredSide | "Avoid Cars" |

The bools are words: the constructors store them with `sw`, and the
scores write their bool outs with `sw` too. Both constructors set their
times to WorldTimer. AvoidCars' MinLifetime is the seconds it was made
with plus 2. Nothing reads AmountToProjectIntoFuture or SecondsToImpact.

The offsets after the car pointer are retail's only where a pointer is 4
bytes, so their layout check sits under `UINTPTR_MAX == 0xFFFFFFFF`. The
host checker pokes those fields by name.

### Pass

CalculateScore:

    -1 in the grace period
    for each car before mine in the list, while none is found:
        skip it unless 0 < y, x < y + y (x signed) and CanICatchThisCar
        the choice out = the information's choice
        TryToDriveAroundCar from it into a target of its own, over
            AIActionPassMaxTimeAheadToMakeAttempt, considering both sides
        found when that works and SideOfCarIsOkay: the car out = this car
    300 when found, else -1

CalculateMaxAcceleration is asked for my car at its speed, and only
CanICatchThisCar is handed the answer, which it doesn't read. The fourth
out-argument isn't written. The cars before mine are the ones ahead, as
Think orders the list. With my car not in it, GetCarsIndexInArray gives
-1 and no car is tried.

SideOfCarIsOkay:

    yes for a car under TRAFFIC_CONTROL
    yes when the car isn't faster than
        TryToDriveAroundCarMinSpeedForDrivingLine (c.lt.s)
    yes when the choice is a driving line
    else the side TryToDriveAroundCar picked was the preferred one

HasBeenAccomplished:

    if the list has a car and its first car is not CarToPass:
        score again into a cleared choice
        when it scores and the choice is not the information's: take the
            choice, the car, and restart MyCreationTime
    done once 3 s have gone since MyCreationTime and CarToPass is off the
        list or more than (MyHalfSizeD + its ApparentHalfSizeD) + 10
        behind
    a relaxed switch when done

HasFailed: CarToPass is off the list, or within the first 3 s and ahead
(y > 0) and CanICatchThisCar (with -1, so it asks the acceleration again
and drops it) says no. A relaxed switch when failed. HasExpired is the
timeout's, as JustDrive's.

CalculatePointsToDrive:

    clear PointsToDrive; UseDrivingLineSpeed 0; throttle, boost and
        PointsToDriveWillExecuteAction 1
    with CarToPass on the list:
        ahead (y > 0): TryToDriveAroundCar into PointsToDrive, over the
            avoid threshold, both sides
        else: a choice that is not a line is set from the location, then
            IsDriveable, not preferred, parallel to the line
        UseDrivingLineSpeed 1
    else:
        a choice that is not a line is set from the location;
        BuildDriveTarget, parallel to the line
        UseDrivingLineSpeed 1, PointsToDriveWillExecuteAction 0

None of the answers is read.

### AvoidCars

CalculateScore:

    secs = 99999, okay and the side used 0
    WhoWillThisDriveTargetHit for my car's own target, over the avoid
        threshold
    if it hits a car sooner than the threshold:
        the car and secs out; the choice out = the information's choice
        in the grace period against a car with no player: okay 1, side 0
        else okay = MakeNewChoice from that choice, both sides
        400
    else -1

HasBeenAccomplished: once `seconds <= MinLifetime` fails (`c.le.s`, so a
NaN MinLifetime is done at once), with a relaxed switch. It never fails
or expires.

CalculatePointsToDrive:

    PointsToDrive = my car's own target; tolerance 0; throttle and line
        speed 1
    ncAvoid, ncChoice = CarToAvoid's and the choice's car's entries
    DoWeCareAboutThisCar for each, answers dropped
    slow = ncAvoid and my speed < 10 and its car's < 5
    reevaluate = not in the grace period, or CarToAvoid has a player;
        and only more than 0.3 s after the last re-evaluation
    if reevaluate:
        a line choice, when slow, becomes the left side of the car to
            avoid, or its right side when there is not enough room
        UsedPreferredSide 0; okay = MakeNewChoice into PointsToDrive
        a line choice whose line is not the location's sets the
            location's line (no relaxed switch) and highlights it for my
            driver number; ncChoice NULL
        a side choice: ncChoice its car's entry
        LastDecisionReevaluationTime = WorldTimer
    unless it re-evaluated into points with a choice:
        a choice that is none or not valid: okay 0, set from the location
        okay = IsDriveable, preferred when UsedPreferredSide, towards the
            line
        no points: BuildDriveTarget parallel to the line, okay 0
    if not okay and we care about ncAvoid or ncChoice, and ncAvoid's car
            is on the list and not blinking:
        close = for a car under REAL_CONTROL, MyHalfSizeD * 0.5 <
                y + vy * 0.1; for any other, 0 < y
        not close when |x| is not under (MyHalfSizeL + ApparentHalfSizeL)
            + 1 and the car has no player
        if close: UseDrivingLineSpeed 0, or 1 when slow, else
            SetDesiredSpeedSlowerThanThisCar (0.1, 0.1); behind a traffic
            car or a cop, DesiredSpeed at least 20
    PointsToDriveWillExecuteAction 1

Retail hands MakeNewChoice UsedPreferredSide's own address. The port
hands it an int and copies the answer into the field after: the
field's int32_t is a long on the 3DS, and MakeNewChoice's out is an
int. MakeNewChoice stores the out on each of its ways out, so the two
agree.

In the grace period CarToAvoid is read through with no NULL test, so it
must be a car. HighlightDrivingLine (0x001cb450) asks my car's driver for
its number through the CarDriver's vptr (entry 80).

### The constants

| Where | Value | Port | Use |
|------:|------:|------|-----|
| gp-18164 | 3 | AIActionPassMaxTimeAheadToMakeAttempt | Pass's look ahead |
| lui 0x4040 | 3 | AIPA_SETTLE | Pass's first seconds |
| lui 0x4120 | 10 | AIPA_BEHIND | behind by |
| gp-28680 | 99999 | AIPA_NO_HIT | IsDriveable's hit time, first |
| gp-28736, gp-28720 | 99999 | AIAC_NO_HIT | no hit |
| lui 0x4000 | 2 | AIAC_MIN_LIFETIME | |
| gp-28724 | 0.3 | AIAC_REEVALUATE_EVERY | |
| lui 0x4120, lui 0x40a0 | 10, 5 | AIAC_SLOW_ME, AIAC_SLOW_IT | slow |
| gp-28716 | 0.1 | AIAC_LOOK_AHEAD | |
| lui 0x3f00 | 0.5 | AIAC_HALF | |
| lui 0x3f80 | 1 | AIAC_ACROSS_MARGIN | |
| gp-28712 | 0.1 | AIAC_SLOWER_BY | both of SetDesiredSpeedSlowerThanThisCar's |
| lui 0x41a0 | 20 | AIAC_MIN_SPEED_BEHIND | |

### The tables

| | Retail | Port's constant (the demo's) |
|---|---|---|
| `_vt$12AIActionPass` | 0x002b7c10 | 0x0029b0a0 |
| `_vt$17AIActionAvoidCars` | 0x002b7c50 | 0x0029b0e0 |

`aiactions_install_vtables` installs the seven.

### The checker

drivingchoice_check adds:
- `@n pa score timeout car amount` and `@n ac score timeout car secs okay
  used`;
- `@sc pa` and `@sc ac`, with every out filled first, so what isn't
  written shows;
- `@so entry preferred` (SideOfCarIsOkay on the list's entry and the
  information's choice), `@ga` (GetCarToAvoid) and `@bk car timer
  duration` (a car's blink);
- after AvoidCars' points, the two highlight globals; and the globals
  PASS, CAM, HROUTE and HLINE.

Two more stubs, on both sides:
- CalculateMaxAcceleration (0x001cce50), in the model only. Its answer
  reaches only CanICatchThisCar, which doesn't read it. The harness runs
  the port's, so it gives each car a ride info and car type 0 a two-entry
  acceleration table.
- GetDriverNumber, in a test CarDriver table (DVT) every car's driver
  points at. It prints the car and answers its DriverNumber.

s_pass_avoid makes Pass or AvoidCars four times on s_actions' world. It
times its clock steps from the action's own times either side of each
edge: 0.3 s, AvoidCars' least lifetimes for its seconds (2, 2.25, 2.5, 3)
and Pass's 3 s. It also steps either side of the grace period's end, for
the default driver and for driver 120. It covers:
- speeds either side of 5, 10 and the line's speed;
- blinks either side of their end;
- the camera on my car or not;
- the look-ahead times moved, including an avoid threshold of 0 (a hit at
  once is then not sooner) and 99999.

s_pa_edge, eight rounds of ten kinds at the end, runs the exact cases
that random worlds miss. Each builds its own few cars, with every car it
doesn't need well behind:
- pa-score: the car ahead at x exactly 2y, a float either side, and at
  -2y, 1.5y and 0.5y, closing or pulling away, with the least speed at 0
  or 5 sometimes.
- pa-hba: the car to pass exactly 10 m past the two half lengths, a float
  either side, and just short, with the clock 3 s on, a tick past and well
  past.
- pa-hf: both cars level at y 0 and still, with nothing accelerating, so
  CanICatchThisCar is 0 < 0, at the clock either side of 3 s.
- pa-cp: my car off its line, real or AI, with each kind of choice set
  raw, so the line the points start from is not the choice's.
- ac-time: AvoidCars' threshold (5 or 4) away from Pass's (0, 0.25 or
  0.5), with my car closing on car 1 down one lane, so the hit comes one
  or two seconds on; the points are asked again 0.3 s and 0.6 s later.
- ac-null: a threshold so far ahead that every car is a hit, sometimes
  with no location.
- ac-close: a car stopped just ahead (car 4), so nothing is driveable,
  with the car to avoid at each edge of the close test: half lengths,
  look-ahead, x, real or not, across, blinking and slow.
- ac-care: the stopped car, and a real car behind closing at 150, so only
  the choice's car is cared about.
- ac-stand: no location, with each line or none, and my own target empty
  or not, made again. For a negative odd line, MakeNewChoice's current
  choice keeps what retail's stack held, which drivingchoice.c clears; a
  stale line choice there skipped one of the lines. The model clears it
  on the way into MakeNewChoice (MAKE_NEW_CURRENT, sp+1696 of its
  1984-byte frame).
- ac-side: a still car a few points ahead and 3 to 6 m to the side, at a
  speed either side of 5, so a line choice becomes a side of it.

The first mutation pass left 45 alive; s_pa_edge catches 35 of them. The
other ten are equivalent:
- pa-nohit: IsDriveable stores DC_NO_HIT in the time before anything reads
  it, and Pass drops the time after.
- pa-cp-clear: every way on rebuilds the points with BuildDriveTarget,
  which first copies the driver's own target over all of them.
- pa-cp-drv-time: the time reaches BuildDriveTarget, which doesn't read
  it, and WhoWillThisDriveTargetHit, where it only stops the walk; Pass
  drops IsDriveable's answer, and the IDs move once a car either way.
- ac-sc-used1: the side used was stored 0 at the top, and nothing between
  writes it.
- ac-cp-used0: MakeNewChoice stores its out on each of its four ways out.
- ac-cp-none: IsValid answers 0 for CHOICE_NONE, so the type test says
  only what the IsValid test says.
- ac-cp-zero: the points are empty after IsDriveable only with no
  location, where IsDriveable's own build made the same empty target.
- ac-cp-build-move: that build runs only with no location, where
  FillUpDriveTarget returns before it reads the movement.
- ac-cp-build-okay: that store runs only with no location, where the
  answer was 0 already.
- ac-cp-slower-b: SetDesiredSpeedSlowerThanThisCar doesn't read its second
  float.

Its numbers:
- 532 scenarios, 194029 ops, 218234 lines, 0 differ.
- 170 mutations for 11d-2: 160 caught and 10 equivalent. Across the whole
  checker, 1047 mutations: 1023 caught, 24 equivalent and 0
  unexplained.

## PullOver and IJustGotHit (11d-3a)

    0x001c8298  AIActionPullOver::AIActionPullOver(int, float, float,
                    NearbyCarList *, DrivingLocation *)
    0x001c8400  AIActionPullOver::CalculateScore(DrivingInformation *)
    0x001c8610  AIActionPullOver::HasBeenAccomplished, HasExpired
                (0x001c8650), HasFailed (0x001c8658)
    0x001c8660  the room to the right edge (a method that doesn't read
                `this`)
    0x001c86a8  AIActionPullOver::CalculatePointsToDrive
    0x001c9c68  AIActionIJustGotHit::AIActionIJustGotHit(int, float, Car *)
    0x001c9d20  AIActionIJustGotHit::CalculateScore(DrivingInformation *,
                    Car **)
    0x001c9e90  AIActionIJustGotHit::HasBeenAccomplished, HasExpired
                (0x001c9f10), HasFailed (0x001c9f58)
    0x001c9f60  AIActionIJustGotHit::CalculatePointsToDrive
    0x001ca628  AIActionIJustGotHit::GetName, then its destructor 0x001ca638
    0x001ca778  AIActionPullOver::GetName, then its destructor 0x001ca788

Traffic pulls over for a cop, and a car that has just been hit reacts to
it. These two are the first actions to read the world outside the list:
the chopper, the cop manager, the players and my car's collisions.

### The records

| Action | Type | 608 | 612 | 616 | 620 | 624 | GetName |
|---|---:|---|---|---|---|---|---|
| PullOver | 6 | MyCreationTime | LastDecisionReevaluationTime | IsMyDrivingChoiceOkay | New620 | PullOverTimeout | "Pull over" |
| IJustGotHit | 9 | CarIHit | LastDecisionReevaluationTime | | | | "I just got hit!" |

The two Timers' own constructors zero them first. PullOver's constructor
then sets MyCreationTime to WorldTimer, IsMyDrivingChoiceOkay to 1 and
clears PointsToDrive a second time. New620 (retail's name is lost) is
whether there was room to pull over: the room to the right edge at the
location's route point is over 2 m, or 1 without a list and a location.
IJustGotHit's constructor keeps the car and zeroes the time.

The room to the right edge is the route point's RightWidth less
MyHalfSizeL (my half width), less how far right of the point my car is,
across the point's direction, in retail's order.

### PullOver

CalculateScore:

    -1 unless my car is under TRAFFIC_CONTROL
    near when the chopper is out, its Plan 0, 1, 2 (by `sltiu`, so a
        negative one is none of them) or BOMBING_RUN, and it is within
        150 m on the ground
    near when an AI cop that is there and whose DesiredLogicState is not
        LS_DISABLED has its car's lights on in range
    near when a player's car has its lights on in range
    600 when near, else -1

A car's lights are in range when CopLights and the three bytes after it,
read as a word, are not 0, and the car is within its speed times 3.5 s on
the ground, and no less than 100 m. The range is worked out before the
lights are asked. Neither a cop's car nor a player's car is tested for
NULL; the cops themselves are.

HasBeenAccomplished: 0 unless my car is under TRAFFIC_CONTROL, else done
when CalculateScore says -1. HasFailed and HasExpired are 0.

CalculatePointsToDrive:

    PointsToDrive = my driver's own target; line speed 0, throttle 1,
        tolerance 0, boost 0
    careful = my driver's SkillLevel is -2
    if PullOverTimeout is within 0.001 of -999 (none), or less time has
            gone since MyCreationTime than PullOverTimeout:
        if more than 0.3 s since the last re-evaluation, or no points:
            LastDecisionReevaluationTime = WorldTimer
            a choice that is not a line is set from the location; okay 1
            careful: BuildDriveTarget from the information's choice,
                parallel to the line
            else: clear the points and FillUpDriveTarget towards the
                right side of the track
            WhoWillThisDriveTargetHit for the points, over the avoid
                threshold
            a hit sooner than 2 s: okay = MakeNewChoice from the left
                side of that car into a target of its own, over the avoid
                threshold, both sides; the points and the information's
                choice take it
        careful: speed + max deceleration * 0.12 when okay, * 0.2 when
            not
        else with the location clear or not okay: brake at 0.2
        else:
            over 15 m/s: New620 1, brake at 0.2
            else New620 goes 0 under 2 m of room and back to 1 over 4 m;
                brake at 0.2 when 0, 14 m/s when 1
            tolerance 2
        a desired speed under 0.5, or my car in any two-car collision:
            speed and tolerance 0
    else (past the timeout):
        a cleared choice set from the location; BuildDriveTarget from it,
            parallel to the line; speed and tolerance 0
    PointsToDriveWillExecuteAction 1; TimeToGetToDesiredSpeed 0.2

The braking speeds are SetDesiredSpeedToMaxDeceleration's, and the
careful ones use CalculateMaxDeceleration at my car's own speed. Past the
timeout, retail's choice is its stack until SetChoiceLocation, which
leaves it alone for a negative odd line; the port clears it first. The
side MakeNewChoice used is dropped.

### IJustGotHit

CalculateScore:

    car out = NULL
    for each of my car's collisions, two cars', whose other car has an
            entry on the list:
        take it when none is held or the held one's car is NULL; when the
            held one is behind (y < 0) and this one ahead (0 < y); or
            when its y is smaller
    400 and the car out when one was taken, else -1

The other car is the second one when the first is mine, else the first.
An entry with no car is found for NULL, so a collision whose other car is
NULL can be taken, and then any later one beats it.

HasBeenAccomplished:

    score again; when it scores, CarIHit = its car
    done when CarIHit is NULL or off the list, or when it didn't score

HasFailed is 0, and HasExpired is the timeout's, as JustDrive's.

CalculatePointsToDrive:

    nc = CarIHit's entry, asked first
    PointsToDrive = my driver's own target; throttle 1, tolerance 0, line
        speed 0
    more than 0.2 s since the last re-evaluation, or no points:
        LastDecisionReevaluationTime = WorldTimer; MakeNewChoice from the
            information's choice into the points, over the avoid
            threshold, both sides; the answers dropped
    heading out of the route forwards: brake at 0.2
    else no nc: line speed 1
    else CarIHit has a player and I am not traffic:
        ahead past (MyHalfSizeD + its ApparentHalfSizeD) - 2.8:
            SetDesiredSpeedSlowerThanThisCar (6)
        behind past (-MyHalfSizeD - its ApparentHalfSizeD) + 2.8:
            accelerate at 0.2
        else line speed 1
    else not ahead (0 < y fails): accelerate at 0.2
    else I am traffic and we face apart (the x and y of our two forward
            vectors dotted, under 0): TimeToGetToDesiredSpeed 0, my
            speed, and hands off the throttle and brake
    else SetDesiredSpeedSlowerThanThisCar (0.1)
    not on line speed: a desired speed of at least 20
    PointsToDriveWillExecuteAction 1

"Accelerate" is SetDesiredSpeedToMaxAcceleration, so CalculateMaxAcceleration's
answer is read here. The heading is GetHeadingClassification with no steer
check. Once nc is found, CarIHit is read through with no NULL test.

### The constants

| Where | Value | Port | Use |
|------:|------:|------|-----|
| lui 0x4316 | 150 | AIPO_CHOPPER_RANGE | |
| lui 0x4060 | 3.5 | AIPO_LIGHTS_SECONDS | |
| lui 0x42c8 | 100 | AIPO_LIGHTS_MIN | |
| gp-28668 | -999 | AIPO_NO_TIMEOUT | |
| gp-28664 | 0.001 | AIPO_TIMEOUT_EPSILON | |
| gp-28652 | 0.3 | AIPO_REEVALUATE_EVERY | |
| lui 0x4000 | 2 | AIPO_HIT_SOON | |
| gp-28648 | 0.12 | AIPO_GENTLE | careful and okay |
| gp-28644 | 0.2 | AIPO_FIRM | careful and not okay |
| gp-28640, gp-28636 | 0.2 | AIPO_BRAKE | |
| lui 0x4170 | 15 | AIPO_TOO_FAST | |
| lui 0x4000, lui 0x4080 | 2, 4 | AIPO_ROOM_LOW, AIPO_ROOM_HIGH | New620 |
| lui 0x4160 | 14 | AIPO_CREEP_SPEED | |
| lui 0x4000 | 2 | AIPO_TOLERANCE | |
| lui 0x3f00 | 0.5 | AIPO_STOPPED | |
| gp-28632 | 0.2 | AIPO_TIME_TO_SPEED | |
| | -2 | AIPO_CAREFUL_SKILL | |
| gp-28572 | 0.2 | AIIJ_REEVALUATE_EVERY | |
| gp-28568 | 0.2 | AIIJ_BRAKE | |
| gp-28564 | 2.8 | AIIJ_OVERLAP | |
| lui 0x40c0 | 6 | AIIJ_BACK_OFF | |
| gp-28560, gp-28548 | 0.2 | AIIJ_ACCEL | |
| gp-28556 | 0.1 | AIIJ_SLOWER_BY | |
| gp-28552 | 0.2 | AIIJ_SLOWER_UNUSED | not read |
| lui 0x41a0 | 20 | AIIJ_MIN_SPEED | |

### The tables

| | Retail | Port's constant (the demo's) |
|---|---|---|
| `_vt$16AIActionPullOver` | 0x002b7ad0 | 0x0029af60 |
| `_vt$19AIActionIJustGotHit` | 0x002b7a10 | 0x0029aea0 |

`aiactions_install_vtables` installs the nine. DoSnapshot (0x001c8370 and
0x001c9cb8) is left pending.

copmanager.h now has eLogicState, and tCop and tCopManagerHead as far as
the score reads them: a cop's nCopNumber (8), LogicState (12) and
DesiredLogicState (16), and the manager's nNumAICops (4) and nNumCops
(8).

### The checker

drivingchoice_check adds:
- `@n po score timeout -1 pot z`, with z's low bit leaving out the list
  and the next bit the location, and `@n ij score timeout car`;
- `@sc po` and `@sc ij` (its car out filled first);
- `@col k n (two a b)...`, a car's collisions; `@ch none|plan x y`, the
  chopper; `@cm none|n cop...`, the cop manager, each cop `-` or
  `car:state`; `@pl n a b`, the players; `@cl k word`, a car's cop
  lights; `@sk k skill`; and `@ti k` with a type info's mass, drag, speed
  limiter, the two tyres' friction and the two downforces;
- the globals COPM, PLAYERS and NPLAYERS.

Three more stubs, on both sides: CollisionBody::GetCollision (0x001d6f38),
Collision::IsTwoCarCollision (0x0021eb20) and Collision::GetCollidingCars
(0x0021eb48), answering from each car's collisions. 11d-2's stub of
CalculateMaxAcceleration is gone: IJustGotHit reads its answer, so it and
CalculateMaxDeceleration run as shipped, from each car's ride info and
type info. The model checks that nearbycar.c's fBeltAccelCoef is 1.

PullOver's choice past the timeout is retail's stack (sp+0 of a 720-byte
frame), so the model clears it on the way into CalculatePointsToDrive
(PO_CPTD, PO_CHOICE), as it does MakeNewChoice's.

s_pull_hit, 40 of each, drives PullOver or IJustGotHit as AIDriver would
on s_pass_avoid's world. Between the calls it changes my car's collisions
(two cars' or not, with cars on the list, off it, mine and none), its
skill and type info, the chopper, the AI cops, the players and each car's
lights, my car near the right edge and past it, and PullOver's location
clear. The clock lands either side of 0.2 s, 0.3 s and the timeouts of 1,
2 and 5 s, and PullOver's own timeout is none, 16 and 17 ulps either side
of -999, or seconds.

s_ph_edge, six rounds of eight kinds, runs the exact edges:
- po-chopper: the chopper in each plan at exactly 150 m along an axis
  and an ulp either side.
- po-lights: the cops' and the players' cars at exactly their range and
  an ulp either side, lights on or off, cops none or disabled.
- po-pot: the timeout 16 and 17 ulps from -999, and its seconds exactly
  up and either side.
- po-room: exactly 2 m and 4 m of room and an ulp either side, at 15 m/s
  and either side, and at the speeds where braking comes to exactly 0.5.
- po-hit: a car stopped just ahead, or slower in my lane a second or so
  on.
- ij-score: the collisions' cars at y either side of 0 and level, a car
  off the list, and an entry with no car.
- ij-cp: the car I hit at a player's two overlap edges, at y 0, head on
  or square, and at the speeds that come to exactly 20.
- ij-head: my car drifting out over the right edge, forwards and back.

The first mutation pass left 14 alive. s_ph_gap, two rounds of six
kinds on a straight road with every car square to it, catches ten:
- po-soon: PullOver careful with its hit exactly 2 s on and either side,
  and AvoidCars' time apart from Pass's (po-soon-k, po-cp-hit-lt,
  po-cp-who-time); then, inside the 0.3 s, the choice poked not okay, so
  the firm braking runs with and without downforce (po-cp-firm-speed).
- po-assoc: my car where the room to the edge, summed retail's way and
  the other, falls either side of 2 or 4 (po-room-assoc).
- po-mnc: car 1 hit 1.9375 s on and car 2 beside it, so going round car 1
  hits car 2 between Pass's time and AvoidCars' (po-cp-mnc-time).
- ij-null: the list's entry with no car taken first, then a car either
  side of it (ij-sc-best-null); and CarIHit NULL with that entry on the
  list (ij-acc-null).
- ij-back: a player's car exactly at the back overlap edge and an ulp
  either side (ij-cp-back-lt).
- ij-tts: traffic hit head on, with its time to the speed poked first
  (ij-cp-head-on-tts).

The other four are equivalent:
- po-ctor-clear: AIAction's constructor has just cleared PointsToDrive,
  and nothing touches it between, so the second Clear makes the same
  stores.
- po-cp-nto-le: `<=` and `<` part only where |pot + 999| is exactly
  0.00100000005f. Near -999 the sum is exact (Sterbenz), a multiple of
  2^-14, which that is not; any other pot is 499.5 or more away.
- po-cp-used: MakeNewChoice stores its out on each of its four ways out,
  and PullOver never reads it.
- ij-slower-unused-k: SetDesiredSpeedSlowerThanThisCar doesn't read its
  second float.

Five of the earlier slices' patterns (jd-copy, jd-assign, ar-tb,
ac-cp-assign and ac-cp-mnc-okay) stopped being unique and carry a line
of context.

Its numbers:
- 672 scenarios, 239714 ops, 264995 lines, 0 differ.
- 220 mutations for 11d-3a: 216 caught (11 by a crash) and 4 equivalent.
  Across the whole checker, 1267 mutations: 1239 caught, 28
  equivalent and 0 unexplained.

## GetUnstuck and AvoidRoadBlock (11d-3b)

    0x001c8b30  AIActionGetUnstuck::AIActionGetUnstuck(int, float, float)
    0x001c8c30  AIActionGetUnstuck::CalculateScore(DrivingInformation *)
    0x001c8ee8  AIActionGetUnstuck::AreWeStuckBehindSomeone(
                    DrivingLocation *, NearbyCarList *), static
    0x001c9018  the goal's route point (a method that doesn't read `this`)
    0x001c9070  the goal point, 2D, and 3D (0x001c90d8)
    0x001c9140  AIActionGetUnstuck::HasBeenAccomplished, HasExpired
                (0x001c9298), HasFailed (0x001c9340)
    0x001c9550  AIActionGetUnstuck::CalculatePointsToDrive
    0x001c9668  AIActionAvoidRoadBlock::AIActionAvoidRoadBlock(int, float,
                    const tRoadBlock *)
    0x001c9718  AIActionAvoidRoadBlock::CalculateScore(DrivingInformation *,
                    const tRoadBlock **)
    0x001c9858  AIActionAvoidRoadBlock::HasBeenAccomplished, HasExpired
                (0x001c98d0), HasFailed (0x001c98d8)
    0x001c98e0  AIActionAvoidRoadBlock::CalculatePointsToDrive
    0x001ca698  AIActionGetUnstuck::GetName, then its destructor 0x001ca6a8
    0x001ca708  AIActionAvoidRoadBlock::GetName, then its destructor
                0x001ca718

The last two actions. A car that is stuck backs out towards a point
further up its route, and a car with a roadblock ahead heads for the
roadblock's escape lane. With these, every one of AIActionType 0 to 10
is ported.

### The records

| Action | Type | 608 | 612 | 616 | GetName |
|---|---:|---|---|---|---|
| GetUnstuck | 7 | MyCreationTime | MinimumLifetime | MinimumLifetimeInEffect | "Get Unstuck" |
| AvoidRoadBlock | 8 | RoadBlockToAvoid | | | "Avoid Roadblock" |

GetUnstuck's Timer is zeroed by its own constructor, then set to
WorldTimer. The minimum lifetime is in effect unless it is within 0.001
of -1 (none). AvoidRoadBlock keeps its roadblock.

The minimum lifetime holds when it is in effect and less time has gone
since MyCreationTime than it (`c.le.s`, so a NaN lifetime never runs
out). The goal is the route point three on from the location's, in the
same table. Retail tests that pointer for NULL, which it never is, and
past the route's end it reads on into the table; the goal point is on
the location's line there.

A point's "across" is how far right of a route point's line it is,
across the point's direction; its "past the edge" is across less the
RightWidth on the right, and -(across + LeftWidth) on the left, so
negative on the road.

### GetUnstuck

CalculateScore:

    -1 in my car's grace period, for a clear location, or with fewer
        than 3 wheels on the ground
    stuck when my car is 20 m or more past the edge at the location's
        route point
    or when, as an AI car at no more than 25 m/s or a traffic car at no
        more than 20, I am heading out of the route forwards (with the
        steer check)
    or when AreWeStuckBehindSomeone
    or when one of my collisions is in front, at least 0.4 s ago, and my
        speed is under 1 or within 0.001 of it
    stuck: my controller's FindWhereIAm, and 500; else -1

AreWeStuckBehindSomeone:

    0 when my car is blinking, or its speed is over |-15| (the absolute
        value of the constant, not of my speed)
    1 when any other car on the list has |speed| no more than
        AISlowCarSpeed, |x| under MyHalfSizeL + its ApparentHalfSizeL,
        and 0 < y < (MyHalfSizeD + its ApparentHalfSizeD) + 9

An entry with no car is read through.

HasBeenAccomplished:

    0 while the minimum lifetime holds
    to = the goal point less my position, normalised (bNormalize2)
    fwd = my body's x and y (BodyMatrix.v0), normalised
    done when fwd . to is at least 0.98 and not AreWeStuckBehindSomeone
    done: FindWhereIAm and my driver's ClearSteeringMemory

HasFailed:

    failed for a clear location or fewer than 3 wheels down
    else 0 while the minimum lifetime holds
    else failed when heading out of the route backwards (steer check)
    else failed when one of my collisions is behind, at least 0.4 s ago,
        and |speed| is under 1 or my speed within 0.001 of 1
    failed: FindWhereIAm and ClearSteeringMemory

HasExpired is the timeout's, with FindWhereIAm and ClearSteeringMemory
when it is past.

CalculatePointsToDrive:

    a choice that is not a line is set from the location
    clear the points; tolerance 0, line speed 0, boost 0, executes 1,
        throttle and brake 1
    a clear location: executes 0, and done
    add the goal point (3D) on the location's line, no check
    FillUpDriveTarget parallel to the line, inside 1
    DesiredSpeed -15 as an AI car, else -6

FindWhereIAm is the CarController's (vptr +72) and ClearSteeringMemory
the CarDriver's (vptr +128, `CARDRIVER_VT_CLEAR_STEERING_MEMORY`).

### AvoidRoadBlock

CalculateScore:

    roadblock out = NULL; -1 with no cop manager
    range = max(my speed * 2.5, 100)
    the first active roadblock with either cop there whose distance
        round the track, CompareDistances(mine, its), is under -range
    600 and the roadblock out when one is found, else -1

For the one found, retail asks GetActiveRoadBlock for it again and puts
its spike belt in my car's frame (WorldToCar); nothing reads that.

HasBeenAccomplished: 1 when neither of the roadblock's cops is there,
else done when CompareDistances(mine, its) is over 15, the roadblock 15 m
behind. HasFailed and HasExpired are 0.

CalculatePointsToDrive:

    a choice that is not a line is set from the location
    clear the points; tolerance 0, throttle and brake 1, line speed 0
    fromL = my across at the location's route point, less the line's
        offset there
    on the roadblock's route: end = its route point, toL = the escape
        lane's across there less the line's offset
    else end = FindClosestPointAhead(my route, the escape lane, from my
            route point); when it is found and the escape lane is under
            5 m past the edge there, toL as above at end
        else end = my route's last point and toL = fromL
    the route points up to end (a FuturePointList on the stack)
    DoSmoothOffsetChange over them, from fromL to toL by the last,
        inside 0
    FillUpDriveTarget parallel to the line, inside 0; line speed 1
    WhoWillThisDriveTargetHit within 1 s: a car that is not a cop (its
        type info's UsageType) and not traffic, with an entry on the list
        ahead (0 < y): line speed 0, SetDesiredSpeedSlowerThanThisCar
        (0.1), and a desired speed of at least 30
    executes 1

### The constants

| Where | Value | Port | Use |
|------:|------:|------|-----|
| lui 0xbf80 | -1 | AIGU_NO_LIFETIME | |
| gp-28628 | 0.001 | AIGU_LIFETIME_EPSILON | |
| lui 0x41a0 | 20 | AIGU_OFF_ROAD | past the edge |
| lui 0x41c8 | 25 | AIGU_SLOW_AI | |
| lui 0x41a0 | 20 | AIGU_SLOW_TRAFFIC | |
| gp-28620, gp-28592 | 0.4 | AIGU_HIT_AGO | score, failed |
| lui 0x3f80 | 1 | AIGU_STOPPED | |
| gp-28616, gp-28588 | 0.001 | AIGU_STOPPED_EPSILON | |
| lui 0x4110 | 9 | AIGU_BEHIND_GAP | |
| gp-28608 | 0.98 | AIGU_FACING | |
| lui 0xc170 | -15 | AIGU_REVERSE_AI | the speed, and AreWeStuckBehindSomeone's |
| lui 0xc0c0 | -6 | AIGU_REVERSE | |
| | 3 | AIGU_GOAL_AHEAD | route points |
| | 500 | AIGU_SCORE | |
| lui 0x4020 | 2.5 | AIRB_LOOK_SECONDS | |
| lui 0x42c8 | 100 | AIRB_LOOK_MIN | |
| lui 0x4170 | 15 | AIRB_PASSED | |
| lui 0x40a0 | 5 | AIRB_ON_ROAD | |
| lui 0x3f80 | 1 | AIRB_HIT_WITHIN | |
| gp-28584 | 0.1 | AIRB_SLOWER_BY | |
| lui 0x41f0 | 30 | AIRB_MIN_SPEED | |
| | 600 | AIRB_SCORE | |

### The tables

| | Retail | Port's constant (the demo's) |
|---|---|---|
| `_vt$18AIActionGetUnstuck` | 0x002b7a50 | 0x0029aee0 |
| `_vt$22AIActionAvoidRoadBlock` | 0x002b7a90 | 0x0029af20 |

`aiactions_install_vtables` installs the eleven. DoSnapshot (0x001c8bb8
and 0x001c96b8) is left pending.

copmanager.h's tRoadBlock now has the two cops (0), the route point
(36) and route (40), the spike belt (52), the escape lane (92) and the
distance round the track (100). Its layout check holds where a pointer
is 4 bytes. GetNumActiveRoadBlocks and GetActiveRoadBlock were already
ported (copmanager.c), walking the PursuitList.

### The checker

drivingchoice_check adds:
- `@n gu score timeout -1 lifetime` and `@n rb score timeout -1 j`, the
  roadblock being `rbs[j]` (NULL for a negative j); `@sc gu` and `@sc rb` (its roadblock out
  filled first); `@as`, AreWeStuckBehindSomeone;
- `@ct k i time x y`, a collision's time and contact point; `@stp k x
  y`, a car's point to steer to; `@td k dist`, its distance round the
  track (the track's length is `G TLEN`); `@ut k usage`, its type info's
  UsageType; `@mv k`, its MatrixValid cleared;
- `@rbf j c0 c1 route point dist sx sy ex ey`, a roadblock, and `@pu
  spec...`, the cop manager's pursuits, each a roadblock's number or `-`
  for none, linked round PursuitList (44).

On both sides FindWhereIAm is a stub in each controller's test table
(CVT, +72), and ClearSteeringMemory and GetSteerToPoint in the drivers'
(DVT, +128 and +160); each prints its car. CompareDistances,
GetNumActiveRoadBlocks, GetActiveRoadBlock, FindClosestPointAhead,
WorldToCar and IsBlinking run as shipped.

s_unstuck, 40 scenarios, drives GetUnstuck as AIDriver would on
s_pull_hit's world. Between the calls my car is on the road, at its
edges and 20 m past them (and 0.1 either side), heading along it, out
and back, at each speed either side of the tests' (1, 15, 20, 25 and
0.001 past 1), as AI, traffic and other modes, with 2, 3 or 4 wheels
down, blinking or not, its body not always unit length; its point to
steer to is ahead or not; its collisions are in front, behind and
beside, either side of 0.4 s old; the list's cars are either side of
being in my way, my own entry among them now and then; and the minimum
lifetime is none, either side of 0.001 from -1, or seconds.

s_roadblock, 40 scenarios, drives AvoidRoadBlock the same way: four
roadblocks on up to four pursuits, each with its cops or not, on my
route ahead or behind or on another, its escape lane on the road, either
side of 5 m past it and past the route's end; my distance round the
track and the roadblocks' either side of the range and of 15 m behind,
the track's length wrapping them or not; and the list's cars cops,
traffic or racers, some either side of 30 and 30.1.

The first mutation pass left 32 alive. s_gu_edge, two rounds of
thirteen kinds, closes 26 of them. Eleven are on a straight road along x,
25 m each side with its lines on its centre, so a car's across is -y
exactly:
- gu-off: my car exactly 20 m past either edge and an ulp either side.
- gu-speed: an AI car at 25 m/s and a traffic car at 20, an ulp either
  side and 0.5 off, drifting out over the right edge with its point to
  steer to behind it.
- gu-coll: something hit in front exactly 0.4 s ago and either side, at
  speeds either side of stopped.
- gu-aws: a stopped car in my way, my speed exactly 15 and either side,
  facing the goal.
- gu-face: the facing dot exactly 0.98 and an ulp either side, found by
  searching dy over ulps in bNormalize2's float order.
- gu-young: a lifetime not in effect, poked to 5 s or 1, facing the goal.
- gu-fail: something hit behind exactly 0.4 s ago and either side, at
  speeds either side of 1 and -1.
- gu-clear: the location clear while the lifetime runs.
- rb-range: the roadblock exactly the range ahead and an ulp either
  side, then exactly 15 m behind and either side.
- rb-esc: a roadblock on another road, its escape lane exactly 5 m past
  either edge of mine and an ulp either side, behind me, and off the
  road near my road's end.
- rb-ahead: a stopped racer in my way, its entry level, behind or ahead.

Two need a curved road:
- rb-start bends it 0.2 rad a point, so it comes back on itself: the
  escape lane is on the road a few points ahead of me but behind the
  road's first point, so where the search starts matters.
- rb-last bends it 0.05 a point, with the escape lane off the road and
  me a few points from the end, so the target runs to the last point and
  the fill-up works its offset out again in floats.

The other six are equivalent:
- gu-ctor-on-le: `<=` and `<` part only where |lifetime + 1| is exactly
  0.00100000005f. Near -1 the sum is exact (Sterbenz), a multiple of
  2^-24, which that is not.
- gu-sc-coll-lt: at a speed of exactly 1 the epsilon test holds anyway.
- gu-sc-coll-eps-le: the same argument as gu-ctor-on-le, about 1.
- gu-sc-coll-eps-abs: without the fabsf, the test differs only for a
  speed under 1 - 0.001, where `v < 1` holds already; a NaN fails both.
- gu-cp-goal-check: the target was just cleared, so it has fewer than
  two points, and with no car the point is accepted either way.
- rb-cp-slower-b: SetDesiredSpeedSlowerThanThisCar doesn't read its
  second float.

Three of the earlier slices' patterns (dr-across-hl, dr-the-car and
ar-cp-line) stopped being unique once these two were in the file, and
carry a line of context.

Its numbers:
- 778 scenarios, 274688 ops, 297126 lines, 0 differ.
- 186 mutations for 11d-3b: 180 caught (10 by a crash) and 6
  equivalent. Across the whole checker, 1453 mutations: 1419 caught,
  34 equivalent and 0 unexplained.
