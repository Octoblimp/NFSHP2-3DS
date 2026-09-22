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

Ported to `3DS Files/source/drivetarget.{c,h}`. Cross-checked by
`tools/drivetarget_check.py` against `tools/src/drivetarget_test.c`.

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
| 516 | *(pad)* | 12 bytes, 516 rounded up to 33 × 16 |

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
`StraightLinePredict`'s heading, and the blended point in
`BlendWithCurrentAcceleration`. In each, `Points[i].pad` ends up holding
whatever the stack held.

**This is the one place the port does not follow the image, and it is
deliberate.** Reading an uninitialised automatic is undefined behaviour in
C, so those temporaries get a `pad` of 0.0f. Nothing on the disc can
depend on the value either — it is a different number on every call — so
the divergence costs a behaviour no caller could have had. Every site is
marked `STACK-W` in `drivetarget.c`.

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

## Two divergences, both written down

**`GetRouteAndRoutePoint` bounds `Route[i]` and the image does not.** The
listing is `bltz` and then a raw `lw` off `pTrackRoutes`: the negative case
is handled and nothing checks the top. `Route[i]` is an `int8_t`, so 100
to 127 would index past the hundred-entry table into whatever the linker
put next — which is not the same thing here as it was on the disc. The
port uses `trmgr_get_route`'s bound instead and answers 0 above 99. The
`p == NULL` test after the route point is computed can never fire, because
the pointer has just had 1064 added to it, and is kept because it is there.

**The `STACK-W` sites write 0.0f**, as above.

## Cross-check

`tools/drivetarget_check.py` models the class from the disassembly at
0x002086f8..0x0020a840, from the copy constructor at 0x001da210, and from
the three free functions at 0x001c0e30, 0x001c0c20 and 0x001c3338 — not
from the C. Every constant comes out of `PS2 Files/NFSHP2.ELF` by address,
so a typo in the header shows as a diff rather than as two files agreeing
with each other.

`bMath` and `bVector` come from their own checkers' models rather than
being written again: `GetAngle` is one `bATan`, five methods normalise, and
re-deriving `bASin`'s twelve-octave table would duplicate a model that
already has its own transcript. `CarState` and `TrackRoute` are local
stand-ins, because DriveTarget touches five fields of one and two of the
other.

```
drivetarget_check   22 scenarios, 821 lines, 0 differ
```

### Fixtures are spelled, not computed

Every fixture float is its own decimal literal on both sides. `0.32f +
0.01f` is 0.329999983, one ulp below the float nearest 0.33: the model
rounds a literal once and the C rounds the sum twice. Fixtures are not the
thing under test, so they are written so that the two sides cannot disagree
about them.

### What the mutation pass moved

```
python tools/drivetarget_check.py --mutate   # 259 mutations, 239 caught,
                                             # 20 equivalent, 0 unexplained
```

The first full pass left **72 survivors** on a transcript that already
agreed with the model on every one of its 660 lines. That is the whole
reason to run the pass: a clean diff says the two sides compute the same
thing, not that the scenarios ever reach the code. The transcript is 821
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
