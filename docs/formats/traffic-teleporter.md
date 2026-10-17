# TrafficTeleporter

`TrafficTeleporter.obj` (0x002226f8 .. 0x002232c0; the demo's 0x0020e610 ..
0x0020f0f0), all of it. `DoSnapshot` (0x00222780) came with the replay
([replay.md](replay.md), TASKS 72d). This is step 11h-3, the last of the
traffic: TrafficCar (11h-1, [traffic-car.md](traffic-car.md)) moves a
traffic car, TrafficDriver (11h-2, [traffic-driver.md](traffic-driver.md))
drives it, and the teleporter places it.

Ported to `3DS Files/source/traffictele.{c,h}`, with the route planner it
asks, `GuessTargetDestinations` (0x001cbb70), in `airouteplan.{c,h}`
([ai-route.md](ai-route.md)). Cross-checked by `tools/traffictele_check.py`
against `tools/src/traffictele_test.c`, with the retail image (SLES_507.31)
running in mipsemu as the oracle.

## The shape of it

The World owns one, built by `World`'s constructor through
`gTrafficTeleporterCtorFn` on 88 bytes it has `bMalloc`'d. It does two
things:

- **At the start**, `World::AddTrafficCar` asks `PlaceNewCar` for each
  traffic car the race wants. It picks a random point on the traffic
  routes, every point as likely as any other, where nobody can see it and
  nothing is near.
- **While the race runs**, `DoTimestep` wakes every 1 to 16 seconds,
  depending on the density. It takes the next traffic car out of sight and
  moves it 250 or more ahead of a random player, still out of sight, with
  a new skin. The traffic seems endless because the same cars keep coming
  round.

The traffic routes are 50 to 59 one way and 60 to 69 the other (the
manager's "50..69 as traffic", see [track-route.md](track-route.md)).
`ForwardsOrBackwards` picks the oncoming ones with `TrafficOncoming`'s
chance.

**"Visible"** means within 250 round the track of the nearest player
(`World::GetDATToClosestPlayer`). It is not the camera's view. A car 251
behind the player can be moved, and one 200 off to the side across a
bend counts as seen.

## The record, 88 bytes

The demo's `.mdebug` type #1882; retail's constructor stores the same
fields.

| Off | Field | |
|----:|-------|---|
| 0 | TimeUntilTeleport | seconds to the next think |
| 4 | LastCar | the traffic car last looked at |
| 8 | ForwardTotals[10] | running point counts over routes 50 .. 59 |
| 48 | BackwardTotals[10] | and 60 .. 69 |

`LastCar` is a `Car *` in the `.mdebug`, but retail keeps an index in it,
counted from the World's `TrafficCarPos`.

## The literals

| Value | Where | Use |
|------:|-------|-----|
| 0.4 | gp-27148 | below this density, no car is ever moved |
| 250 | | the sight distance; the first place tried |
| 50 | | each later place, on from the last |
| 24.5865 | gp-27144 | a moved car's speed |
| 100 | | too close to another car |
| 20 s | `lui 0x41a0` | the first think, and how long the start is kept clear |
| 2000 | | how far round the start line is kept clear |
| 100 | | PlaceNewCar's tries |
| 101 | | PickRoutePoint's draws |
| 0.00025 | gp-27140 | WorldTimer's ticks in seconds |
| 0.01 | gp-27136 | the boundary distances' percent |

## The functions

**The constructor** (0x002226f8) fills both totals, then sets the think
time and holds the first think to at least 20 s, more than `SetThinkTime`
ever gives. `LastCar` is 0. A NaN think time is left as it is (`c.lt.s`).

**The destructor** (0x00222760) has nothing to undo, and `bFree`s the block
on `flags & 1`.

**DoTimestep** (0x002227e0) returns at once in any of these cases:

- the density is below 0.4 (a NaN goes on);
- there is no traffic;
- the race is not at `RACE_STAGE_RACING`;
- there are no players.

Otherwise the clock runs down by `dt`. When it reaches 0 it is set again,
and the traffic cars after `LastCar` are looked at in turn, wrapping back
to the first. The first one out of sight goes to `TryToTeleportCar` and
becomes `LastCar`. Coming round to `LastCar` again, every one in sight, it
stops. The table count is compared unsigned (`sltu`).

The image reads the race without testing it. The port tests it.

**PlaceNewCar** (0x002228e0) returns NULL when either way has no points.
Only the last total is read, so the first slot can be empty. Otherwise it
draws a point with `PickRoutePoint` and tests it with `IsGoodPlace`
(`all` set), up to 100 times. On a good one:

- a TrackPathCoordinate is reset to the point and dropped, as the image
  does;
- the heading is `bATan` of the point's direction, the height its
  Elevation;
- a random skin goes into the DriverInfo's ride;
- the Car is built at the point's DAT, on `eNO_MOVEMENT` and
  `TRAFFIC_CONTROL`;
- the controller is given the route and point (vtable slot 40);
- it is not drawn.

racerun.c starts the traffic at the countdown.

**TryToTeleportCar** (0x00222a90) picks a direction and a random player.
It notes how far the car is ahead of the player, and finds the player's
nearest point on the routes that way. Off the routes, it gives up. It asks
GuessTargetDestinations for one point 250 on, then 50 on from each until
`IsGoodPlace` (`all` clear, the car itself left out) likes one. It gives
up when:

- the planner finds nothing;
- the place is behind the player;
- the car was already ahead, and the place is further ahead than the car.

A good place gets `Car::ResetToRoutePoint` at 24.5865, `TRAFFIC_MOVEMENT`
and `SwitchSkin`.

**IsGoodPlace** (0x00222c40; the name is the port's) answers no when:

- the race is under 20 s old and the point is within 2000 of the start
  line, which is the start line boundary's percent of the track length;
- the point is visible;
- `TooCloseToAnotherCar` says yes.

With no race the image reads the start line through address 0. The port
leaves it out.

**CheckIsVisible(float)** (0x00222dc8) is within 250 round the track.
**CheckIsVisible(bVector2 \*)** (0x00222d88) is within 250 in the plane;
nothing calls it.

**SetThinkTime** (0x00222e10) is `(1 - TrafficDensity) * 15 + 1`: 16 s with
none, 1 s at full.

**ForwardsOrBackwards** (0x00222e40) is 1 unless `World::Random(1.0)` is
under `TrafficOncoming`.

**FillInTotals** (0x00222e88) fills `out[i]` with the sum of `NumPoints`
over routes `first .. first + i`. A missing route counts 0, and a negative
slot reads none (`bltz`).

**TooCloseToAnotherCar(float)** (0x00222fc0) walks the World's car list,
passing over the car left out, the poofed and, without `all`, the undrawn.
It is true for a traffic car within 100 either way round the track, or
any other car up to 100 behind the point (`0 < d < 100`).
**TooCloseToAnotherCar(bVector2 \*)** (0x00222ee8) is the same cars within
100 in the plane; nothing calls it.

**PickRoutePoint** (0x002230d0; the name is the port's) draws a number
under the last total. The route is the first whose running total passes
it, and the point is the draw less the routes before. It draws again
while the point is not Posted, up to 101 draws in all, and keeps the last.

**RandomPlayerCar** (0x002231f0) is a random player's car.
**PickRandomSkin** (0x00223228) is a random one of the type's skins, or 0
with none. **SwitchSkin** (0x00223278) puts a random skin on with
`Car::SwitchSkin` when it is not the one the car has. The ride's
`SkinNumber` is a signed byte (`lb`).

## Car::SwitchSkin

The teleporter's repaint needed three functions of CarRenderInfo.obj
([car-render-info.md](car-render-info.md)):

- `Car::SwitchSkin` (0x0011e588) sets the ride's skin byte, then calls
  CarRenderInfo's SwitchSkin and UpdateSkinTextures;
- `UpdateSkinTextures` (0x0011ff08) calls UpdateTextureInfo on the five
  entries SwitchSkin renames;
- `UpdateTextureInfo` (0x0011fed0) looks up an entry's texture again by
  its new name hash, the default standing in.

They are `car_switch_skin`, `carrenderinfo_update_skin_textures` and
`carrenderinfo_update_texture_info`, checked by `carrenderinfo_check.py`.

## In the port

`main.c` sets `world.h`'s four seams: the constructor, the destructor,
`PlaceNewCar` and `DoTimestep`. `worldstep.c` still
skips a NULL `PlaceNewCar`, so a build without the teleporter places no
traffic, as a NULL `AddCopCarToRace` places no cop.

**What a Quick Race gets.** Quick Race asks for `TrafficDensity` 0.33. That
is below 0.4, so `DoTimestep` never moves a car: the traffic stays where
`PlaceNewCar` put it, driving its routes. At placement the race is under
20 s old, so no car starts within 2000 of the start line. The first
Azahar runs found every traffic car placed and drawn, the nearest 198 to
222 m from the player. The player had not reached any of them by the end
of the run.

## The checker

`tools/traffictele_check.py`.

**As shipped:**

- every TrafficTeleporter function but DoSnapshot, called directly
  (`racesnap_check` has DoSnapshot);
- GuessTargetDestinations, both under TryToTeleportCar and alone over
  route networks with signposts;
- under them: `CompareDistances`, `bATan`, `TrackRoutePoint::GetSignpost`,
  and Signpost's `GetNewRoute` and `GetNewRoutePoint`.

**Stood in on both sides**, each one printing its call, so both sides must
ask the same questions in the same order:

- `World::Random`, int and float, from the script's queue and then a
  shared generator;
- `GetDATToClosestPlayer` and `GetDistanceToClosestPlayer`;
- `GetNearestRoutePoint`;
- `Car::IsPoofed`, and the type's skin count and skin number;
- Car's constructor, with a test controller whose slot 40 prints,
  `SetMovementMode`, `SetControlMode`, `ResetToRoutePoint` and
  `SwitchSkin`;
- TrackPathCoordinate's constructor and destructor (silent) and
  `ResetPosition`;
- `bMalloc` and `__builtin_delete`.

**The no-race start line.** The console reads it through address 0, and
the model's address 0 reads 0. So the no-race cases keep their points 2000
or more from 0, where the two agree.

**Scenarios:**

- FillInTotals over missing and empty slots;
- the constructor, with SetThinkTime under it;
- the destructor with each flag;
- ForwardsOrBackwards;
- PickRoutePoint with unposted points, all 101 draws unposted, and only
  bit 15 counting;
- the skins;
- both visibility tests;
- TooCloseToAnotherCar: traffic either way, racers behind only, round the
  end of the track, the cars passed over, and two near;
- IsGoodPlace: the start line at each boundary, either side of 2000, and
  no race;
- GuessTargetDestinations over signs, stops, branches, a full ring, the
  71st path and the step guard's edge;
- PlaceNewCar: each failure in turn, a hundred tries, no points either
  way, and random cars;
- TryToTeleportCar: off the routes, behind, ahead, too close, round the
  end of the track, a sign along the way, an ulp past 250, and walking
  back;
- DoTimestep's early returns, the clock, the walk round, all in sight, a
  smaller table, each density's think time, and a run of steps.

7563 ops, 0 differ.

### The mutation pass

180 mutations: 178 caught, 2 equivalent.

| Mutation | Why it cannot show |
|----------|--------------------|
| good_swap | `CompareDistances(b, a)` is exactly `-CompareDistances(a, b)`, the wrap at half the track included, and the start line test takes its fabs. |
| branch_way_full | Full is only ever set by a push, and a pop always comes between a branch's pushes and the next branch, so it is 0 when the way on is pushed. |
