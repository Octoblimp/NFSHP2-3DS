# CopDriver

The CopDriver half of retail's `copdriver.obj` (0x001a1ce8 .. 0x001a32e8).
`DoSnapshot` (0x001a2b58) came later, with the replay (TASKS 72c). This
is step 12d: the controller an AI cop's car gets
under COP_CONTROL. It drives the car through CopMover
([cop-mover.md](cop-mover.md), 12c), the other half of the file.

Step 12d also brings what CopDriver calls:

- tAICop's drive target in `cop.c`: IsNearPursuitTarget,
  InitializeDriveTarget and UpdateDriveTarget ([cops.md](cops.md));
- CarInRecentCollision, the first of `coputil.obj`, in `coputil.c`;
- tPursuit's two drive targets and its history, laid out in
  `copmanager.h`, and the history's VelocityAt in `copmanager.c`.

Ported to `3DS Files/source/copdriver.{c,h}`. Cross-checked by
`tools/copdriver_check.py` against `tools/src/copdriver_test.c`, and the
tAICop part by `tools/cop_check.py`. In both, the retail image
(SLES_507.31) runs in mipsemu as the oracle.

## The record, 76 bytes

The same in the demo (`.mdebug` t1468) and retail.

| Off | Field | Type |
|----:|-------|------|
| 0 | Base | `TrackedController`, 36 bytes: CarController (Driver, pCar, vptr) and the route |
| 36 | State | `eCopDriverStates` |
| 40 | StateBeforeGettingStuck | `eCopDriverStates`, what BACKING_UP goes back to |
| 44 | SubState | `int`: 1 on the pursuit's own targets, 0 on the cop's |
| 48 | fStuckTimer | `float` |
| 52 | fBackingUpTimer | `float` |
| 56 | fPatrolSpeed | `float`, 29.057 m/s (65 mph) from the constructor |
| 60 | nCopIndex | `int`, the cop's slot in `pCopManager->Cops` |
| 64 | v2SteerTarget | `bVector2` |
| 72 | nCarClass | `int`, by car type |

The states: DISABLED 0, PARKED 1, PATROLLING 2, PURSUIT 3, BACKING_UP 4.

`_vt$9CopDriver` is at 0x002b5998, in TrackedController's layout:

| Slot | Entry |
|-----:|-------|
| 8 | the destructor, 0x001a1e30 |
| 16 | DebugDisplay, CarController's |
| 24 | DoSnapshot, 0x001a2b58 (TASKS 72c): a section begun with the object; the TrackedController, the three states' low bytes, the timers and speed, the steer target and the cop index as one byte |
| 32 | Think, 0x001a2110 |
| 40 .. 80 | TrackedController's route entries |
| 88 .. 104 | CarController's SetToPhysicsMode, ForceBoost and ReleaseBoost |

`Car::SetControlMode`'s COP_CONTROL arm (mode 4) builds one through
`gCopDriverCtorFn` ([car-modes.md](car-modes.md)). main.c points that seam
at `copdriver_construct`, and `COPDRIVER_SIZE` is `sizeof(CopDriver)`.

## The tuning

The .lit4 pool, gp-29468 .. gp-29440, the pursuit file's gp-15596, and
constants the code builds with `lui`. gp-29460 and gp-29452 are both the
mph factor, and gp-29456 and gp-29448 both 1.1: each of Think's two arms
reads its own copy.

| Where | Bits | Value | Use |
|------:|------|------:|-----|
| gp-29468 | 41e87445 | 29.057 | the patrol speed, 65 mph |
| gp-29464 | 415692b6 | 13.411 | translating needs this speed, 30 mph |
| gp-29460 | 400f2b02 | 2.237 | m/s to mph |
| gp-29456 | 3f8ccccd | 1.1 | catching up |
| gp-29444 | 410f0c79 | 8.941 | the slow speed, 20 mph |
| gp-29440 | c10f0c79 | -8.941 | backing up |
| gp-15596 | 3f266666 | 0.65 | the history's later look back, s |
| `lui` | 3e800000 | 0.25 | the history's first look back, s |
| `lui` | 41a00000 | 20 | how far ahead the steer target is; the near target's range |
| `lui` | 42200000 | 40 | translating's range |
| `lui` | 40800000 | 4 | the throttle while steering for a target |
| `lui` | 40000000 | 2 | the backing-up time; the stuck speed |
| `lui` | 3f800000 | 1 | the stuck time |
| `lui` | 40200000 | 2.5 | BLOCK's lane |
| `lui` | 42700000 | 60 | BLOCK's mph |
| `lui` | 46800000 | 16384 | a quarter turn, BAM |

**How far past the line's speed.** The table at 0x00310ef8 scales the
driving line's speed by `tCopManager::nDifficultyLevel`: 1.15, 1.2 and
1.25. When the chased car has no player, it is always 1.25.

## The constructor

`__9CopDriverP3Car` (0x001a1ce8) runs TrackedController's constructor
and sets its own table. It bMallocs a NullDriver ("NullDriver", 560
bytes, pool 16), with CarDriver's constructor inline and the table
changed after, NitroFlag 0 and DesiredGear -1, and makes it the Driver.

It is then parked, with StateBeforeGettingStuck parked, SubState 1, both
timers 0, no cop (-1), the steer target at the origin and the patrol
speed at 65 mph. The image fills the steer target by reading back the 0
it has just stored. nCarClass goes by the car type's Type: 0 for 32,
1 for 33, 2 for 34, 3 for 31 and 4 for 4. Any other type leaves it as it
was.

The destructor stores its own table and destroys the Driver through its
table (flags 3). Then it runs TrackedController's destructor with its
flags.

## Think

`CopDriver::Think(dt)`, 0x001a2110.

1. TrackedController's Think. A car not on COP_MOVEMENT does nothing
   else. (The image reads `Cops[nCopIndex]` before that test, and the
   port after.)
2. **Stuck.** If AreWeStuck and the cop is not within 20 m of the car it
   chases, the state is kept in StateBeforeGettingStuck and becomes
   BACKING_UP, for 2 s.
3. The mover's braking goes back to 40 and its throttle to the car
   type's (ResetMaxThrottleAccel).
4. By the state:
   - **DISABLED:** braking at 2, nothing wanted, no throttle or
     steering, EBrake and Brake full, SportGear and DesiredGear -1,
     STEERING. Then the Driver's SetDesiredSpeed (slot 56) is called
     with its Throttle, over 10 s. A NullDriver's does nothing.
   - **PARKED:** no speed wanted, STEERING.
   - **PATROLLING:** STEERING, for the point 20 m along the driver's own
     drive target (FindDriveTargetPointByDistance, offset by the cop's
     `New48`), at fPatrolSpeed.
   - **PURSUIT:** below, if the cop has a pursuit.
   - **BACKING_UP:** the timer runs down by dt. Below 0 the state goes
     back to StateBeforeGettingStuck. Otherwise the steer target is the
     patrol point (if it was patrolling) or the pursuit's point (if it
     was in pursuit), and the car goes for it in reverse at 20 mph.

**Going for the steer target** (0x001a2a4c, PATROLLING's and
BACKING_UP's tail): the heading wanted is bToPolar of the way to it, the
throttle is held to 4, and the speed is the one given.

### PURSUIT

GetPursuitTargetPoint gives the steer target. If the cop is within 40 m
of the chased car, going its way (their velocities' dot is above 0) and
at 30 mph or more, it translates. Otherwise it steers.

**Translating.** The mover's TRANSLATING state, for a velocity:

1. The chased car's velocity. A player's comes from the pursuit's
   history: the velocity 0.25 s back, scaled to the length the velocity
   had 0.65 s back (if the first is not 0).
2. By the sub-state:
   - FLANK and GET_AHEAD: along 1.5, and 3 m/s extra;
   - BUMP: across 10, and 3 extra;
   - BLOCK: if the two cars are within 2.5 m across their route points
     of each other, then below 60 mph no velocity, else half; further
     apart, 1.1 times;
   - STOP: braking at 14, across 3.
3. The way to the target is split along the cop's own velocity (made a
   unit with bNormalize) and across it. The velocity wanted is
   `along x (the along part) + across x (the rest) + the chased
   velocity`; along is 1 and across 1.5 unless the sub-state set them.
   STOP wants none. The result is lengthened by the extra, and z
   is 0.

**Steering.** The mover's STEERING state, with the heading for the
target and a speed by the sub-state:

- PURSUIT_FOLLOW, FOLLOW_OFFSET, FOLLOW_BACKWARDS, FLANK, BUMP: the
  distance to the chased car plus its speed;
- LOW_SPEED_CLOSE_FOLLOW: five times the distance plus its speed;
- BLOCK: as above, 0, half or 1.1 times its speed;
- GET_AHEAD: 1.1 times its speed;
- ACQUIRE: the mover's base top speed;
- the rest: 0.

The speed is then held to the cop's route point's driving line speed,
for the lower class of the two cars, times the scale above. If it is
still above 20 mph and the chased car is more than a quarter turn off
the cop's heading (and more than 1 m away), it is 20 mph.

## GetPursuitTargetPoint

0x001a1e90, `(out)`. Without a pursuit it leaves `out` alone.

- **PURSUIT_FOLLOW, FOLLOW_OFFSET, LOW_SPEED_CLOSE_FOLLOW,
  FOLLOW_BACKWARDS, FLANK, BUMP, STOP:** the pursuit's own targets, with SubState 1.
  Within 20 m of the chased car the driver's drive target becomes the
  pursuit's near one, and the point is GetDriveTargetPointByDLOffset
  FromStart on it. Further away it becomes the far one, and the point
  is 20 m along it from the cop. Both are offset by `New48`.
- **BLOCK:** SubState 0. InitializeDriveTarget and UpdateDriveTarget
  along the chased car, then the point 20 m along from it, as far across
  as the chased car is across its route point.
- **GET_AHEAD:** the same, with no offset.
- **ACQUIRE:** the same along the cop's own car.

## The two walkers

**FindDriveTargetPointByDistance** (0x001a2c30, `(out, lateral, target,
pos, dist, offset)`). It returns 1 when it found a point.

- With one point, that point, if pos is within dist of it; lateral 0.
- With more, it looks from the last segment back for the first one pos
  is alongside: `0 <= along < len`. From there it walks on, a segment at
  a time, until the length covered reaches dist. The point is that far,
  offset along by `offset.x` and across by `offset.y`, both in that
  segment's unit. `lateral` is how far pos is across from it.
- Not found, `out` is point 1, or point 0 with fewer than two.

**GetDriveTargetPointByDLOffsetFromStart** (0x001a2ef0, `(out, target,
offset)`). It starts from point `NumPoints - 1`, read as
`target + NumPoints x 16`, whatever NumPoints is. With fewer than two
points, that is the answer. Otherwise it walks back while the length so
far is within `offset.x`, and puts the point that far along. Then it
moves `offset.y` across, square to that segment. Its lengths are divided
the EE's way.

## AreWeStuck

0x001a2a90, `(dt)`. Not in a collision this frame
(CarInRecentCollision: the car's dynamic body has NumCollisions not 0),
it is 0. PATROLLING and PURSUIT below 2 m/s count the timer up and say
yes past 1 s. At 2 m/s or more, the timer is cleared. DISABLED, PARKED
and BACKING_UP clear it.

## The accessors

SetPatrolSpeed, SetState and SetCopIndex set their field.
GetRouteNumbersToUse does nothing in retail and in the port.

## tPursuitHistory::VelocityAt

0x0022d080, in the pursuit file, new in retail. The history is 368
bytes: the count, 30 velocities newest first, the seconds each lasted,
and a table at 364. VelocityAt(t) walks the times from the newest. In the
first entry whose running total reaches t (unless it is the last one
kept), the answer is that velocity plus a slope times a time. The slope
is that velocity less the next older one, over the entry's own time. The
time is the running total less the **newest** time, fTime[0], whichever
entry it is. Past the end, or with nothing
kept, it is the newest velocity.

## The check

`tools/copdriver_check.py` runs retail's code in mipsemu. Run as shipped
under it are CopMover's ResetMaxThrottleAccel, bToPolar, bNormalize,
VelocityAt and CarInRecentCollision. Stubs on both sides: bMalloc,
TrackedController's constructor, destructor and Think, DriveTarget's
constructor, Clear and assignment, GetRoutePoint, the three tAICop
functions, and the NullDriver's destructor and SetDesiredSpeed. The
script's 21727 operations:

- the constructor on every car type, the accessors and the destructor;
- FindDriveTargetPointByDistance and GetDriveTargetPointByDLOffset
  FromStart on fixed and random targets, and with signed zeros and tiny
  segments;
- AreWeStuck in every state, about 2 m/s and 1 s;
- GetPursuitTargetPoint in every sub-state, about 20 m;
- Think:
  - off COP_MOVEMENT, in every state;
  - patrolling;
  - getting stuck and backing up, to 0 exactly;
  - pursuit steering by sub-state and class, and the quarter turn;
  - pursuit translating, BLOCK's lanes, and the history;
  - the edges: 40 m, a dot of 0, exactly 30 mph, NaN, -0 and infinite
    speeds, and DISABLED from a car that was driving;
  - random runs.

29413 lines, 0 differ. `--mutate`: 232 mutations, 226 caught and six
equivalent:

- the NullDriver's size, which is CarDriver's (560);
- in FindDriveTargetPointByDistance, below 0 points the segment loop
  doesn't run; a zero-length segment's unit is never read;
- translating with a zero velocity wanted: 0, or NaN with the extra, either
  way;
- STOP's across, which is never read since it wants no velocity
  (the image skips it too, at 0x001a25fc and 0x001a2664);
- at exactly 20 mph, the clamp to 20 mph sets the speed it already has.

The tAICop functions' check is in [cops.md](cops.md).
