# Chopper (the police helicopter)

`Chopper` is the police helicopter of Hot Pursuit. It follows a car along
the track's routes, flies bombing runs ahead of it, and drops rockets,
smoke bombs or spike belts. tPursuit owns one when the race has a
helicopter. The port has it in `chopper.{c,h}`, in slices:

| slice | what |
|---|---|
| 12k-1 | the HeliSheet it flies over (`helisheet.md`) |
| 12k-2 | the object, following and attacking a car, the target spot, placing it in the world (this page) |
| 12k-3a | the chase logic under the plans (this page) |
| 12k-3b | the plans: HighLevelPlanning, CleverPursuitPlan and BombRunLogic (this page) |
| 12k-4 | flying |
| 12k-5 | drawing, dust and the ChopperSound |
| 12k-6 | the salvos: FireSalvo and its launch (`chopperfire.c`) |
| 12k-7 | tPursuit's UpdateChopper and the manager's methods |

Retail's ELF is stripped. The names are the demo's (`Chopper.obj`), and
the retail code is `0x001e7a90` .. `0x001eae04`. `tools/chopper_check.py`
cross-checks the port against the image.

## The object

The demo's is 752 bytes (.mdebug type#2444). Retail's is 976:

| offset | field | note |
|---:|---|---|
| 0 | `pChopperSound` | ChopperSound, whose Sound3d's vptr is at +28 |
| 4 | `WorldObj` | a WorldObject named `TRACK_HELICOPTER` |
| 8 | `TopologyCoord` | 704 bytes; the demo's was 560 |
| 712 | `DustEmitters` | bTList of AcidEmitters, `XEM_HELI_DUST` |
| 720 | `TimeUntilThink` | |
| 724 | `CurrentCar` | |
| 728 | `Plan` | ChopperPlan |
| 732 | `MoveMode` | 0 pursuit, 1 rotate |
| 736 | `ChopperRoute`, `ChopperPoint` | where the helicopter is |
| 744 | `TargetRoute`, `TargetPoint` | where the bombing run aims |
| 752 | `TP` | TrackPathCoordinate, 40 bytes |
| 792 | `TargetDistance` | |
| 796 | `OldCarRoute`, `OldCarPoint` | the car's, when the run began |
| 804 | `BombRunType` | ChopperAttackType |
| 808 | `NumSalvosReleased` | |
| 812 | `TimeUntilNextSalvo` | |
| 816 | `NextLauncher` | |
| 820 | `Timeout` | 25 |
| 824 | `StuckTime` | retail's; Fly adds to it when a move fails |
| 828 | `TotalSalvos` | retail's; the bombing run counts its salvos |
| 832 | `CurrentPos` | bVector3 |
| 848 | `Matrix` | retail's; CalcMatrix builds it |
| 912 | `Speed` | |
| 916 | `Acceleration` | bVector2 |
| 924 | `Roll`, `DesiredRoll`, `Yaw`, `Pitch`, `DesiredPitch` | degrees |
| 944 | `RotRate`, `ZVelocity`, `GroundZ` | |
| 956 | `EmitDust` | bool |
| 960 | `New960` | retail's; 1 when Easter egg 5 is on |
| 964 | pad | 12 bytes to 976 |

Everything after the TopologyCoordinate is 144 bytes further on than the
demo's.

### The plans

| value | ChopperPlan |
|---:|---|
| 0 | PURSUIT |
| 1 | HEAD_TO_STAKEOUT |
| 2 | AT_STAKEOUT |
| 3 | START_CHASE |
| 4 | BOMBING_RUN |
| 5 | END_CHASE |
| 6 | EATING_DONUTS |

A new helicopter is EATING_DONUTS, which is idle.

## The bombing runs (`0x0031a7c8`)

Each row is 32 bytes, indexed by ChopperAttackType without a check:

| type | munition | Ahead | Velocity | Adjust | SalvoSize | NumSalvos | SalvoSpread | SalvoDelay |
|---:|---|---:|---:|---:|---:|---:|---:|---:|
| 0 rocket | CM_ROCKET | 2 | 20 | 0 | 1 | 1 | 0 | 0 |
| 1 smoke bomb | CM_SMOKEBOMB | 2 | -10 | 0 | 1 | 8 | 30 | 0.5 |
| 2 smoke bomb | CM_SMOKEBOMB | 1.5 | -10 | 0 | 2 | 3 | 5 | 0.5 |
| 3 spike belt | CM_DROPPED_SPIKES | 2 | -10 | 0 | 1 | 1 | 0 | 0 |
| 4 | CM_DROPPED_SPIKES | 1 | -10 | 0 | 1 | 2 | 4 | 1 |

The demo's enum has four types. Retail's table has a fifth row, a pair of
spike belts dropped a second apart.

## The constructor and destructor

```
Chopper::Chopper()                      0x001e7a90
    TopologyCoordinate(), dust list empty, TrackPathCoordinate()
    WorldObj = new WorldObject(bStringHash("TRACK_HELICOPTER"), NULL, 1)
    pChopperSound = CreateChopperSound(this)          0x00215098
    afxGetEmitters(&DustEmitters, bStringHash("XEM_HELI_DUST"))
    ClearVariables()
    Plan = EATING_DONUTS
    New960 = !AIDemoMode && !ReplayDemoMode && egg 5 is on

Chopper::~Chopper()                     0x001e7b80
    afxDeleteEmitters(&DustEmitters)
    if pChopperSound: its destructor (slot 8) with 3
    if WorldObj: its destructor with 3
    the TP's, the TopologyCoordinate's and the list's destructors
    with bit 0: __builtin_delete
```

ClearVariables (`0x001e7c38`) zeroes every field from `TimeUntilThink`
on, except `Matrix`, which becomes the identity, and `Timeout`, which
becomes 25. The TP is reset at `CurrentPos`, which is zero by then.

## Following and attacking

```
FollowThisCar(car)                      0x001e7f80
    if New960: car = World->CarTable[0]     // the player's, NULL or not
    if !TheHeliSheet || !HasSignposts(): return 0
    if car == NULL:
        if Plan is START_CHASE or EATING_DONUTS:
            CurrentCar = NULL; Plan = EATING_DONUTS
        else:
            Plan = END_CHASE
    else:
        if Plan is not EATING_DONUTS or START_CHASE: return 0
        CurrentCar = car; Plan = START_CHASE
    TimeUntilThink = 0
    return 1

AttackCar(type)                         0x001e8040
    if Plan != PURSUIT:
        if CurrentCar: FollowThisCar(CurrentCar)
        return 0
    TimeUntilNextSalvo = 0; Timeout = 25
    Plan = BOMBING_RUN; BombRunType = type; NumSalvosReleased = 0
    TargetDistance = the 2D distance to the car
    if ChopperBehindCar(): TargetDistance = -TargetDistance
    Target = the helicopter's route and point
    OldCar = the car's route and point
    AdjustBombTarget()
    return 1
```

**The run's target** is some way ahead of the car on its route:

```
AdjustBombTarget()                      0x001e8140
    ahead = max(Ahead * car speed, 100)
    if TargetDistance + 24 < ahead:
        ShiftTarget(ahead)
        FindUnobstructedSpot()

ShiftTarget(dist)                       0x001e81d8
    out[5] = GuessTargetDestinations(car's route and point, dist + 24, forward)
    TargetDistance = dist
    the first of them not marked TRP_NO_HELISHEET becomes the target

FindUnobstructedSpot()                  0x001e82c0
    from the target, while the HeliSheet's polygon under the point has
    flag bit 0: TargetDistance += the point's Length, on to the next point
```

- **A NaN distance never shifts.** `TargetDistance + 24 < ahead` is false
  for NaN, so the target stays where it was.
- **FindZValue leaves the flags alone on a miss.** A miss after a hit
  keeps the walk going on the hit's flags. A miss on the first point reads
  whatever retail's stack held. The port starts the word at 0, which
  stops the walk.

## In the world

```
PlaceChopperInWorld(pos, z)             0x001e83b0
    the sound's Activate(1)
    CurrentPos = (pos, z); Pitch, Roll, their targets and Speed = 0
    Yaw = the car's heading * 360 / 65536
    the TP reset at CurrentPos; the interest box 1 round it
    GroundZ = the car's z, then FindGroundHeight()
    FindChopperPointFromScratch(); CalcMatrix()

RemoveChopperFromWorld()                0x001e84a8
    WorldObj->Enabled = 0; the sound's Activate(0); the interest box cleared

FindGroundHeight()                      0x001e8358
    GroundZ = GetElevation((CurrentPos.x, CurrentPos.y, GroundZ)); return the terrain
```

**The matrix** (`0x001ea3f8`) scales by 1.1 on each axis (gp-27984). It
turns by Roll on x, 360 - Pitch on y, and 180 - Yaw on z (plus 360 when
that is below 0). Each angle goes to BAM as `cvt.w.s(deg * 65536) / 360`,
truncated. The translation is CurrentPos raised by 2.3 (gp-27980). The
WorldObject's update (`0x001ea578`) copies it and enables the object.

## The rest of 12k-2

| function | address | what |
|---|---|---|
| ChopperBehindCar | `0x001e84f0` | CompareDistances(TP's, car's) <= 0 |
| RotateToChopperCoord | `0x001e8540` | RotateVector (`0x002313e0`) by 360 - Yaw |
| GetMaxDeceleration | `0x001e8560` | -120 heading to or at a stakeout, else -60 |
| Mute / UpdateSound | `0x001ead80` / `0x001eadb0` | the sound's Mute(i) (slot 32), Update(1, 0, 1) (slot 24) |
| AbortBombingRun | `0x001eadf0` | BOMBING_RUN becomes PURSUIT |
| FindChopperPointFromScratch | `0x001e8798` | GetNearestRoutePoint over the racing routes, flags 6 |
| FindChopperRoutePoint | `0x001e87e8` | the route's closest point within 24; then the signpost's new route's; then from scratch |

RotateVector turns `v` by `deg` degrees and reads both of its parts before
writing either, so `out` may be `v`.

## The chase logic

12k-3a ports these sixteen functions. HighLevelPlanning (12k-3b) calls
them with a `ChopperTarget` on its stack, 12 bytes: `Location`
(bVector2) and `DesiredSpeed`.

```
StartChaseLogic(t, on_sheet, flags, z)  0x001e8590
    if !on_sheet or flags bit 1: return 1
    PlaceChopperInWorld(t->Location, z + 150)
    Plan = PURSUIT; EmitDust = !(flags bit 0); ZVelocity = -25
    return 0

EndChaseLogic(t)                        0x001e8608
    if FindZValue(CurrentPos) hits, giving z and flags:
        if z + 150 <= CurrentPos.z:
            RemoveChopperFromWorld(); Plan = EATING_DONUTS; return 1
        if !(flags bit 1 and ZVelocity == 0):
            ZVelocity = 25; t->Location = CurrentPos; return 0
    walk on from the helicopter's point to the route's end or the first
    point more than 30 away; t->Location = the last point found
    t->DesiredSpeed = 50; return 0

SetFollowSpeed(t)                       0x001e88c0
    t->DesiredSpeed = the car's VelocityMagnitude + 30

FindPreviousFork(info, b)               0x001e88e0
    back = b ^ 1; count = 0
    loop:
        n = FindNearbySignpost(info, back); if n == 0: return 0
        count += n
        info = the sign's new route and point
        if its sign (Flags & 7) is not ALWAYS_TAKE (2): return count
        info's point = GetRelativePoint(info, back); count += 1

SwitchToNearbyFork(out, in, b, maxd)    0x001e8990
    out = in; k = FindPreviousFork(out, b); if k == 0: return 0
    2k times: if out's point is nearer than maxd: return 1
              out's point = GetRelativePoint(out, b); if NULL: return 0
    return 0

TargetChopperPoint(t)                   0x001e8a80
    t->Location = ChopperPoint's position

FollowRoute(t, route, point, fwd)       0x001e8a98
    mind = CalcMinRouteFollowDistance(t)
    if ChopperPoint is point or further than mind:
        if further: SetFollowSpeed(t)
        TargetChopperPoint(t); return
    out[5] = FindPointsToTarget(the helicopter's, (route, point), fwd, heli)
    if none, and SwitchToNearbyFork(the helicopter's, fwd, mind) finds a
    fork: FindPointsToTarget again from the fork
    if none: return
    take the first that is point or further than mind, else the last
    if it is not point: SetFollowSpeed(t)
    t->Location = its position

BeginStakeout(t, route, point)          0x001e8ce8
    walk on from (route, point) to the first point without
    TRP_NO_HELISHEET whose signpost lacks NO_STAKEOUT (Flags bit 4)
    off the route's end: BailToPointNearChopper(t); return
    Target = that point if the sign is BACKWARDS (Flags bit 3), else the
    sign's new route and point
    c = FindClosestPoint(Target's route, CurrentPos, 400)
    if c and Target's index < c's:
        Target = the helicopter's; TargetChopperPoint(t); return
    Plan = HEAD_TO_STAKEOUT; Timeout = 60; FollowRoute(t, Target, 1)

HangoutNearHere(t, route, point)        0x001e8e70
    along = t's offset from point along its Direction
    across = 0.7 * t's offset across it          (gp-28048)
    loop: along *= 0.7
          t->Location = point's GetPosition(along, across)
          if FindZValue(t->Location) hits: return
          across *= 0.7

BailToPointNearChopper(t)               0x001e8f30
    HangoutNearHere(t, ChopperRoute, ChopperPoint)

CalcMinRouteFollowDistance(t)           0x001e8f40
    max(Speed * 0.1, 30)                         (gp-28044)

AdjustTargetInBounds(t)                 0x001e8f70
    up to 3 times:
        TestLocation 4.5 to -x, +x, +y and -y of t
        x: only -x on the sheet: x -= 1.5; only +x: x += 1.5; y alike
        nothing moved: return 1
    return 0

ChopperOnDifferentFork(route, point)    0x001e90f0
    if route is ChopperRoute: return 0
    info = the helicopter's; if FindPreviousFork(info, 1) == 0: return 0
    return info's route is route

AdjustTargetLocal(t)                    0x001e9368
    t->Location = RotateToChopperCoord(t->Location - CurrentPos)

TestLocation(x, y)                      0x001e98d0
    FindZValue(CurrentPos + RotateVector((x, y), Yaw)) hits

AdjustByThinkTime(f)                    0x001e9940
    f * 100
```

- **Indexes the image's way.** BeginStakeout compares two points'
  indexes in the route's table as `(p - table) * 0xb6db6db7 >> 4`,
  signed. For a point in the table that is its index exactly.
- **The fork's count** is shifted left by one and tested again, so a
  count of 2^31 walks no points.
- **The signpost's word.** Its Flags byte is bits 8 to 15: the sign is
  the low three bits, BACKWARDS bit 3 and NO_STAKEOUT bit 4.

## Planning

12k-3b ports the three functions above the chase logic. Think
(`0x001e9d48`, 12k-4) calls HighLevelPlanning once every 0.1 s. Its
caller, Fly (`0x001ea7d0`), skips Think while the helicopter is
EATING_DONUTS. That is the one plan in which CurrentCar may be NULL, so
the planning always has a car to read, except in END_CHASE, which never
reads it.

```
HighLevelPlanning(t)                    0x001e9648
    Timeout = max(Timeout - 0.1, 0)                         (gp-28036)
    unless END_CHASE:
        t->Location = the car's Position + 0.3 * its Velocity  (gp-28032)
        on_sheet = FindZValue(t->Location), giving z and flags
    unless START_CHASE: FindChopperRoutePoint()
    t->DesiredSpeed = -1
    BOMBING_RUN: BombRunLogic(t)
    HEAD_TO_STAKEOUT, AT_STAKEOUT:
        if on_sheet and (t within 60 or Timeout == 0): Plan = PURSUIT
        else if HEAD_TO_STAKEOUT:
            if TargetPoint within 30:
                Plan = AT_STAKEOUT; Timeout = 45
                t->Location = TargetPoint's position
            else: FollowRoute(t, Target, 1)
    START_CHASE: if StartChaseLogic(t, on_sheet, flags, z): return 1
    END_CHASE: if EndChaseLogic(t): return 1
    if PURSUIT: CleverPursuitPlan(t, on_sheet, flags)
    AdjustTargetInBounds(t); AdjustTargetLocal(t); return 0

CleverPursuitPlan(t, on_sheet, flags)   0x001e9150
    if ZVelocity != 0 and (flags bit 1 or !on_sheet):
        t->Location = CurrentPos; return
    near = t within CalcMinRouteFollowDistance(t)
    (route, point) = the car's
    if either is NULL: BailToPointNearChopper(t); return
    point = FindClosestPointAhead(route, t->Location, point), if any
    if on_sheet:
        if near:
            if Speed > 20:
                t->Location = point's GetPosition(t's offset along its
                                                  Direction, 0)
            return
    else if point has TRP_NO_HELISHEET:
        BeginStakeout(t, route, point); return
    if ChopperOnDifferentFork(route, point):
        BeginStakeout(t, route, point); return
    if near: HangoutNearHere(t, route, point)
    else: FollowRoute(t, route, point, ChopperBehindCar())

BombRunLogic(t)                         0x001e9398
    point = the car's point
    if point is not OldCarPoint:
        d = the distance from OldCarPoint to point
        if the car's route is not OldCarRoute, or OldCarPoint's index is
        below point's: d = -d
        TargetDistance += d; (OldCarRoute, OldCarPoint) = the car's
    AdjustBombTarget()
    if NumSalvosReleased > 0:
        TimeUntilNextSalvo -= 0.1; fire = it is below 0      (gp-28040)
    else if TargetPoint is within 30:
        a = the helicopter's offset from ChopperPoint across its
            Direction, (dir.y, -dir.x), so right is positive
        fire = (a - RightWidth if a > 0, else -(a + LeftWidth)) < 0
    if fire and FindZValue(CurrentPos) hits:
        FindGroundHeight()
        if CurrentPos.z - GroundZ <= 10:
            FireSalvo(); NumSalvosReleased++; TotalSalvos++
            Timeout = 25; TimeUntilNextSalvo = the type's SalvoDelay
            if NumSalvosReleased >= the type's NumSalvos:
                Plan = PURSUIT; return
    if Timeout == 0: Plan = PURSUIT; return
    FollowRoute(t, Target, 1)
```

- **The car's lead** is a bScaleAdd (`0x002589d8`), which writes y before
  x. The port's bScaleAdd2 keeps that order.
- **z and flags** live on HighLevelPlanning's stack, and FindZValue
  leaves them alone on a miss. Nothing reads them then. CleverPursuitPlan
  returns early, or never tests flags, when on_sheet is 0, and
  StartChaseLogic returns 1 before it looks. The port starts both at 0.
- **Indexes** are BeginStakeout's (above). The car's two points come
  from GetRoute and GetRoutePoint together, so both are in the route's
  table whenever the routes match.
- **FireSalvo** (`0x001ea8c0`) is 12k-6's. Until then, `chopperfire.c`
  has a placeholder that fires nothing. The run still counts its salvos
  and ends after the last one.

## The port

- **No sound unless it is set.** The ChopperSound is task 29's. The port
  builds one only through `gCreateChopperSoundFn`, and skips every call
  through it when there is none. Retail calls through it unguarded except
  in the destructor.
- **The flags word starts at 0** in FindUnobstructedSpot (see above).
- **HangoutNearHere stops** after a miss once both offsets are below the
  least normal float, or NaN. By then the EE has flushed them to zero,
  so every try is at the point itself, and the image tries it for ever
  if it is off the sheet. An IEEE float would shrink to the least
  denormal and stay there. The port leaves the target at that last try.
- **BombRunLogic skips the car's progress** when the car's point or
  OldCarPoint is NULL. The image only compares the two, then reads both
  positions, so a NULL point reads address 0.

## The cross-check

`tools/chopper_check.py` runs retail's functions in mipsemu against
`chopper.c` and `coputil.c`'s RotateVector, with emath's rotations,
bSinCos, bIdentity and bScaleAdd real on both sides. Everything else is
a stub that logs its arguments and answers from the script: the
TopologyCoordinate, the TrackPathCoordinate, the WorldObject, the AcidFX
emitters, the routes and signposts (FindClosestPointAhead among them),
the planners (FindNearbySignpost, FindPointsToTarget), the HeliSheet's
FindZValue, FireSalvo, and the sound's table. FindZValue answers per
point or by boxes of the plane. The routes' points sit inside their
tables, so BeginStakeout's indexes are the image's own. After each call
it compares every field at retail's offsets, the pad included, and the
ChopperTarget.

The model shares the port's four divergences:
- it lends retail a silent sound when the port has none;
- it zeroes the flags word on entry to FindUnobstructedSpot;
- a hook after HangoutNearHere's FindZValue (`0x001e8f04`) ends the loop
  by the port's rule;
- a hook at BombRunLogic's compare of the car's points (`0x001e93c8`)
  makes them equal when either is NULL.

Five mutations survive by construction. Two are in BeginStakeout's
index arithmetic, which only ever sees points inside the table. The
other three are HighLevelPlanning's starting on_sheet, flags and z,
which nothing reads unless FindZValue has set them.
