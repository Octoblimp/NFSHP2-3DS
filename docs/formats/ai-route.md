# NearestRoutePointInfo -- the AI's route helpers

    0x001c1660  GetNearestRoutePoint(NearestRoutePointInfo *, bVector2 *,
                                     RoutesToSearch, int, float)
    0x001c1808  GetNextRoutePoint(NearestRoutePointInfo *)
    0x001c1918  GetNextRoutePointAhead(NearestRoutePointInfo *)
    0x001c3268  NearestRoutePointInfo::IsValid

A NearestRoutePointInfo is a route and a point on it. It answers "where on
the route network is this?". These four functions live in the AI's utility
object, with the route planners, which are ported in `airouteplan.{c,h}` (below):
GuessTargetDestinations for the TrafficTeleporter
([traffic-teleporter.md](traffic-teleporter.md)), and ReturnToLastBranch,
FindRoutesToTarget, FindPointsToTarget and FindNearbySignpost for the
helicopter ([chopper.md](chopper.md)). Three other free functions from the
same object are in `drivetarget.c`.

The port is `3DS Files/source/airoute.{c,h}`. It is cross-checked by
`tools/airoute_check.py` against `tools/src/airoute_test.c`, with the image
itself running in mipsemu as the oracle. The image also runs everything
beneath the four functions: `TrackRoute::FindClosestPoint`, the bounding
box test, `GetDistanceAway`, `CompareDistances`, the signpost accessors and
the manager's constructor, list code and loader. So the checker also checks
`trackroute.c`'s search against the image, which `trackroute_check.py`'s
Python model cannot do.

Who calls what:

| Function | Call sites |
|----------|-----------|
| GetNearestRoutePoint | TrackedController::FindWhereIAm, tAICop::InitializeDriveTarget (2), tCopManager::InitRoadBlockStructures, InitSpeedTrapStructures, TrafficTeleporter::TryToTeleportCar, Chopper::FindChopperPointFromScratch, DroppedSpikes::MakeSpikeBelt |
| GetNextRoutePointAhead | RealController: Think, RouteDeltaPredict, CalculateLateralPostionAndVelocityWRTDrivingLine (2) |
| GetNextRoutePoint | GetNextRoutePointAhead (3), tAICop::UpdateDriveTarget (2), tCopManager::EndPullover, Chopper (3) |
| IsValid | RaceCoordinator::InitCars, RealController::CalculateLateral... (3) |

## The record, 8 bytes

| Off | Field |
|----:|-------|
| 0 | Route |
| 4 | Point |

## A point's index

Nothing here keeps a point's index. Every function works it out from the
pointer, the way the compiler divides by 112:

    idx = (int32)((Point - Route - 1064) * 0xb6db6db7) >> 4

112 is 16 * 7, and 0xb6db6db7 is the inverse of 7 mod 2^32. The result is
exact for a point in the route's own table. For any other pointer it is
garbage: a point from a different route, a point four bytes out of step, or
the route itself. The garbage only depends on the byte distance, so the
port gets the same garbage whenever the bytes are laid out as on the disc.
A step then stores `table + (idx + 1) * 112`, which can point anywhere, and
nothing reads through it until the next call.

**IsValid** (0x001c3268) needs both pointers set. The route's number is
loaded with `lh` and tested with `sltiu v0,v0,70`, so a negative number
fails too. The point's index must be in [0, NumPoints).

## GetNearestRoutePoint

It walks one of TrackRouteManager's two lists: the racing routes for
ALL_RACING_ROUTES (0), the traffic routes for anything else.

- ALL_TRAFFIC_ROUTES (1) keeps every traffic route.
- Any other value keeps only the traffic routes running one way. A route
  numbered below 60 runs with the track. "Forward" means `TrackDirection
  == 0`, and ONCOMING_TRAFFIC_ROUTES (3) flips it. So 2, 4, 7 and -1 all
  mean FORWARD_TRAFFIC_ROUTES.

The image passes `which` as a word, and it only ever tests it for
equality. The port's `RoutesToSearch` is an `int32_t` with four defines,
not an enum. GCC would make an enum with no negative values unsigned, and
then a test written as a range would still pass at -1. Two mutations
survived for exactly that reason until the type changed.

`TrackDirection` is `TheRaceParameters+12` (0x0031252c), an
`eTrackDirection`: FORWARD 0, BACKWARD 1. `InitWithDefaults` sets it to
FORWARD. It sits in `.data`, and it is 0 on the disc, which the port's
zero initialiser matches. It is in `race.h` now.

For each route it calls `FindClosestPoint(route, pos, best, flags,
distanceAround)`, where `best` is the best distance so far. It starts at
999999 (gp-28896, 0x497423f0). With `TRFIND_BY_TRACK_DISTANCE` (0x20) in
`flags`, the route's point is measured with GetDistanceAway, and otherwise
with the plane distance. The search keeps a result if `d < best`, so the
first of two equal routes wins. It fills in Point and then Route, and
returns 1. If nothing is found, it returns 0 and leaves `info` alone.
FindWhereIAm passes 34, which is `TRFIND_POSTED_ONLY |
TRFIND_BY_TRACK_DISTANCE`. Flags 8 and 16 are the manager's own; a single
route's search never reads them.

Two consequences of what is underneath:

- **The `d < best` test is always true.** FindClosestPoint only returns a
  point nearer than the radius it is handed, and it measures exactly as
  the search does. Passing a fixed radius instead would not change the
  answer either, because the test would then throw away exactly what the
  running radius would have. Each half makes the other redundant; the
  checker lists both as equivalent.
- **The walk is not exhaustive.** After each point, FindClosestPoint skips
  `dist / 24 - 2` more. So a query 999999 units from a route sees only that
  route's first point. At x = 999999 the search finds nothing, even though
  the route's last point is 999799 away and inside the radius.

## GetNextRoutePoint

A point has a signpost when the low byte of its flag word is not 0xff. The
sign is read as a word: bits 8-10 are its Sign and bit 11 is Backwards
(byte 1, bits 0-3). If the sign is not Backwards and its Sign is 0 or 2,
`info` goes down the branch: Route becomes `GetNewRoute` and Point becomes
`GetNewRoutePoint`. Every other sign, and every point without one, steps:
the next point when `idx + 1 < NumPoints`, otherwise NULL. The route is
kept either way. The step counts on `info->Route`, not on the route the
point belongs to.

The point must not be NULL. The image would read the byte at 44 of address
0 and find a sign there.

## GetNextRoutePointAhead

1. With no point, or no route, it does nothing.
2. One step.
3. Only if the **start** point has a signpost -- the step may have gone down
   a branch and landed behind -- it looks further. A plain start whose next
   point is behind it gets just the one step.
4. If the new point is NULL, it stops.
5. `d = (p - start) . start.Direction`. If `!(d < 0)` it stops, so +0 and
   -0 both stop. It is the start's direction, not the new point's.
6. A second step. The image reads the new point without testing it, so
   off the end of a route it reads address 0. The port stops there.
7. If the new point is within 8 of the **start** (`c.lt.s`, so exactly 8
   is not), a third step.

## GuessTargetDestinations

    0x001cbb70  GuessTargetDestinations(NearestRoutePointInfo *, unsigned,
                                        TrackRoute *, TrackRoutePoint *,
                                        float, int)

It walks the route network from a point, forwards or back, and returns up
to `count` points `dist` on, in `out[0 ..]`. The TrafficTeleporter asks it
for one point 250 on, then 50 on from each. The port is
`airouteplan.{c,h}`, checked by `traffictele_check.py`
([traffic-teleporter.md](traffic-teleporter.md)), which runs it both under
TryToTeleportCar and alone.

**The walk.** Each point walked takes its Length off the distance left.
Walking back, the start's Length is added first. A point counts once the
distance left goes below 0. It is written out, and when that makes
`count` the walk returns. Otherwise that path is done.

A point with a signpost that applies stops the plain step. A Backwards
sign applies only walking back, and any other sign only walking
forwards. What happens depends on the sign:

| Sign | |
|-----:|---|
| 3, stop | The distance left is -1, so this point counts next time round, even with no Length. |
| 2, always take | The walk goes down the sign's route to its point. |
| 0, faster | The walk splits. The way on and the branch both go at the front of the ring, the branch last, so it comes off first. |
| 1, 4 .. 7 | The walk splits. The way on goes at the front, the branch at the back. |

Down a sign, the distance left at the new point is the old one, plus the
signed point's Length, less how far the new point lies along the signed
point's direction.

A point with its Posted bit clear ends the path, and so does either end of
the route.

**The ring.** The paths still to walk are a ring of 20 on the image's
stack, each a route, a point and the distance left (12 bytes, copied with
`ldl`/`ldr`). A push that fills it sets Full, and while Full nothing more
goes on: what would have is dropped. When a path ends, the next one comes
off the front. With the ring empty, the walk returns what it found.

**The two guards.** Each give 0, whatever was found by then:

- the 71st path coming off the ring;
- a step past 0x11800.

With no route or no point, it returns 0 at once.

## The helicopter's planners

    0x001cc130  ReturnToLastBranch(info, branches, routes)
    0x001cc270  FindRoutesToTarget(start, target route, routes, fwd, heli)
    0x001cc5d0  FindPointsToTarget(start, target, out, count, fwd, heli)
    0x001cc838  FindNearbySignpost(info, fwd)

The helicopter (`chopper.c`) follows these. The port is `airouteplan.{c,h}`.
It is checked by `tools/routeplan_check.py` against
`tools/src/routeplan_test.c` (below), with the image as the model.

**The deques.** Each is a `Deque<T, 20>`:

| deque | item | size | Front | Back | Full |
|---|---|---:|---:|---:|---:|
| routes taken | `TrackRoute *` | 92 | 80 | 84 | 88 |
| branches not taken | NearestRoutePointInfo | 172 | 160 | 164 | 168 |

The deque is empty when Front == Back with Full clear.

- PushBack writes at Back, steps Back on (wrapping 20 to 0) and sets Full
  when it meets Front.
- PushFront steps Front back first (0 to 19), sets Full the same way, then
  writes.
- Taking off either end clears Full.

Every caller skips a push when Full, so what would have gone on is
dropped.

**FindNearbySignpost** steps the point along its route until one has a
signpost. It returns 1 plus the steps taken, or 0 when it runs off the
route (the point is then NULL).

**ReturnToLastBranch** returns 0 with no branch left. Otherwise the newest
branch (at Front) comes off into `info`. Routes come off the back of the
routes deque until the branch's route is the last, and it returns 1.

**FindRoutesToTarget** searches depth first. The start's route goes on,
and if it is the target the answer is 1 at once. Then it walks. At a
signpost that applies (a Backwards sign walking back, any other walking
forwards):

| the sign names | |
|---|---|
| the target | The target goes on. 1. |
| a route not taken | The route goes on, and the walk goes down the sign. Unless the sign is 2, the point after the sign is kept as a branch, at the front. |
| a route taken | A sign 2 or 3 sends the walk back to the last branch, as ReturnToLastBranch does. Any other is passed by. |

Then it steps. With `heli`, a point marked TRP_NO_HELISHEET (0x4000)
also sends the walk back to the last branch. The branch's point is looked
at next as it is, without a step. Running off a route, or out of
branches, empties the routes (Back = Front, Full clear) and the answer
is 0.

**FindPointsToTarget** lists up to `count` points from the start towards
the target, into `out[0 ..]`, and returns how many.

- When the start is the target, `out` gets the target alone, and it
  returns 1.
- With `heli`, a start marked TRP_NO_HELISHEET returns 0.

Each point stepped onto is listed. The list ends:

- at the target;
- at the end of a route;
- at a sign 3;
- at a TRP_NO_HELISHEET point, with `heli`;
- once `count` are listed (one at least).

A sign 2 is taken, without a step. At any other sign that applies,
FindRoutesToTarget fills one routes deque that serves the whole call. The
sign is taken only when it names the route at the deque's front, and an
empty deque ends the list. That front is the first route ever put on,
which is the start's. So in practice these signs are passed by. The port
keeps this.

**What the port does not follow.** None of these happen on a shipped
track. The checker gives the model the port's answer with a hook at each.

- **ReturnToLastBranch with the routes run out.** The routes can empty
  before the branch's route turns up. The image then keeps comparing the
  last route it took off (or, with none, a stale stack word) for ever.
  The port returns 0.
- **A branch kept at the end of a route** has no point. The image steps
  from address 0, and with `heli` reads it. The port takes it as running
  off the route.
- **Looking through a full routes deque** (or one whose Back is 0) for a
  route not there. The image stops only when it lands on Back after a
  step, before the wrap, so it goes round for ever. The port stops after
  twenty looks.
- **A full routes deque** takes no more, so the walk can go round a loop
  of routes for ever. The port gives up after 0x11800 steps
  (`ROUTEPLAN_MAX_WALK`), as on running off a route.

## What the port does not follow

None of these happen on a shipped track. The checker hooks each one in the
model, and a scenario that reaches one fails outright instead of being
compared.

- **GetNewRoutePoint on an empty route slot.** The image tests its route
  with `bltz` on a byte loaded by `lbu`, which can never be negative, so
  it has no NULL test at all. An empty slot gives `0 + 1064 + 112 *
  NewPoint`. The port returns NULL. `trackroute_check.py`'s Python model
  had the port's NULL test too, which is why this went unnoticed until
  the image was the model. All 56 of track 12's signs resolve.
- **A sign naming a route past slot 99.** The image reads past the
  manager's table. The port indexes past its array.
- **The second step of GetNextRoutePointAhead running off a route.** The
  image computes a distance to address 0's contents and, if that is under
  8, steps from a NULL point. The checker allows this where the start is
  at least 8 from the origin, since memory at 0 is zero in mipsemu. Both
  sides then stop with the point NULL.
- **GetNextRoutePoint with a NULL point or route.** The image reads through
  it; the port would crash.

## Checking it

    python tools/airoute_check.py
    python tools/airoute_check.py --mutate

14,738 ops and 7,224 lines, 0 differ. Of 91 mutations, 86 are caught and 5
are equivalent, each with its reason in the script: the two halves of
`d < best`, `<=` for `<` there, and testing only the route for "found",
which is written with the point. The fifth is IsValid's NULL-point test.
Without it, a NULL point's index is garbage that depends on where the
host put the arena, and at a 64-bit host's addresses it never lands in
range. Four mutations survived the first pass, for three reasons:

- **`RoutesToSearch` was an unsigned enum.** Two range tests that should
  have failed at -1 passed.
- **A step below a route's table** was only right on a 64-bit host if the
  offset was sign-extended. Nothing read through the result until three
  steps in a row were added.
- **The direction's starting value** was never seen, because every
  scenario set it before searching.

A full pass is long enough to hit the build flake that
`hostbuild.BuildEnvironmentError` describes. The tally above comes from
two runs: one stopped on the last mutant, which then built and was caught
alone. If a pass stops, rerun what is left with `--only`.

All the routes live in one arena, laid out the same way on both sides:
back to back, each cut off after its last point, the way the loader finds
them. So foreign and misaligned points give the same garbage indices on
both sides. The image strings its routes through their list words; the
port keeps arrays, and nothing prints those words. Both sides have a
256-entry sign table, so any sign byte reads inside it. The entries a
scenario does not set are sign 1, which does not branch. A point's driving
lines are 0xff, so a point read out of step usually finds no signpost.

The scenarios cover:

- IsValid at route numbers 69, 70, -1, -32768 and 32767, at the index
  boundaries, and with foreign and misaligned points;
- GetNextRoutePoint over every Sign value, Backwards, the other three flag
  bits, the last point, and every flag word combination around the sign
  byte; the route it is handed against the point's own; and three steps
  in a row from a point below the route's table. The index is then
  negative, and on a 64-bit host the step only lands where the image's
  does if the offset is sign-extended before it is added;
- GetNextRoutePointAhead at each of its three steps and every boundary
  between them: exactly 8 and just under, a dot of +0 and -0 and a hair
  below, the start's direction against the new point's, branches at the
  second and third steps, and each way off the end;
- the search over both lists, all four RoutesToSearch and three values
  beyond them, the direction before anything sets it, both directions,
  the traffic numbering at 59, 60 and 61, a traffic-typed route numbered
  45, a route of Type 2 that is in no list, every flag bit, ties, the shrinking radius below 1 (where squaring would
  change the answer), track distance against plane distance at four track
  lengths, and the radius and bounding-box edges at 999999;
- track 12's own 17 routes and 56 signs, loaded by the loader: a step and
  an ahead from every one of its 2,535 points, IsValid on and across routes,
  and the search along every racing route with FindWhereIAm's flags.

### The helicopter's planners

    python tools/routeplan_check.py
    python tools/routeplan_check.py --mutate

`routeplan_check.py` runs the image's four planners in mipsemu against
`tools/src/routeplan_test.c`. Both sides build the same 24 routes and
256 signs. A point prints as its route and index, so a step to the
wrong place shows. The model gets the port's four answers (above) from
hooks: a step from no point returns no point, an empty routes deque ends
ReturnToLastBranch, the look stops at twenty, and the walk gives up
after 0x11800 steps.

The scenarios cover:

- FindNearbySignpost from every point of four routes, both ways;
- ReturnToLastBranch on full, empty and wrapped deques of both kinds;
- FindRoutesToTarget at every sign value, Backwards or not, at a target
  and at routes taken. It also runs back to branches from a sign and from
  a no-go point, from a branch kept at a route's end, and on fifteen
  starting deques: full, wrapped, with Back at 0, and with stale items;
- two routes that send the walk round for ever;
- a chain of 22 routes that fills both deques, so r20's branch is
  dropped;
- a walk whose target turns up on its 0x11800th step, one step either
  side, and one 1,020 steps on;
- FindPointsToTarget at every sign, count and target, a target whose
  route is not its point's, and a no-go start;
- 1,000 random networks of four routes.

The result is 81,092 ops, 100,285 lines and 0 differ. Of 98 mutations,
97 are caught and 1 is equivalent: dropping the look's emptiness test,
which no call reaches. Six survived the first pass. The branches deque
never filled with four routes, which is why there are 24. No walk ran
long enough to tell the guard's `>` from `>=`. No target had a route
other than its point's.
