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
whether it is done. The actions themselves are 11d; the five small ones
are under "The small actions (11d-1)" at the end. This is the base:
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
