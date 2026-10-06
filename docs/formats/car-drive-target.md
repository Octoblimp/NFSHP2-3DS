# DriveTarget

`DriveTarget.obj` exists this time — `.text 0x002086f8`, `0x24d0` long —
but it is not all DriveTarget. Seven `OBB` methods and the free function
`bDoublesBack` (0x00208fa0) are in the same run, which is why the object
measures 9424 bytes against a DriveTarget tally of 8636. The copy
constructor is emitted out of line at 0x001da210, inside
`CarCollisionDetect.obj`, and `_GLOBAL_$I$__11DriveTarget` (0x0020ab48) is
the static initialiser. Twenty-eight symbols: twenty-six methods in the
object, one constructor outside it, one init thunk.

The tenth slice of task 25, after
[CarState](car-state.md), [Engine](car-engine.md),
[CarTypeInfo](car-type-info.md), [CarDriver](car-driver.md),
[Steering](car-steering.md), [RigidBody](rigid-body.md),
[Suspension](car-suspension.md), [Wheel](car-wheel.md) and
[DriveTrain](car-drivetrain.md).

DriveTarget is the short list of points the AI is currently steering
through, together with the speed it wants at each one. It is 528 bytes and
it is embedded at offset 0 of every `CarDriver`, which is why the layout
had to be spelled out before CarDriver could be ported at all.

Ported to `3DS Files/source/drivetarget.{c,h}`. Cross-checked against
`tools/src/drivetarget_test.c` twice over: by `tools/drivetarget_check.py`,
a model written from the disassembly, and by
`tools/drivetarget_image_check.py`, which runs the same scenarios through
the shipped code in `tools/mipsemu.py`.

The port is **retail's** DriveTarget since step 11b-1, and the image check
runs SLES_507.31. Most of this page was written from the demo's listing,
and its addresses are the demo's; retail's class is the demo's with a byte
added, three methods added and two rebuilt on them. See
[Retail's DriveTarget](#retails-drivetarget) for what changed.

## Car is not a prerequisite, and that was checked rather than assumed

The task list had DriveTarget waiting on `Car`, on the strength of thirteen
of its twenty-six methods taking a `Car *`. They do, and it does not
matter: **every one of them reaches `Car` only through the `CarState`
embedded at byte 64**, which has been ported since the first slice of task
25.

`Car` is 2016 bytes and its `.mdebug` entry carries `State:/0263,512,8192`
— bit 512, so byte 64, 1024 bytes. Across `Clear`, `InterpolatePoint`,
`Resample`, `EstimateScore`, `CalculateMaxSpeed`, the two acceleration
fillers and the four `AddPointToTarget` overloads, the only Car offsets
touched are 64 (passed straight on as a `CarState *`), 96
(`State.Position`) and 112 (`State.Velocity`). `Dump` adds one more, the
`DriverNumber` at 10, and `BlendWithCurrentAcceleration` adds `pPlayer` at
24 — a pointer it only tests against zero.

The three free functions in the call graph are the same story:
`IsPointAheadOfCar` (0x001c0e30) reads 96 and 112 and nothing else,
`CalculateLookAheadDistance` (0x001c0c20) is
`max(State.VelocityMagnitude * 2, 20)` in six instructions, and
`GetMaxLateralAcceleration(Car *)` (0x00209f30) never reads its argument at
all — it is `lui at,0x41f0 ; mtc1 at,$f0 ; jr ra`, a constant 30.0f.

So `drivetarget.h` carries a three-field `Car` stand-in guarded by
`#ifndef CAR_H`. When the real `car.h` arrives the block disappears and
the three fields keep their names and their offsets.

## The record

528 bytes. No vtable: the constructor only memsets and calls `Clear`, so
unlike `CarDriver` there is no pointer hiding in the tail.

| Off | Field | Type |
|----:|-------|------|
| 0 | NumPoints | `int8_t` |
| 1 | *(pad)* | 15 bytes, so Points is 16-aligned |
| 16 | Points | `bVector3[20]` |
| 336 | CalculatedSpeed | `float[20]` |
| 416 | Route | `int8_t[20]` |
| 436 | RoutePointNumber | `int16_t[20]` |
| 476 | DrivingLine | `int8_t[20]` |
| 496 | TType | `int32_t`, an enum |
| 500 | WhichPointIPicked | `int8_t` |
| 501 | *(pad)* | 3 bytes |
| 504 | WhichPointIPickedCalculationTime | `int32_t` |
| 508 | WhichPointIPickedTime | `int32_t` |
| 512 | Length | `float` |
| 516 | LastPointToScore | `int8_t`, retail's; -1 is every corner |
| 517 | *(pad)* | 11 bytes, 516 rounded up to 33 × 16 |

The `.mdebug` entry gives the offsets and not the element types, so those
came from the instructions that index each array:

```
Points[i]            sll v0,a1,4                    0x00208a0c
                     addiu v0,v0,16                 0x00208a14
                     addu v0,s0,v0                  0x00208a1c
Route[i]             lb  a2,416(base + i)           0x00208af0
RoutePointNumber[i]  lh  a3,436(base + i*2)         0x00208af8
DrivingLine[i]       lb  t0,476(base + i)           0x00208ae8
NumPoints            lb  v1,0(s0)                   0x002089a4
Length               lwc1 $f0,512(s0)               0x002091bc
WhichPointIPicked... lw  v0,504(s1)                 0x00209218
```

The element count is 20 everywhere, and the constructor agrees: it opens
with a loop counted from 19 down to -1 whose body the compiler optimised
away to nops, leaving the trip count as the only trace of twenty
default-constructed members.

**This record needs no slack term.** Every other class in task 25 has a
layout assert carrying `sizeof(void *) - 4` because the PS2's pointers are
four bytes and the host's may be eight. DriveTarget has no pointers in it,
so the assert checks all eleven offsets and the size on both hosts as
written. The `DrivingLocation` stand-in beside it does have two, and its
offsets do widen — which is why the transcript prints them.

## The constants

The ten pooled floats are `DriveTarget.obj`'s own `.lit4`, 0x00321fa8 and
0x28 long, so they are anonymous. `_gp` is 0x00328bf0.

| Addr | gp offset | Value | Read by |
|------|-----------|-------|---------|
| 0x00321fa8 | -27720 | 0.001 | `Clear`, the speed floor |
| 0x00321fac | -27716 | 0.342 | `GetFirstPoint`, cos 70° |
| 0x00321fb0 | -27712 | 0.4 | `EstimateScore` |
| 0x00321fb4 | -27708 | 0.4 | `EstimateScore` |
| 0x00321fb8 | -27704 | 0.4 | `EstimateScore` |
| 0x00321fbc | -27700 | 0.001 | `CalculateMaxSpeed` |
| 0x00321fc0 | -27696 | 0.001 | `CalculateTime` |
| 0x00321fc4 | -27692 | 9999999.0 | `CalculateTime`, "no time" |
| 0x00321fc8 | -27688 | 0.1 | the integration step |
| 0x00321fcc | -27684 | 1.3333333 | 1 / 0.75, the blend scale |

The pool is **read slot by slot** by the checker, not once per distinct
value. The compiler pooled 0.001 three times and 0.4 three times, once per
use site, and the header collapses each family into one macro; reading them
apart is what makes that collapse a checked claim rather than an
assumption.

Four more are inline `lui at,...` literals rather than pooled ones: the
30.0f speed gate in `GetFirstPoint`, the 30.0f grip limit
`GetMaxLateralAcceleration` returns, and 0.75f twice — once as the
acceleration-dominates ratio in `FillWithCurrentAcceleration` and once as
the blend window in `BlendWithCurrentAcceleration`.

Six globals are named in the map file:

```
0x00323a50  AIDriverSecondsToLookAhead          2.0f
0x00323a54  AIDriverDefaultLookAhead           20.0f
0x00324a60  DriveTargetMinDistanceToPoint       4.0f
0x00325354  DriveTargetMinDistanceToPointSquared  .sbss
0x003235d0  CameraFollowDefaultCar                 1
0x003235d4  CameraFollowThisCarInstead            -1
```

The squared distance is in `.sbss` — it has no bytes in the file at all —
because `_GLOBAL_$I$__11DriveTarget` computes it at start-up. Four
instructions:

```
0020ab48  lwc1   $f0,-16784(gp)
0020ab4c  mul.s  $f0,$f0,$f0
0020ab50  jr     ra
0020ab54  swc1   $f0,-14492(gp)
```

`drivetarget_static_init()` is that, and the checker runs it rather than
folding the answer, so the four instructions are modelled and not assumed.
Both sides print 16 for the square and neither of them was told to.

## GetAngle reads off the front of the array

0x002087b8, and the shortest method with a real finding in it.

```
002087bc  addiu  v0,zero,-1
002087c0  sd     ra,16(sp)
002087c4  slt    v0,v0,a1
002087c8  movz   a1,zero,v0        i = 0 when i <= -1
002087cc  lb     v1,0(a0)
002087d0  addiu  v1,v1,-2
002087d4  slt    v0,v1,a1
002087d8  movn   a1,v1,v0          i = NumPoints - 2 when that is smaller
002087dc  sll    a2,a1,4
002087e0  move   a1,a2
002087e4  addiu  a2,a2,16
002087e8  addiu  a1,a1,32
002087ec  addu   a2,a0,a2
```

The index is clamped **up** from -1 to 0 and then **down** to
`NumPoints - 2`, in that order, and never back up again. `sll ; addiu 16 ;
addu` is a byte offset from the top of the record rather than an array
subscript, so a negative result is an address and not a trap.

Two point counts leave it negative, and they are not the same case:

* **One point** clamps to -1. `Points[-1]` is the record's own first
  sixteen bytes — `NumPoints` and its padding — which a constructed
  record has zeroed, so it reads as (denormal, 0, 0, 0) and the angle
  comes out of `Points[0]` alone. Out of bounds for the array, inside the
  object, and deterministic.
* **No points** clamps to -2, and that address is sixteen bytes *before
  the record*. Whatever the linker or the caller put there is what gets
  read.

Both are genuine out-of-bounds reads in the shipped game, the same flavour
as `Table::GetValue`'s. The port spells the addressing as a byte offset
for exactly this reason — written as `t->Points[i]` the compiler would be
entitled to assume `i >= 0`.

`ga one` in the transcript is the first case, on a record
`drivetarget_init` built, so both sides can state the answer. The
transcript stops there: the empty case reads memory neither side owns, so
there is no answer for them to agree on and asking for one would diff the
allocator rather than the method.

## Assignment and copy-construction disagree about the padding

Two ways to copy a DriveTarget, and they are not the same operation.

`operator=` (0x00208788) is one `bMemCpy` of 528 bytes and then
`move v0,s0`. The size is an immediate, so every byte goes across
regardless of how many points are in use — the three padding runs
included.

The copy constructor (0x001da210, out of line in `CarCollisionDetect.obj`)
is member-wise: five twenty-iteration loops and then eight scalar stores.
No memcpy. **The three pad runs keep whatever the destination already
held.**

The `ct` scenario dirties both destinations with 0x3C, dirties the source's
pads with three recognisable patterns, and prints all three runs from both
copies. The asymmetry is a line in the transcript rather than a comment.

## A stack bVector3 whose w is never written

Five places build a `bVector3` on the stack, fill x, y and z, and hand it
to something that copies all sixteen bytes with `lqc2`/`sqc2`:
`SetPoint`'s 2D overload, `AddPointToTarget`'s 2D overload,
`AddPointToTarget`'s 2D `DrivingLocation` overload,
`StraightLinePredict`'s heading under 1 m/s, and the blended point in
`BlendWithCurrentAcceleration`. In each, `Points[i].pad` ends up holding
whatever the stack held. (`StraightLinePredict`'s other arm is not one of
them: its heading is a whole quadword loaded from the velocity, and all
four lanes of it are written. See below.)

**This is the one place the port does not follow the image, and it is
deliberate.** Reading an uninitialised automatic is undefined behaviour in
C, so those temporaries get a `pad` of 0.0f. Nothing on the disc can
depend on the value either — it is a different number on every call — so
the divergence costs a behaviour no caller could have had. Every site is
marked `STACK-W` in `drivetarget.c`.

The image check can tell these lanes from real values without being told
where they are. It runs the image twice, over two different stack poisons,
and a lane that changes with the poison is one of these. Across the
transcript it finds 160 such lanes, and every one of them is at one of the
five sites.

## Clear, and what survives a frame

0x00208980, 528 bytes, and the method the whole class exists around: at the
top of every AI frame the target is cut back to the part of the path still
in front of the car.

Four early exits, and all four converge on the same two stores at
0x00208b68 — `sw zero,508` then `sw zero,504`, the two time stamps — so
the epilogue is shared and the order is fixed.

1. `NumPoints == 0`: zero the length and leave.
2. `|speed| <= 0.001` **or** `speed < 0`: empty the list. Standing still or
   reversing means there is no path worth keeping.
3. Every point behind the car: empty the list. The test is
   `0 < Velocity · (Points[i] - Position)`, against the **raw** velocity
   rather than a normalised one, and it is strict.
4. Otherwise: `ShiftLeft` the dead points off the front, interpolate a
   fresh point `speed` metres along what is left, and keep only up to it.

The fourth case splits again on what `InterpolatePoint` returned. A
return of -1 means the new point is on the first leg, so the whole target
collapses to that single point — and the route data is read out of the slot
`GetFirstPoint` chose **before** `NumPoints` is zeroed, which is why those
three loads sit above the `sb zero,0(s0)` at 0x00208b54 in the listing and
above the assignment in the port.

## InterpolatePoint

0x00208b98. Walks the path from the car through the points accumulating
distance, and writes the point `dist` along it.

The cumulative array is **indexed by point number rather than packed**, so
entries below `first` are never written and never read. One point is a
special case that strikes out towards it and stops at `dist` whether or not
that overshoots; no points returns -1 without writing the output at all.

The return value is the index of the point *before* the one it landed on:
-1 when it landed on the first segment, `NumPoints - 1` when it ran off the
end and had to extrapolate. `Clear` reads that distinction and nothing
else.

`DummyFunction` (0x00208b90) is called from inside the walk and is a bare
`jr ra` in the shipped image — a debug hook that survived as a call site.

## Resample, and a Length that stops being a length

0x00209358. Respaces the points evenly along the path they already
describe: same shape, same endpoints, uniform spacing. The `Car *` is
taken and never read.

Two details are worth having written down.

**The last segment is a copy of the one before it.** `seg[n-1] = seg[n-2]`
and `len[n-1] = len[n-2]`, so the walk always has somewhere to go if it
reaches the end of the list.

**Length becomes the distance of the last point emitted, not the path
length it started from.** The walk keeps two accumulators a step apart —
`next` is where the point just emitted sits, `emitted` is where the next
one will — and it is `next` that is stored. On a path that divides evenly
the two agree; where they do not, `Length` comes out one step short of the
path it describes.

The control flow is four tests around two nested loops with three exits,
and the port keeps the `goto`s rather than restructuring, because the two
`goto done` sites and the two fall-through sites reach the same code by
different paths and flattening them changes which test runs last.

## EstimateScore

0x002096b0, 1596 bytes, the big one. It answers "how fast could this car
actually get through this path", or -1 if some corner on it cannot be taken
at all.

Three phases. First every point from `first` onward gets the car's current
speed written into `CalculatedSpeed` and its leg length measured — from the
car for the first point, from the previous point after that. Then two
nested walks ask `CalculateMaxSpeed` whether each corner fits, clamping
`CalculatedSpeed` down as they go. Finally a trapezoid sum of speed against
distance, divided by the distance: the mean speed weighted by how long the
car spends at it.

**The second walk measures from a point that does not move.** The inner
loop runs `nxt` forward while measuring back to `Points[outer - 1]`, which
stays put, so the legs get *longer* rather than being consecutive. That is
what makes the 0.4-second skip-ahead threshold mean anything: the walk is
asking how far ahead the car gets within a fixed time, not how long each
individual segment takes.

A single point is scored off the car's own speed and bails before any of
the corner tests, which is also the only path where `dist[]` is read at an
index the fill loop did not write. The image leaves that stack array
uninitialised; the port zeroes it, and the divergence is noted here because
it is undefined behaviour in C rather than a wrong number — a stale
`WhichPointIPicked` past `NumPoints` is the only way to reach it, and no
target the AI built can be in that state.

## CalculateMaxSpeed, and a magnitude nobody reads

0x00209cf0. Given three consecutive points, an entry speed and a proposed
exit speed, it decides whether the corner between them can be taken.

Two velocity vectors, the acceleration between them, the component of that
acceleration perpendicular to the first, and the question of whether its
magnitude fits inside 30 m/s². Three ways to answer yes without asking:
a speed inside the epsilon, a distance inside the epsilon (which also pins
the output to the entry speed), and a time inside the epsilon.

**The reciprocal is taken once and multiplied twice.** `1.0f / time` then
two `mul.s`, which is not the same as two divides once the rounding is
counted.

**The parallel magnitude is computed and never used.** Two multiplies, an
add and a `sqrt.s` on the component along the first velocity, dropped on
the floor. Dead in the shipped image; kept in the port because the image
has it, and argued in the checker's `EQUIVALENT` list rather than quietly
deleted.

## Retail's DriveTarget

Retail's `DriveTarget.obj` is 0x0021b918..0x0021dbc0, and the copy
constructor is at 0x001e7930. Diffed method by method against the demo's,
most of it moved CarState's fields (ForwardSpeed to 896,
VelocityMagnitude to 900, MatrixValid to 1024) and nothing else. Five
things are new.

**A byte at 516, `LastPointToScore`.** It was the demo's padding. `Clear`'s
shared tail (0x0021bd98) is the demo's two stamp stores with
`sb -1,516` between them, the copy constructor gains a ninth scalar copy
after `Length`, and `DrivingChoice::BuildDriveTargetAroundCar` (0x00243e7c) sets it to
`NumPoints - 1` once it has built a target. Assignment copies it with the
rest of the 528 bytes, as before.

**An accessor, 0x0021bdc8.** `EstimateScore`'s last corner:
`NumPoints - 2` while the byte is -1, the byte less one otherwise, both
narrowed through `sll 24 ; sra 24`. So a byte of -128 is 127, not -129.

**CalculateMaxSpeed split in two.** The demo's function from its third test
on is now its own method, 0x0021d130, which takes the two velocities
ready-made. What is left at 0x0021cfe8 is the two early answers (speed,
then distance), the two normalises, and a call. The new half has its own
pool slot for its epsilon, the same 0.001.

**A first corner from the car, 0x0021cf38.** v1 is `State.Velocity` as it
stands, not normalised; v2 aims from the car's position at the point, at
the speed wanted there; the distance is `factor * |ForwardSpeed|` and the
entry speed is `VelocityMagnitude`. It has neither of CalculateMaxSpeed's
early answers.

**EstimateScore rebuilt on them, 0x0021c920.** The fill loop and the
trapezoid sum are the demo's. The two walks are not:

1. Pass one skips forward as before, and stops on `s0`. If `s0 + 1 <
   NumPoints`, the first corner is the from-car question about
   `Points[s0]` with a factor of 0.5 (an inline `lui 0x3f00`): half a
   second of the car's forward speed, where the demo asked
   `CalculateMaxSpeed` from the car's position through `Points[s0]` to the
   next point.
2. The accessor's cut is read **before** the failure is tested, and `s0`
   is stepped past the first corner. A cut below `s0` ends the walk there.
3. Pass two is the demo's skip-ahead, but bounded by the cut, not by
   `NumPoints`: a walk that runs past the cut stops the pass without
   asking and without failing it. The corner it asks about is
   `Points[outer - 1]`, `Points[s0]`, `Points[s0 + 1]`.

So a target the AI built is scored up to its second-last point, as the
demo did, and one `Clear` left scores every corner, as -1 says.

**A car standing still divides by zero twice.** The from-car corner has no
early answers, so at rest it asks `bNormalize2To` for a length of zero (the
speed wanted at the point is the car's, 0) and then projects the
acceleration on a zero velocity, 0/0. Both are the EE's FLT_MAX: the
normalise's quotients come out zero, the projection's products with v1's
zeroes are zeroes, the lateral part is the whole acceleration, and the
corner fits. IEEE's infinity and NaN would refuse it, and the target would
score -1 for every car at rest. Both divides are `ee_div` in the port
(`drivetarget_calculate_max_speed_v`'s projection and `bNormalize2To`'s
first divide), and the image check lists exactly those two sites,
0x0021d204 and 0x00258914, as the divides that took the EE's path.

## GetFirstPoint

0x002091f0. Which point the car should be steering at, cached for the
frame in `WhichPointIPickedCalculationTime` against `WorldTimer`, so the
second call inside a frame is four instructions.

The first point that is both within 0.342 of straight ahead — cos 70° —
and further away than `DriveTargetMinDistanceToPoint` wins; the fallback is
the last point. Above 30 m/s the threshold drops to zero and anything not
behind the car will do. The test is strict, so exactly 30 is not "fast".

**The cone test uses the normalised delta and the distance test uses the
raw one**, which is still sitting on the stack from before the normalise.

**The empty arm clears the stamp instead of setting it.** The cache is
`WhichPointIPickedCalculationTime` at 504 tested against `WorldTimer`, and
the normal exit sets it:

```
00209228  blezl  v0,0x00209328
0020922c  sb     zero,500(s1)      ... delay slot, taken arm only
   ...
00209318  sb     s4,500(s1)        the answer
0020931c  lw     v0,-20224(gp)     WorldTimer
00209320  b      0x0020932c
00209324  sw     v0,504(s1)        stamp = WorldTimer
00209328  sw     zero,504(s1)      empty arm: stamp = 0
```

The `blezl` is branch-likely, so the `WhichPointIPicked = 0` in its delay
slot belongs to the empty arm alone — and that arm falls into a `sw zero`
rather than the `sw v0`. So an empty target re-answers on every call
inside the same frame, where a full one answers once. The one exception is
a `WorldTimer` of 0, where a zeroed stamp reads as a hit. Both are in the
transcript and neither is a transcription slip.

## ShiftRight blanks three fields out of five

0x0020a478 and 0x0020a5a8. `ShiftRight` opens `n` slots at the front and
blanks them; `ShiftLeft` drops the first `n` and optionally recomputes the
length.

The blank is partial. The three stores are `sw zero,24`, `sw zero,16` and
`sw zero,20` — z, x and y — plus `RoutePointNumber` to -1 and
`CalculatedSpeed` to zero. **`Route`, `DrivingLine` and `Points[i].pad`
keep whatever the slot held**, so a shifted-in slot carries the route
number of whatever used to be five places along. The transcript prints
more slots than `NumPoints` at every `sr` and `sl` call site for exactly
this reason.

The count arithmetic is `(uint8_t)NumPoints + n` stored as `int8_t`, and
then clamped to 20 if the result is not below 21 — the store happens in the
branch's delay slot and is overwritten on the clamped arm, so the
truncation is visible either way. `ShiftLeft` refuses `n == NumPoints`,
so the list can never be emptied that way.

## Dump prints nothing and is still observable

0x002095f8, 184 bytes. In the shipped image the print calls are gone; what
is left transforms every point into car space and drops the answer on the
floor.

It is ported anyway, for two reasons. The method count would be wrong
without it, and **the transform is observable**: `CarState::GetTransformMatrix`
builds `RelCoordMatrix` and sets `MatrixValid` the first time it is asked,
so that flag is the only way to see the guard from outside — and it is
enough to see it. The `du` scenario reads it after each of the guard's
four outcomes.

The guard itself is two tests, and the first one alone turns the whole
function off in the shipped build: `CameraFollowDefaultCar` is 1.

## Not ported

`DoSnapshot` (0x00208830) needs `ReplaySnapshot`, the same dependency
`CarState`, `Engine`, `CarDriver`, `Steering`, `RigidBody`, `Suspension`,
`Wheel` and `DriveTrain` are all still waiting on.

`operator new` and `operator delete` are the PS2 slot allocator.
`DriveTarget`'s destructor is the GNU v2 deleting form — `if (flag & 1)
operator delete(this);` and nothing else — so there is no destructor body
to port and the delete belongs to the caller.

## Three divergences, all written down

**`GetRouteAndRoutePoint` bounds `Route[i]` and the image does not.** The
listing is `bltz` and then a raw `lw` off `pTrackRoutes`: the negative case
is handled and nothing checks the top. `Route[i]` is an `int8_t`, so 100
to 127 would index past the hundred-entry table into whatever the linker
put next — which is not the same thing here as it was on the disc. The
port uses `trmgr_get_route`'s bound instead and answers 0 above 99. The
`p == NULL` test after the route point is computed can never fire, because
the pointer has just had 1064 added to it, and is kept because it is there.

**The `STACK-W` sites write 0.0f**, as above.

**`StraightLinePredict` divides a zero velocity the IEEE way.** On the VU,
`vrsqrt` of a zero sum is FLT_MAX, the heading comes out zero, and the point
lands on the car. On the 3DS it is an infinity and then a NaN. The port uses
the plain divide anyway, because the input cannot arrive: the arm is taken
only at a `VelocityMagnitude` of at least 1, and both places that write that
field (`mellowmover.c` and `physicscar.c`) compute it from this same
`Velocity`. `eefpu.h`'s `ee_div` is kept for divides by zero that the game
actually takes, and this is not one of them. Retail's first corner from a
car at rest takes two, and those are `ee_div`s: see
[Retail's DriveTarget](#retails-drivetarget).

## FillWithCurrentAcceleration trusts a small acceleration, not a large one

    0020a074  mul.s  $f0,$f0,$f1        |Velocity| * 0.75
    0020a078  c.lt.s $f0,$f2            < |Acceleration| ?
    0020a080  bc1f   0x0020a098         no: integrate
    0020a088  jal    StraightLinePredict

The integration runs only while the acceleration stays at or under three
quarters of the speed. Past that, the target is one straight-line point.
The test is strict, so exactly three quarters integrates. A car with no
speed and no acceleration integrates too: every step lands on the car, the
zero-length legs pass AddPointToTarget's strict doubling-back test, and the
twenty-point wall is what stops the loop.

**The port and this checker's model both had the test negated**, and they
agreed. `realcontroller_check.py` found it: it runs the image in mipsemu,
and a ComboPredict that fell through with no acceleration gave fifteen
points in the image and one in the port. Every `fi` fixture has been
re-derived so that it reaches the branch its comment names. `fi still` and
`fi ratio over` are new. With `fi still` in the transcript, the loop's own
twenty-point test is no longer redundant, so `fi-no-wall` is caught and its
equivalence argument is gone. Beneath the controller, `realcontroller_check`
runs the image's Clear, AddPointToTarget, StraightLinePredict, and both the
Fill and the Blend. `drivetarget_image_check` now runs the image of every
method, so the rest of the class is no longer checked against a model
alone.

## StraightLinePredict divides the pad too

The same shared misreading happened a second time, one lane over.
`drivetarget_image_check` found it the first time it ran.

    001c3394  lqc2       vf1,112(s0)          State.Velocity, all four lanes
    001c3398  vmul.xyz   vf03,vf01,vf01
    001c339c  vaddy.x    vf02,vf03,vf03y
    001c33a0  vaddz.x    vf02,vf02,vf03z      (x*x + y*y) + z*z
    001c33a4  vrsqrt     Q,vf00w,vf02x        1 / sqrt
    001c33ac  vaddq.x    vf02,vf00,Q
    001c33b8  vmulx.xyzw vf01,vf01,vf02x      all four lanes

Above 1 m/s the heading is not a call to `bNormalize3To`. It is an inline
VU0 normalise, and its last multiply is `.xyzw`: the lane `CarState` calls
`pad` comes out divided by the length along with the other three. The port
and the model both called `bNormalize3To` and then copied `Velocity.pad`
across unscaled. The port's own comment said that all four lanes went
through the normalise, and the code under it still did not scale the
fourth.

On `fn slp fast`, a velocity of (0.9, 1.2, 0.3, 0.7) looking 20 m ahead of a
pad of 8, the image gives 0.7 / 1.5297 * 20 + 8 = 17.1520863 and the port
gave 22. A sweep of 3000 random velocities matched on x, y and z every time
-- the inline normalise rounds exactly the way `bNormalize3To` does with a
target of 1 -- and differed on w every time. `realcontroller_check` runs
this image too, but prints only x, y and z, which is why it never saw it.

Both sides are fixed: the port now spells out the reciprocal and the four
multiplies. `fr-slp-pad-unscaled` is the old line as a mutation.
`fr-slp-divides` is the same normalise written as four divides, and it
needed a fixture of its own. `fn slp divide` uses a 3-4-5 velocity at
1.5 m/s, where 0.9 * (1 / 1.5) and 0.9 / 1.5 round apart; none of the
existing fixtures could tell them apart.

## Cross-check

`tools/drivetarget_check.py` models the class from the disassembly at
0x002086f8..0x0020a840, from the copy constructor at 0x001da210, and from
the three free functions at 0x001c0e30, 0x001c0c20 and 0x001c3338 — not
from the C. Since 11b-1 the parts retail changed are modelled from retail's
listing, 0x0021b918..0x0021dbc0 and 0x001e7930. Every constant comes out of `PS2 Files/NFSHP2.ELF` by address,
so a typo in the header shows as a diff rather than as two files agreeing
with each other.

`bMath` and `bVector` come from their own checkers' models rather than
being written again: `GetAngle` is one `bATan`, five methods normalise, and
re-deriving `bASin`'s twelve-octave table would duplicate a model that
already has its own transcript. `CarState` and `TrackRoute` are local
stand-ins, because DriveTarget touches five fields of one and two of the
other.

```
drivetarget_check        22 scenarios, 993 lines, 0 differ
drivetarget_image_check  22 scenarios, 993 lines, 160 pad lanes masked, 0 differ
```

### The image check

A model and a port are two readings of one listing, and twice now they
have shared a mistake: the Fill test above, and the StraightLinePredict pad.
`tools/drivetarget_image_check.py` takes the reading out of the oracle. It
imports `drivetarget_check`'s scenarios, fixtures and line formats
unchanged, and replaces every function the model writes from the listing
with a wrapper that:

- puts the Python records into `mipsemu` at the image's own offsets;
- calls the shipped function at its address; and
- reads the records back.

An import-time check fails if the model gains a function that no wrapper
replaces. Since 11b-1 the image is retail's, SLES_507.31. The coverage is
the whole of 0x0021b918..0x0021dbc0 except the two `DoSnapshot`s, plus the
copy constructor at 0x001e7930, the three free functions,
`DrivingLocation::IsClear` and the static initialiser.

What is not the image is what the C harness also supplies. `Car` is a zeroed
2304-byte block with the fields DriveTarget reads at retail's offsets. The
three routes are zeroed 115752-byte records, with `TheTrackRouteManager`'s
table rewritten before every call, and `pPlayer` is a dummy block that
Blend only tests against zero.

The `STACK-W` lanes are found by two runs over two stack poisons, as
described above. A lane that differs between the runs is allowed only in a
column the print wrapper marked as a pad. A difference anywhere else would
mean the image's control flow read garbage, and the run stops. The oracle
divides the EE's way (`RetailEmu(ieee=True, eediv=True)`), and lists the
divide sites that took the zero-divisor path. They are the two in
[Retail's DriveTarget](#retails-drivetarget), 0x0021d204 and 0x00258914,
both reached by the scenarios' cars at rest, and no others.

### Fixtures are spelled, not computed

Every fixture float is its own decimal literal on both sides. `0.32f +
0.01f` is 0.329999983, one ulp below the float nearest 0.33: the model
rounds a literal once and the C rounds the sum twice. Fixtures are not the
thing under test, so they are written so that the two sides cannot disagree
about them.

### What the mutation pass moved

```
python tools/drivetarget_check.py --mutate         # 288 mutations, 268 caught,
                                                   # 20 equivalent, 0 unexplained
python tools/drivetarget_image_check.py --mutate   # 288 mutations, 268 caught,
                                                   # 20 equivalent, 0 unexplained
```

The two checkers share one mutation list and one set of equivalence
arguments, and they agree on every verdict: nothing the model catches does
the image miss, and nothing argued equivalent against the model turns out
to be visible against the image. The two newest entries,
`fr-slp-pad-unscaled` and `fr-slp-divides`, are the StraightLinePredict pad
above.

**What 11b-1 moved.** Retail's DriveTarget brought 27 mutations of its
own: the byte at 516 (`cl-no-last-reset`, `cl-last-reset-zero`,
`cp-drops-last`, `h-last-unsigned`), the accessor (`lc-*`), the split
CalculateMaxSpeed (`ms-split-entry-is-exit`, `ms-v-short-no-write`), the
from-car corner (`fc-*`), the two EE divides (`ms-projection-ieee`,
`bv-normalize2-ieee`) and the rebuilt walks (`es-first-corner-*`,
`es-cut-*`, `es-pass2-*`). `es-nxt-is-cur` went with the demo's first
corner. Four old ones were respelled to the new source, and one,
`fr-isclear-tests-point`, now aims at `drivinglocation.h`, where `IsClear`
has lived since 11a. The full pass caught all of the new ones but two, and
both are argued in the checker: `fc-dist-no-abs` (the distance is only
`CalculateTime`'s numerator, so dropping the `fabsf` negates the time, its
inverse and the acceleration exactly, and the magnitude's squares put the
sign back) and `es-cut-ignored` (without the early exit pass two's body
runs once, and its own `last < s0` test leaves without asking a corner,
changing only locals).

One equivalence fell the other way. `ct-no-clear` drops the copy
constructor's call to `Clear`, which in the demo could change nothing,
because the memset had already zeroed everything `Clear` writes. Retail's
`Clear` also stores -1 at 516, which the memset does not, so dropping the
call leaves a copy whose `LastPointToScore` is 0, and the pass catches it.

After 11b-1 both tallies are one uninterrupted run each. Before it, the
model's was one run and the image's came from two. The
first stopped after 36 mutants on a `BuildEnvironmentError` -- the msys2
toolchain returning a failure with no diagnostic, which `hostbuild` says to
rerun -- and the other 226 then ran in a fresh process with the build
retried on that error and the finished 36 skipped. Before the pad fix, the
model's own tally also came from two runs, split the same way after twelve.

The first full pass left **72 survivors** on a transcript that already
agreed with the model on every one of its 660 lines. That is the whole
reason to run the pass: a clean diff says the two sides compute the same
thing, not that the scenarios ever reach the code. The transcript is 993
lines now.

**Boundaries nothing sat on.** Most of the survivors were a `<` turned into
a `<=`, or a constant nudged, and killing one needs the two sides exactly
equal -- picking a likely number is not good enough.

`k-score-t2` lowers the second skip-ahead threshold from 0.4 s to 0.2 s.
The fixture that was already there puts the inner walk's time at exactly
0.4, which fails both tests, so it could not separate them; the new one
puts it at 0.391 s, inside 0.4 and outside 0.2, and the two versions then
stop the walk on different points and ask `CalculateMaxSpeed` about
different corners. `es-pass1-inclusive`, `k-score-t1` and `k-score-t3` are
the same shape at their own thresholds.

`ms-v1-scaled-by-out` and `ms-divides-twice` were the two stubborn ones.
Both change the arithmetic inside `CalculateMaxSpeed` in ways that come out
at the same float almost everywhere, so the fixture has to sit within an
ulp of the grip test. Both were found by bisecting the entry speed against
the 30 m/s^2 limit until the answer flipped, and the pair of fixtures
either side of that boundary kills them.

**Boundaries that were sat on and still could not be seen.** The last two
survivors were this instead, and they are the more interesting failure: the
fixture reached the equality exactly, the two versions really did take
different branches, and the dump printed the same numbers anyway.

`bl-window-inclusive` turns `accTime < 0.75` into `accTime <= 0.75` at the
tail of `BlendWithCurrentAcceleration`. The fixture already put `accTime`
at exactly 0.75 -- legs of 5 m and 2.5 m at 10 m/s -- so the mutant ran one
more pass than the original. That pass blends at `0.75 * 1.33333337`, which
clamps to 1, so it leaves x and y exactly where they are; z, pad and
`CalculatedSpeed` were all zero already, and `SetPoint3` writes zero into
all three. An extra pass that changes nothing. Giving the points a z of 3
is enough, because `SetPoint3` zeroes z whatever the blend is and `Length`
is recalculated from it.

`rs-inner-test-strict` turns `len[k] <= travelled` into `len[k] <
travelled` at the head of `Resample`'s step-over. It needs `travelled ==
len[k]` exactly -- and that alone is still not enough, because the real
code then emits `Points[k+1]` at frac 0 while the mutant emits `Points[k] +
seg[k]` at frac 1, which is the same point unless the addition fails to
undo the subtraction. Three points with legs of exactly 5 m put the
accumulator on the boundary, and the separation goes in the pad, where
`16777218 - 1` and `1 + 16777216` are both ties that round to 16777216 --
two ulps short of where the other arm lands. The pad is not in `len3`, so
the geometry stays a plain 3-4-5 ladder. Everything after that slot
re-syncs, the mutant spending its next pass stepping over the segment it
should already have left, so the whole difference is one printed cell.

**Arms no scenario entered.** `Clear`'s collapse arm, `InterpolatePoint`'s
one-point arm, `Resample`'s pad and stamp, `FillWithCurrentAcceleration`'s
turn-back exit and `BlendWithCurrentAcceleration`'s window. Each has a
scenario of its own now.

**A diagnosis that looked like a hole and was not.** `es-pass1-inclusive`
survived a fixture designed for it, and the reason was in the hunt script
rather than in the code: it never ran the static initialiser, so
`DriveTargetMinDistanceToPointSquared` was the `.sbss` zero instead of 16.
The fixture's first point is exactly 4 m out, `GetFirstPoint`'s test is the
strict `MIN_DIST_SQ < d^2`, and the real code steps over it -- so the inner
loop never reached the equality the fixture was built around. Moving the
first point to 6 m fixed it. The lesson is the repo's own rule read back at
it: **a model used to design a fixture has to be initialised the same way
the transcript initialises it.**

#### The twenty that survive

Each one is argued in the checker's `EQUIVALENT` dict rather than left as a
number in the tally, and the import asserts that every name there is a
mutation that exists, so a typo shows up at import instead of inflating the
count.

The sharpest of them is worth repeating here, because it is a fact about
the class and not just about a mutation. **`CalculateMaxSpeed` never writes
anything into `CalculatedSpeed` but the entry speed it was handed.** Both
of its `*pOut = speed` arms store the entry speed, and the entry speed it
is given is `CalculatedSpeed[first]` in the first walk and
`CalculatedSpeed[outer - 1]` in the second. The fill loop sets every entry
from `first` up to `VelocityMagnitude`, so by induction the whole array
stays at `VelocityMagnitude` and `EstimateScore` returns either the car's
own speed or -1. The array the method is named for never holds anything the
car was not already doing, which is why `es-trapezoid-one-sided` and
`es-sum-pairs-shifted` -- two mutations that change which pair of speeds
each trapezoid averages -- cannot be caught by any input.
