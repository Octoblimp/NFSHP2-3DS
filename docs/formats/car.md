# Car

The hub of task 25, and deliberately not its physics. Eighty methods,
22876 bytes of code in `Car.obj` (`0x0012f150 .. 0x00134f6c`) plus six the
compiler emitted elsewhere, and a 2016-byte record — but the simulation
itself lives in the movers that `SetMovementMode` constructs. Car owns the
state they write into, the lights, the horn, the wipers, the blown tyres
and the blinking, and it hands everything else off.

Ported in slices. This document covers the record, which is whole, and the
first code slice: the seventeen methods that reach nothing outside Car,
CarState and the two world clocks, plus `Car::WorldToCar`, which reaches
only a CarState method that has been ported since that slice.

Ported to `3DS Files/source/car.{c,h}` and `3DS Files/source/topology.h`.
Cross-checked by `tools/car_check.py` — 20 scenarios, 1871 lines, 0
differing; 82 mutations, 78 caught, 4 equivalent, 0 unexplained.

## Car has no vtable

Worth saying first, because the map suggests otherwise. `__pure_virtual`
appears against `Car.obj`, and the obvious reading is that Car is abstract.
It is not. The symbol belongs to the `CarDriver`, `CarMover` and
`CarController` abstract bases that share the object file.

Car's one base is `bTNode<Car>` at offset 0 — eight bytes of intrusive
list link, the same shape `bslotpool.h` spells out for `bTNode<SlotPool>`,
and the links Race's car list is threaded through. Under the GNU C++ v2 ABI
a vptr would be appended at the *end* of the object; at 2016 bytes the
record ends on `fAngleToCamera` at 2008 plus a quadword round-up, with no
room for one, and nothing in the eighty methods loads a vtable out of
`this`.

## The record

`Car (size=2016)` in `.mdebug`. Every offset below was re-derived from a
load or a store in the listing before it was written down; the table gives
the instruction that confirmed each of the ones the first code slice
touches.

| Offset | Field | Confirmed by |
|---|---|---|
| 0 | `Link` — `bTNode<Car>` | the list walks in `Race` |
| 8 | `CarIndex` (int16) | `lh v0,8(a0)` |
| 20 | `MyDriver` | `lw v0,20(a0)` in `ShouldVisualEffectsBeGenerated` |
| 44 | `pCarDriver` | `lw v0,44(a0)` in `GetSteering` |
| 64 | `State` — embedded `CarState`, 1024 bytes | every `State` access |
| 1160 | `RenderingEnabled` (int8) | `lb v0,1160(a0)` in both gates |
| 1184 | `TheOverrideRenderingPosition`, 96 bytes | the front end's selector |
| 1280 | `TheTopologyCoordinate`, 560 bytes | `PutFlatOnTrack` |
| 1840 | `TheTrackPathCoordinate`, 40 bytes | `GetRoutePoint` |
| 1892 | `WantToBlinkHeadlights` | `sw` in `HonkAndOrBlinkHeadlights` |
| 1896 | `WantToHonkHorn` | `sw` at `0x00132560` |
| 1900 | `WantTwoHonksAndOrBlinks` | `sw` at `0x00132540` |
| 1904 | `HeadlightsAndHornStartTime` | `lw`/`sw`, the WorldTimer stamp |
| 1908 | `HeadlightsAndHornOnDuration` | `lwc1 $f3,1908(a0)` |
| 1912 | `HeadlightsAndHornOffDuration` | `lwc1 $f0,1912(a0)` |
| 1928 | `WiperOnTime` | `lw v0,1928(a0)` at `0x001319c8` |
| 1932 | `WiperOffTime` | the two branch-likely delay slots |
| 1936 | `WiperState` | `lw v0,1936(a0)`, the early-out |
| 1944 | `BlownTireBits` (uint8) | `lbu` in `FixBlownTires` |
| 1960 | `BlinkTimer` | `lw v1,1960(a0)` at `0x00131644` |
| 1964 | `BlinkDuration` | `lwc1 $f1,1964(a0)` |
| 1976 | `bPoofed` | `lw v0,1976(a0)` in `IsPoofed` |
| 1980 | `bVisibleOnTrackMap` | `sw zero,1980(a0)` in `BlinkBlinkPoof` |
| 2008 | `fAngleToCamera` | the last field; 2012 is padding |

Almost every field the game touches is inside `State`, and the listing
reads them through Car rather than through the embedded record:
`GetWheelTraction` loads 916 and 928 off `this`, which are State+852 and
State+864. The header reads through `State` and the two agree because the
offset is fixed.

### The three records that widen, and by different amounts

Car embeds three things by value that contain pointers, and on a 64-bit
host they do not grow by the same amount:

- `CarState` by two pointers,
- `TrackPathCoordinate` by four,
- `TopologyCoordinate` by a hundred and twenty-eight.

That last one is why `topology.h` states `TopologyCoordinate`'s layout
rather than reserving 560 opaque bytes. `TrackPolygonTable` is 128
*pointers*; on the host that array alone adds 512 bytes. A blob would have
made Car's size assert agree with the wrong number on the host and the
right one only on ARM — the failure `wheel.h`'s `_pad2` already cost this
port once.

So every assert in `car.h` carries its own slack count:

```c
#define CAR_SLACK ((size_t)(sizeof(void *) - 4))
#define CAR_AT(f, n, k) (offsetof(Car, f) == (size_t)(n) + (k) * CAR_SLACK)
```

On ARM every slack term is zero and `CAR_AT` reduces to the console's raw
offset, which is the check that actually matters.

### One slack unit that is not a pointer

`CarIndex` and `DriverNumber` are two int16s at 8 and 10, which leaves
`pCarTypeInfo` at 12. A 64-bit host must round that up to 16 — four bytes
the console does not spend. It is the same width as one widened pointer,
so every offset past it reads as one extra slack unit without there being
an extra pointer to account for it. Two more such gaps follow, before
`pCarDamage` and before `pCaffeineObj`. On ARM all three vanish.

### Padding asserted by width, not only by offset

The seven holes are asserted twice — once for where they start and once
for how wide they are — and the second assert is not redundant. The
mutation pass is what proved it: shortening `_hole56` from eight bytes to
four changes nothing on this host, because `CarState` is eight-byte
aligned here and the compiler pads the gap straight back. On ARM the
alignment is four and the same edit would slide the entire record from
`State` onwards. Asserting the width makes the host build say so too.

## What is in the first code slice

Eighteen methods: three retail stubs, the blinking, the debug checksum,
the two wheel aggregates, the two effect gates, the forward acceleration,
the horn request, the wiper window, the borrowed steering angle, and the
`WorldToCar` forwarder.

Six of them are easy to transcribe wrongly, and none of the six shows in
the shape of the code.

### `GetWheelTraction` pairs the diagonals, not the axles

`0x001330e0` adds 916 to 928 and 920 to 924 — `WheelTractionUsage[0]` with
`[3]`, and `[1]` with `[2]`. Each pair is halved and the larger of the two
is returned.

Read as front-and-rear it gives the same answer on a symmetric car and a
different one on every asymmetric slide, which is exactly the case the
function exists for. The transcript carries two fixtures chosen so that
the two readings disagree — `u 1 0.5 0.5 0 -> 0.5` and
`u 0.25 0.75 0.5 0.125 -> 0.625`.

### `IsBlinking` has two sentinels

Zero is the obvious one. The other is `0x7fffffff`, built at `0x00131650`
with `lui 0x7fff; ori 0xffff` and tested with `xor` and `sltu` rather than
with a branch — which is precisely why it reads past. It is a real second
early-out and `PleaseResetMeLater` writes it.

Both mutations that drop one of the two sentinels are caught, and so is
the off-by-one that spells the second as `0x7ffffffe`.

The elapsed time is `subu` then `cvt.s.w`, so it is a *signed* 32-bit
wrapping subtract. A `WorldTimer` that has wrapped past the stamp gives a
negative elapsed time and the car keeps blinking. Kept as it is.

### `ShouldVisualEffectsBeGenerated` tests the driver type first

The traffic-car test at `0x00134144` comes before the poof test and before
`RenderingEnabled` is loaded at all, so a traffic car answers false
whatever its other two fields say. `ShouldSoundEffectsBeGenerated`, four
addresses later, has no such test.

### `HonkAndOrBlinkHeadlights` sums `On + Off + On`, with the old durations

The guard is that the previous request's whole cycle has already elapsed,
so a second honk inside the first one is dropped rather than queued.
`0x0013252c` adds Off to On and `0x00132534` adds On again — all of it
before the new durations are stored, so the guard is measured against the
request that is still running. Two thirds of a cycle, or the same sum with
the incoming durations, is a different guard, and both mutations are
caught.

### `GetForwardAcceleration` returns a magnitude below the threshold

The `c.lt.s` at `0x00133dc0` sends speeds under 0.1 to a plain `sqrt` of
the acceleration's squared length. That is unsigned, so a car braking hard
at a standstill reports a *positive* forward acceleration. Above the
threshold the answer is the dot of the acceleration with the normalized
velocity and can go negative.

`vrsqrt Q,vf00w,vf01x` at `0x00133e0c` is a real divide by a real square
root on the VU, not a fast estimate, so `1.0f / sqrtf(len2)` is exact for
the port — the same reading `wheel.c`'s `normalize3` takes.

### `TurnWipersOnForDuration` is a window merge with two branch-likelies

`WiperOnTime` and `WiperOffTime` are a half-open window of frames during
which the wipers run. A new request either extends the window it overlaps
or replaces one that has already passed; then the off-time is rounded *up*
to a whole number of 82-frame wipes measured from the on-time, so a wipe
that has started always finishes.

`0x001319d4` and `0x001319e0` are `bnel` and `beql`, whose delay slots
execute only when the branch is taken, and both delay slots hold
`lw v1,1932(a0)` — the off-time. Read as ordinary branches the load lands
on the wrong side and the merge picks the wrong end of the window.

The final rounding is `(span + 81) / 82 * 82 + start` with a signed
divide. A span that came out negative — which the merge can produce when a
caller passes an `off` before its own `on` — divides toward zero and the
result lands short of `start`. Kept: the original does the same.

This is also the only method in the slice that reads `WorldTimeFrames`
rather than `WorldTimer`.

## `cvt.w.s`, written out in full

`CalculateDebugChecksum` is four instructions — add x to y, scale by
65536, convert, return — and it was the one function in the slice whose
first transcript did not match.

Truncation toward zero is the easy half and a C cast already does it. The
other half is the ends. The R5900 saturates **by the sign of the source**:
`0x7fffffff` for a value at or above 2^31, `0x80000000` for one below
-2^31. A bare C cast does not reproduce that, and the conversion is
undefined behaviour in C besides. The three targets disagree in practice:

| Target | out of range, positive | out of range, negative |
|---|---|---|
| R5900 `cvt.w.s` | `0x7fffffff` | `0x80000000` |
| ARM `vcvt.s32.f32` | `0x7fffffff` | `0x80000000` |
| x86-64 `cvttss2si` | `0x80000000` | `0x80000000` |

So ARM agrees with the console and the host build did not. The port now
spells the conversion out in `car_trunc_w`, which is
`tools/camera_check.py`'s `trunc_w` — the model the camera slice wrote
first — moved to the source side. It is `static` because Car is its only
caller; when a second appears it belongs in a header of its own, not in
`bmath.h` or `emath.h`, which are faithful ports of real object files and
own no invented functions.

The negative threshold is spelled `x < -2147483648.0f` here and
`<= -2147483649.0` in the Python. The two select the same set of float32
values: -2^31 is exactly representable and the next float32 below it is
-2147483904, with nothing in between.

Two of the four surviving mutations live here, and both are worth reading:

- **`trunc-neg-threshold-le`** — clamping exactly -2^31 yields the value
  the conversion already yields, because -2^31 is its own saturation
  value. No fixture can tell the two spellings apart, on any target.
- **`trunc-no-neg-saturation`** — deleting the negative arm changes
  nothing *on this host*, since `cvttss2si` already returns `0x80000000`
  below range, and nothing on the other two either, since they agree with
  the arm. What the arm buys is not a different answer but a defined one:
  without it the conversion is UB and a compiler that constant-folds it is
  entitled to produce anything. The positive arm, by contrast, is a real
  behaviour change on this host, and all three of its mutations are
  caught.

In the game this never fires. `Position` is a track coordinate of at most
a few kilometres and the scaled sum stays well inside range; the
out-of-range fixtures are the transcript's, not the game's.

## The tick constant, and a comment that was wrong

`CAR_TICK_SECONDS` is `0.000250000012f` — the image's own word,
`0x3983126f`, read out of the ELF by address at two different `gp`
displacements (`gp-32020` in `IsBlinking`, `gp-31992` in
`HonkAndOrBlinkHeadlights`) and asserted equal, because "one `#define`
covers both call sites" is a claim the port makes and not an observation.

`car.c` originally carried a comment saying the constant was written as a
literal because `1.0f / 4000.0f` rounds to `0x3983126e`, one ulp down.
**That was false.** The correctly-rounded float32 of 1/4000 is
`0x3983126f` exactly — the same word. The mutation that swaps the two
spellings is what said so: it survived against a clean transcript because
there was nothing to catch. The comment is corrected and the mutation is
recorded as equivalent, which is the honest place for it.

The word that *is* different is `0x3983126e`, which a hand-typed
`0.00024999999f` gives, and the first mutation pass showed that nothing in
the transcript could tell it from the real one. Every other fixture
compares far enough from a boundary that a single ulp of tick does not
flip an answer. Two scenarios were added that do:

- **`[blink tick]`** — 4000 ticks of the correct word is exactly `1.0f`,
  and `IsBlinking`'s test is `elapsed < duration`, so a duration of
  `1.0f` answers no on the image's word and yes one ulp below it. The
  stamp is 1 and the timer 4001 rather than 0 and 4000, because a stamp of
  0 is a sentinel and would early-out before the tick was ever multiplied
  in.
- **`[honk tick]`** — the guard is `cycle < elapsed`, so the separation
  runs the other way: a cycle of exactly `0.99999994f` fires on the
  correct word and does not fire one ulp below. Deliberately the opposite
  direction from the blink, since the two call sites read the constant
  from different `gp` displacements.

## A fixture that could not see its own mutation

`stub-event-writes` makes `EventHandler` secretly set `bPoofed = 1`. It
survived the first pass — because the `[stubs]` fixture set `bPoofed = 1`
itself before snapshotting the record, so the write stored the value that
was already there. The scenario compares 2016 bytes before and after and
counts the differences; a field holding the value the write would store is
a field the comparison cannot see.

The fixture now seeds 2 into the three fields the three stub mutations
write, and all three are caught. The general form is worth keeping in
mind: **a no-op fixture value is a blind spot, and only a mutation finds
it.**

## The other two survivors

- **`steering-signed`** — `GetSteering` is `lhu` and return, and
  `Steering` is a `uint16_t`. Round-tripping a 16-bit value through
  `int16_t` and back reproduces every bit of it; the sign extension the
  detour introduces is truncated away again by the return type. The
  mutation is the identity, which is the point of recording it: a reader
  who later "fixes" the signedness here changes nothing.
- **`tick-is-one-over-4000`** — covered above.

## `Car::WorldToCar` is eight bytes

```
00138e90  j     0x001b6ab0   <WorldToCar__8CarStateP8bVector2T1>
00138e94  addiu a0,a0,64
```

A tail call with `this + 64` — the embedded CarState. Only the 2D overload
exists; there is no `WorldToCar__3CarP8bVector3T1` in the image. It is one
of the six Car methods the compiler emitted outside `Car.obj`.

It is not one of the thirty-four, because `CarState::WorldToCar` is outside
the class. It is in this slice anyway, because that callee has been ported
since the CarState slice, so nothing is stood in for.

The only thing the forwarder can get wrong is the 64, so the transcript is
built to see that rather than to re-test the transform. Each fixture prints
`MatrixValid` next to the transformed point: `GetTransformMatrix` sets that
flag on whichever CarState it was handed, so a forwarder passing the wrong
address leaves the flag at `Car+64` clear even if the numbers happen to
agree. The transform itself comes from `carstate_check`'s model rather than
being restated here — restating it would test the checker against itself.

Linking it in means `car_check` now builds `carstate.c` and the four files
under it. They are not under test here; `carstate_check` owns them. Linking
the real ones rather than stubbing them is what makes the fixtures mean
anything.

## What is not ported yet

Ten methods wait on a vtable seam. `CarController`, `CarDriver`,
`CarMover`, `CarDamage` and `CollisionBody` are abstract bases whose
vtable this port models as a stored word, so a call through one cannot be
written until that seam exists:

> `Think`, `Drive`, `GetRoute`, `GetRoutePoint`, `GetAmountOutOfBounds`,
> `UpdateSound`, `IsCollideable`, `SetToPhysicsMode`,
> `UpdateHeadlightsAndHorn`, `IsFacingWrongWay`

Nine wait on a class that belongs to task 26 or 27: `UpdatePosition` and
`MaybeCameraShake` on the effect system, `GetCarSpaceBoundingBox` and
`GetLastPenetrationTime` on `CarCollisionBody`, `GetTrackedAcceleration`
on a `RealController` field at +20, `SetFrictionBoost` on a `PhysicsCar`
field at +108, `FixBlownTires` on `RealDriver::ForceEBrakeStop`,
`CalculateDraftFactor` on `pCurrentWorld`'s car list, and `PutFlatOnTrack`
with `FindFlatOnTrackPosition` on a real `TopologyCoordinate`.

The remaining fifty are the constructor and destructor, the reset and
damage groups, the render and sound groups, and the two force-feedback
methods.

One piece of carried debt lands here: `wheel_install_seams()` is defined
in `wheel.c` and never called. Its home is the `MM_PHYSICS` arm of
`Car::SetMovementMode`, which is in the vtable-seam slice.

## Includes, and the cycle underneath them

`car.h` once declared `typedef struct Car Car;` **above** its own
includes, to survive `drivetarget.h`'s stand-in `Car`, which lived inside
its own `#ifndef CAR_H` and would otherwise have switched this file off
silently. The stand-in is gone — `drivetarget.h` includes this header now
— so the ordering rule it created is retired, either include order gives
the real record, and nothing in `car.h`'s own include chain names `Car`.
The typedef sits with the other forward names below the includes.

`car.h` names `CarTypeInfo` and `CarDriver` rather than including their
headers, and that is not a style choice. The chain is:

```
cardriver.h  ->  drivetarget.h  ->  car.h  ->  cardriver.h
```

By the time `car.h` is reached from `cardriver.c`, `cardriver.h`'s own
guard is already set, so its include expands to nothing and
`CarDriver *pCarDriver` would have no type. Car holds both of those as
pointers only, so naming them is enough, and anything that needs the
complete record includes the header itself: `car.c` does, for
`pCarDriver->Steering`, and so does `tools/src/car_test.c`, which declares
one by value.

`CarState`, `TopologyCoordinate` and `TrackPathCoordinate` are embedded by
value and so must be complete; all three are included.
