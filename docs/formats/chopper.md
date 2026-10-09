# Chopper (the police helicopter)

`Chopper` is the police helicopter of Hot Pursuit. It follows a car along
the track's routes, flies bombing runs ahead of it, and drops rockets,
smoke bombs or spike belts. tPursuit owns one when the race has a
helicopter. The port has it in `chopper.{c,h}`, in slices:

| slice | what |
|---|---|
| 12k-1 | the HeliSheet it flies over (`helisheet.md`) |
| 12k-2 | the object, following and attacking a car, the target spot, placing it in the world (this page) |
| 12k-3 | planning |
| 12k-4 | flying |
| 12k-5 | drawing, dust and the ChopperSound |
| 12k-6 | the bombing run |
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

## The port

- **No sound unless it is set.** The ChopperSound is task 29's. The port
  builds one only through `gCreateChopperSoundFn`, and skips every call
  through it when there is none. Retail calls through it unguarded except
  in the destructor.
- **The flags word starts at 0** in FindUnobstructedSpot (see above).

## The cross-check

`tools/chopper_check.py` runs retail's functions in mipsemu against
`chopper.c` and `coputil.c`'s RotateVector, with emath's rotations,
bSinCos and bIdentity real on both sides. Everything else is a stub that
logs its arguments and answers from the script: the TopologyCoordinate,
the TrackPathCoordinate, the WorldObject, the AcidFX emitters, the routes
and signposts, the HeliSheet's FindZValue, and the sound's table. After
each call it compares every field at retail's offsets, the pad included.
The model shares the port's two divergences. It lends retail a silent
sound when the port has none, and it zeroes the flags word on entry to
FindUnobstructedSpot.
