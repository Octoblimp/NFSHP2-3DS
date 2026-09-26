# Car

The hub of task 25, and deliberately not its physics. Eighty methods and
22876 bytes — seventy-four of them, 20460 bytes, in `Car.obj`
(`0x0012f150 .. 0x00134f6c`), and six the compiler emitted in other objects
— and a 2016-byte record. The simulation itself lives in the movers that
`SetMovementMode` constructs. Car owns the
state they write into, the lights, the horn, the wipers, the blown tyres
and the blinking, and it hands everything else off.

Ported in slices. This document covers the record, which is whole, and
eleven code slices; the fourth, the movement and control modes, has
[a document of its own](car-modes.md). The first is the seventeen methods that reach nothing
outside Car, CarState and the two world clocks, plus `Car::WorldToCar`,
which reaches only a CarState method ported since. The second is the
vtable seam, the nine methods that are pure dispatch through it, three
fields Car borrows from other classes, the draft, and the object's static
initialiser. The third is seven methods that call out into code ported
already: where the other cars are, the post-collision yaw boost,
`IsDrifting`, and `ComputeFakeRPM`. The fourth is `SetControlMode`,
`SetMovementMode`, `SetToPhysicsMode` and `SetFrictionBoost`, with the
null mover, controller and driver they build. The fifth is the two that
stand the car on the ground, `FindFlatOnTrackPosition` and
`PutFlatOnTrack`, which waited on the topology (task 27). The sixth is
the reset group: `ResetCore` and the three that wrap it. The seventh is
`AverageAir` and `BeginMovement`: the air under the car, and the start of
each of its steps. The eighth is `Move`, the step itself, with the three
it calls first: `ChangeGear`, `CalculateNewCatchupMultipliers` and
`UpdatePosition`. The ninth is six that make one call out of Car each:
the distance between two cars, the blown tyres, the deferred reset, the
AI's driving line and the delivery. The tenth is
`TriggerCarTerrainEffects`, the smoke, spray and splash under the wheels.
The eleventh is `FinishMovement`, the end of each step. Sixty-three of the
eighty methods are ported, 12456 of the 22876 bytes.

Ported to `3DS Files/source/car.{c,h}`, `topology.h`, `vtable.{c,h}`,
`world.{c,h}`, `collisionbody.h`, `carcontroller.h`, `sound3d.h` and
`sinit.{c,h}`, with `bToPolar` added to `bmath.{c,h}`. Cross-checked by
`tools/car_check.py` — 58 scenarios, 4238 lines, 0 differing; 254
mutations, 238 caught, 16 equivalent, 0 unexplained — and the boot walk by
`tools/sinit_check.py`, 6 mutations, 6 caught. The fourth slice's files
and its checker are listed in [car-modes](car-modes.md). The fifth and
seventh are `cartrack.c`, checked by `tools/track_check.py`, which has the
topology loaded already. The sixth is `carreset.c`, with two of `ReplayManager`'s
methods in `replay.c`, checked by `tools/carmode_check.py`. The eighth is
`carmove.c`, with `timer.c`, `player.c`, `difficultyinfo.{c,h}` and
`Race::GetRacingCar` in `race.c`, checked by `carmode_check` too. The
ninth is `carrace.c`, with `DynamicCollisionBody::GetDistanceAndSpeed` in
`carcollisionbody.c`, checked by `carmode_check` as well. The tenth is
`careffects.c` and the eleventh `carfinish.c`, and `carmode_check` checks
both.

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

## What is in the second code slice

Thirteen methods and one static initialiser, on top of a seam:

- **the vtable seam**, `vtable.{c,h}`, which every dispatch goes through;
- **nine dispatchers** — `Think`, `Drive`, `GetRoute`, `GetRoutePoint`,
  `GetAmountOutOfBounds`, `UpdateSound`, `IsCollideable`,
  `IsFacingWrongWay`, `UpdateHeadlightsAndHorn`;
- **three borrowed fields** — `GetCarSpaceBoundingBox` and
  `GetLastPenetrationTime` from the `CarCollisionBody`, and
  `GetTrackedAcceleration` from a `TrackedController`;
- **the draft**, both overloads of `CalculateDraftFactor`;
- **`_GLOBAL_$I$fDraftFalloff`** (`0x001347c0`), which builds the draft's
  Table and Graph and five other tables the rest of Car reads.

Each class the slice reaches into brought only what Car reads of it:
`CarCollisionBody` and `Timer` in `collisionbody.h`, `TrackedController`
in `carcontroller.h`, `Sound3d` in its own header, and the front of
`World` — up to the end of `CarTable` and no further — in `world.{c,h}`.

### The vtable seam

g++ 2.9x makes a virtual call as four instructions, and every dispatcher
in this slice is exactly those four:

```
lw   v0, V(obj)       # the vptr, at the class's own offset V
lh   a0, S(v0)        # entry S: the this-adjustment ...
lw   v1, S+4(v0)      #          ... and the function
jalr v1 ; addu a0, obj, a0
```

A table is an array of eight-byte `{int16 delta, int16 index, fn}`
entries with entry 0 empty, and a slot is named by its byte offset. The
vptr is not at offset 0: g++ 2.9x puts it after the data of the first
class that declares a virtual, so it is at 8 in `CarController`, 556 in
`CarDriver`, 28 in `Sound3d` and 80 in `CollisionBody`.

The port already kept every vptr as the image's own address, in a
`uint32_t` at the image's offset. `vtable.c` adds the other half: a
registry from that address to the port's entries. A call site is then
written as the image writes it — same slot, same delta added to the same
pointer — and a harness can install a recording table **at the real
address** and watch which slot was taken.

`car_test.c` does exactly that. Each class gets two tables: one with delta
0 and one with a nonzero delta (4 for the AI controller and the AI car
sound, 8 for `CarDriver`, 12 for `DynamicCollisionBody`), and every fake
prints the `this` it was handed as `<fixture>+<offset>`. So the transcript
shows the three things a virtual call can get wrong — the slot, the
adjustment and the order — and a dispatcher that drops the `addu` prints
`ctl+0` where the model says `ctl+4`.

The deltas are port data, not the image's: a delta is a distance between
two bases, and the host's slack moves bases. So each class that installs a
real table will compute its deltas with `offsetof` rather than copy the
image's `lh` values.

`vt_slot` never returns NULL. It aborts on a vptr nobody installed, a slot
that is not a multiple of eight, slot 0, a negative slot, a slot at or
past the table's count, and an entry with no function — each of which
means a class the port has not brought over was somehow constructed, a
port bug rather than a game state. `vt_install` aborts past 96 tables.
car_check runs every refusal as its own process and requires the abort and
its message; the full-registry mode also prints how many installs
succeeded first, so a limit of 95 or 97 shows.

### The static initialiser, run rather than read

Only `fDraftFalloff` is in `.data`. Everything else the initialiser
touches — the speed-range knees, the Table, three Graphs, the thirteen
`ObjectPoints`, the `DamageAboveMatrix` and the post-collision yaw profile
— is zero until it runs.

car_check does not transcribe it. It **runs** `_GLOBAL_$I$fDraftFalloff`
in `mipsemu`, the Table and Graph constructors included, and prints every
word left in memory, with each pointer named by the symbol it lands on.
The Table's multiplier (5.0) is the image's own division, and the Graphs
alias `vDraftSpeedRange`, `vRoadNoiseSpeedData` and
`PostCollisionYawControlProfileData` rather than copying them.

Two details that the run showed and a transcription could miss:

- the initialiser never stores an `ObjectPoints` pad lane, so each stays
  the zero `.bss` gives it — and `DamageAboveMatrix` stores all sixteen
  words, the last row's `w` = 1 included;
- the road-noise knees are `0x3fb1c71d` and `0x415e38e4` from `gp-31900`
  and `gp-31896`, which are `1.388889f` and `13.888889f`: 5 and 50 km/h in
  metres per second as the image rounded them, not as `5 / 3.6f` rounds.

#### Nothing called it, or the other three

The port had four ported static initialisers — Car's, RigidBody's,
Wheel's and DriveTarget's — and **nothing ran any of them**. Every Table
they fill would have been zero the first time the physics looked
something up. The image never has that problem: `main+0x14` calls
`__main`, which hands `bCallFunctions` the range after the count word at
`__CTOR_LIST__` (`0x00314f78`, 109 entries), and `bCallFunctions` walks it
forwards before `main` does anything of its own.

`sinit.{c,h}` is that walk over the ported entries, in list order —
`[14]` Car, `[41]` RigidBody, `[44]` Wheel, `[87]` DriveTarget and `[103]`
the slot-pool manager — and `main.c` calls it where it used to call
`bSlotPoolManagerInit` alone. `tools/sinit_check.py` holds each call to
its list index and its symbol, requires the indices to increase, requires
each function's own source to name the same address, and requires every
`*_static_init` defined anywhere in the source to be called exactly once.
Its six mutations are all caught.

The walk also corrected a comment. `main.c` credited the manager to
`_GLOBAL_$I$` at `0x00240070`; that address is the `$D$` beside it, which
runs the destructor. The constructor is `_GLOBAL_$I$bNewSlotPool__FiiPCci`
at `0x00240080`, and it is entry 103 — so on the console the manager is
built *after* all four physics initialisers, which is where the walk puts
it. None of the five reads anything another writes, so the order is kept
because it is the image's, not because a different one would be seen.

### The draft

`CalculateDraftFactor(Car *other)` is what `other`, running ahead, gives
`c`: zero unless the leader is fast enough, near enough, and has `c`
inside a cone behind it; otherwise a falloff looked up by distance over a
speed-scaled cone factor.

It reads two of the speed-range knees *directly* as thresholds —
`vDraftSpeedRange[1].x` (1.0) as the slowest leader worth drafting, and
`vDraftSpeedRange[3].y` (60) as the farthest one can be. Both are read
through the pointer the initialiser filled, and the model asserts the
`lui`/`addiu` pair that builds it and the two displacements, 8 and 28.

VU order throughout: `vmul.xyz`, `vaddy.x`, `vaddz.x`, so every length and
dot is `((x + y) + z)`. The distance's root is the FPU's `sqrt.s`; the
velocity's is `vrsqrt`, read as `1.0f / sqrtf` as the forward acceleration
reads it. The cone constants are the image's words: `0.95f` (`0x3f733333`)
and `19.999996f` (`0x419ffffe`) — which is `1 / (1 − 0.95f)` as float32
arithmetic gives it, not the `20.0f` a person would type. The early-out
and the cap are both `0.9f` but are two literal-pool words (`gp-32084` and
`gp-32080`), so they are two `#define`s, and a mutation that moves one
without the other is caught.

**The slowest-leader test is redundant, and that is why two mutations of
it are equivalent.** The speed Graph is 0 at every speed up to 1.0 — flat
from `(0,0)` to `(1,0)`, and `p[0].y` below the first point — so a leader
that slips past the test divides by zero, the Table clamps the `+inf` to
its high end, and its last entry is 0: the same 0 the early return gives.
Moving the threshold down, or making it `<=`, changes nothing a fixture can
see. Moving it *up*, to `[2].x`, is caught, because a leader at 3 has a
draft to lose. A third mutation, `f <= 0` for `f < 0`, is equivalent for
the same reason: at `f == 0` the divisor is zero again.

The sum walks `pCurrentWorld->CarTable`, reloading the world and the count
every pass, skipping `c`, and testing the early-out after every car. The
world fixtures are strings — `"CEC"`, `"sA0"` — with `0` a NULL entry the
loop must never reach, so a loop that fails to stop crashes the harness.
Two worlds (`"BB"`, `"CB"`) overshoot 0.9 on their last add so only the
cap brings them back; `"CEC"` passes through 0.85, under the early-out, so
an early-out at 0.8 stops it one car early and shows. Testing only after
cars that are not `c` is equivalent: that test sees the sum the previous
test already let through, or 0 when `c` comes first.

#### A NaN the console cannot produce

Two cars at exactly the same position make the distance 0, and `dot /
dist` is 0/0. (A leader whose `VelocityMagnitude` is at least 1 but whose
`Velocity` is zero would do the same to the normalisation; the two should
agree, but nothing here enforces it.) The EE's FPU has no NaN — its zero
divide saturates — so on the console the lookups carry on with large
finite numbers. The port is IEEE, so the NaN reaches `table_get_value`,
and what happens then is the host's float-to-int conversion: ARM
saturates a NaN to 0 and the draft comes back NaN, while x86 gives
`0x80000000` and indexes far outside the table. The sum then turns a NaN
into the cap, because `sum < 0.9f` fails.

No fixture builds this case, since it would crash the host harness. The
port is left as the image is. The place to decide it is task 26, which
owns spawning and so owns whether two cars can ever share a position.

### The dispatchers

Most are the four instructions and nothing else. The ones with something
to get wrong:

- **`IsFacingWrongWay`** is "not strictly positive": the car's forward
  axis (`BodyMatrix` row 0, `Car+144` and `+148`) dotted with the route
  point's direction in the ground plane, and `0 < dot` means right way. A
  car exactly across the road is facing the wrong way, and so is a NaN.
- **`UpdateHeadlightsAndHorn`** skips player cars entirely. The request is
  on, off, on from the stamp. During the *off* phase `lit` is
  `WantTwoHonksAndOrBlinks == 0` (`sltiu a0,v0,1`), so a single request
  stays lit straight through the gap and only a double one goes dark;
  after the second on phase it is simply off. The lights are
  `(lit && WantToBlink) ? 1 : (ForceHeadlightsOn != 0)`. The horn is
  edge-driven through the driver — `IsHonking` first, then `Start` or
  `Stop` only on a change — and **`pCarDriver` is reloaded before the
  second call**. The `[headlights reload]` fixture swaps the driver inside
  `IsHonking` to one whose table has a delta of 8, so the reload shows as
  `driver2+8`. The grid is 288 cases: nine moments across both phase edges
  and a clock behind the stamp, against both values of each of the five
  flags.
- **`IsCollideable`** asks nothing of the body while the car is blinking,
  and otherwise normalises the body's answer with `sltu s1,zero,v0` — a
  body that answers 2 or −1 is collideable, and the fixtures include both.
- **`UpdateSound`** does nothing without a sound, and otherwise calls
  `Update(1.0f, 0, 1.0f)`: both floats from one `lui 0x3f80`, the short
  zeroed in the delay slot of the null test.
- **`Think`** stores the draft factor *before* dispatching, so the
  controller's `Think` reads this frame's value. The fake prints what it
  sees.

### The borrowed fields

- **`GetCarSpaceBoundingBox`** is two quadword copies, pad lanes included,
  min before max. Two fixtures alias an output with the body's own box, so
  the order shows.
- **`GetLastPenetrationTime`** returns the one-word `Timer` in `v0`.
- **`GetTrackedAcceleration`** reads `TrackedController::Acceleration` at
  +20 only under `REAL_CONTROL`. The load is in the delay slot of a
  `beql`, annulled when the test fails, so every other mode answers 0
  **without reading the controller at all**. The fixture gives every mode
  a controller that would answer, so a read in the wrong mode shows as a
  number, and then gives every other mode none, so a read crashes.

#### A layout assert that was wrong

`CarCollisionBody`'s assert first said `pCar` was nine slacks past its
console offset, on the reasoning that `DynamicCollisionBody` was already a
multiple of eight on the host. It is not: 256 + 9 × 4 = 292, and a
pointer's alignment rounds it to 296. So `pCar` is ten slacks on, and the
pointer itself makes the eleventh. The host compile said so; on ARM every
slack is 0 and both readings agree, which is exactly why only the host
could find it.

## Five survivors, and all five were fixtures

The slice's first mutation pass left five mutants alive. None was
equivalent.

- **The reach, as `<=` and as `[3].x`** (150 rather than 60). Past 60,
  the lookup's argument `dist / (f * g)` is below 1 only if `f * g` passes
  60, and `g` tops out at 60 — so both mutations look equivalent, since
  `f` is at most 1. But `f` is at most 1 only in exact arithmetic.
  `dot / dist` can round above 1, `f` then passes 1, and a leader exactly
  60 away keeps a sliver of draft (3.7e-6), which `<=` takes away. A leader
  a few ulps past 60 would get a sliver if the reach were 150. No
  single-axis fixture can produce this: `sqrtf(a * a)` is `|a|` again when
  both roundings are correct, so `a * (1 / |a|)` never rounds past 1. That
  is why the fixtures at 60 and 60.0001, which were all along x, could not.
  The first two `[draft rounding]` cases are diagonal, found by searching
  the model.
- **`len2` and `dot`, regrouped.** In every fixture, each sum rounded the
  same either way. The other two `[draft rounding]` cases each have three
  awkward components.
- **The sum counting `c`.** `c` stood still in every world, and a car below
  the knee adds exactly 0. `c` now moves at 30, which the sum never reads.
  A sum that fails to skip `c` drafts from itself at distance 0, which is
  the NaN above, and on the host that crashes the harness. The crash is
  the only way to catch it: every self-draft past the knee is that 0/0.

The five equivalents the slice adds:

| Mutation | Why nothing can see it |
|---|---|
| `sinit-graph-first` | `graph_init` stores the array's address and count and reads nothing in it |
| `draft-knee-le` | at speed 1.0 the Graph is 0, the lookup `+inf`, the Table's last entry 0 |
| `draft-knee-index-0` | the Graph is 0 at every speed up to 1.0: the same `+inf`, the same 0 |
| `draft-cone-le` | `f == 0` makes the divisor 0: the same `+inf`, the same 0 |
| `sum-test-inside-if` | the test on `c`'s pass sees the sum the previous test already let through |

## What is in the third code slice

Seven methods, 1304 bytes, and the template function one of them calls.
Every one calls out of the class, and every callee was ported already —
except `bToPolar`, which the math library's document had counted as ported
and its source had never had. It is in `bmath.c` now, with a `topolar`
scenario in `bmath_check` and a mutation pass of its own there.

| Method | Address | Size | Its outside callee |
|---|---|---:|---|
| `IsCarToLeft` | `0x00131ca0` | 68 | `CarState::WorldToCar` |
| `IsCarToRight` | `0x00131ce8` | 68 | `CarState::WorldToCar` |
| `GetRelativeCarPosition` | `0x00130f10` | 220 | `bNormalize` |
| `IsCarInFront` | `0x00131d30` | 124 | `bToPolar` |
| `GetPostCollisionYawControlBoost` | `0x001341d0` | 132 | `Graph::GetValue` |
| `IsDrifting` | `0x00134258` | 116 | `CarState::GetYaw` |
| `ComputeFakeRPM` | `0x00131080` | 576 | `smooth<float>` |

`smooth<float>` (`0x00134788`, 52 bytes) is emitted in `Car.obj` and is
not a method, so it is not one of the eighty.

### Where the other cars are

`IsCarToLeft` and `IsCarToRight` put the other car's `State.Position`
(`+96`) into this car's frame and read the sign of x: left is `x < 0`,
right is `0 < x`. Both are strict, so a car dead ahead or astern — or at
`-0.0` — is on neither side.

`GetRelativeCarPosition` does not use the heading. It normalises
`State.Velocity` in the ground plane, so a car standing still measures
along world x: `bNormalize` answers `(1, 0)` for a zero vector. The dot of
the delta with that direction is returned and the cross goes through the
pointer; either one past 100 answers 999 (`gp-32032`) and the pointer is
not written. The store is in a `bnel`'s delay slot, annulled for NULL.

`IsCarInFront` takes `bToPolar` of the world delta, subtracts
`State.Angle` (`+868`), sign-extends the result from 16 bits, and compares
its magnitude — `pmaxw` of it and its negation — strictly against the
limit. Two consequences:

- A car dead astern is a turn of -32768, whose magnitude is 32768, so a
  limit of 32768 still excludes it and only `0x8001` and above take in the
  whole circle.
- A car at the same position has a zero delta, and `bATan(0, 0)` is
  16384. It is a quarter-turn to the left, and in front for any limit
  above that.

### The yaw

`GetPostCollisionYawControlBoost` reads the collision body's
`LastYawControlCollisionTime` (`+264`) and answers 0 for the same two
sentinels as `IsBlinking` — 0 and `0x7fffffff` — tested the same way. The
elapsed time is the tick count difference as a **signed** 32-bit number
times the tick; at 4 seconds or more (`lui 0x4080`, strict `<`) it is 0,
and otherwise it is the Graph at `gp-23416`.

As shipped the profile is `(0, 0) (0.4, 1) (1, 1) (2, 0)`, 0 from two
seconds on, so the four-second test changes nothing, and it is 0 before
its first knee too, so a stamp in the future cannot be told from one at
the present. The Graph aliases a writable array, though, and the
`[yaw boost wide profile]` pass pokes it — a last knee at 8 s, a first
value of 0.125 — so that both the cutoff and the sign of the elapsed time
show in the transcript.

`IsDrifting` needs two wheels down (`+888`), a yaw of more than 0.13
radians (`gp-31904`) either way, and a forward speed (`+892`) above 12
(`lui 0x4140`). `GetYaw` is 0 below a forward speed of 5, so its gate
cannot be seen from here.

The threshold is **not symmetric**. The first drifting yaw is 1356 BAM one
way and 1357 the other: `GetYaw` folds a delta of 64180 by subtracting
2π in float32, and that `sub.s` rounds it to -0.12999964, inside the
threshold, where 1356 gives +0.13000 and change. All 65536 deltas were
run through the fold; none lands on 0.13f exactly, so `<` against `<=`
cannot be seen either.

### The fake engine

`ComputeFakeRPM` gives a car whose engine is not simulated a plausible
gear and RPM from its speed alone. Eleven tweakables drive it, all
initialised `.sdata` words read through `gp`, and a twelve-entry table of
(low, high) RPM pairs at `0x002e84f8`:

| Tweakable | Address | Value |
|---|---|---:|
| `GearRTo1Speed` | `0x00323044` | -2 |
| `Gear1To2Speed` | `0x00323048` | 25.38 |
| `Gear2To3Speed` | `0x0032304c` | 40.89 |
| `Gear3To4Speed` | `0x00323050` | 56.47 |
| `Gear4To5Speed` | `0x00323054` | 72.06 |
| `Gear5To6Speed` | `0x00323058` | 80 |
| `GearTopSpeed` | `0x0032305c` | 89.51 |
| `MaxRPMInc` | `0x00323060` | 50 |
| `MaxSpeedInc` | `0x00323064` | 1 |
| `TestSpeed` | `0x00323068` | 0 |
| `TestRPM` | `0x003241cc` | 100 |

```
RPMTable  1000 8500 | 6500 8500 | 6500 8500 | 5500 9000 | 6500 7200 | 6600 7000
```

The speed is `TestSpeed` if that is above 0, else `VelocityMagnitude`;
pulled to 0.01 under `GearTopSpeed` if it reaches it; and smoothed toward
by `MaxSpeedInc` a call through `OldSpeed`. Below `Gear1To2Speed` the gear
is first, or reverse under -2, and the RPM runs along pair 0 by `|speed|`
clamped to 25.38 — so reversing at 30 revs the same as reversing at 25.38.
Above it, the first band whose top exceeds the speed picks the gear (band
`i` gives gear `i + 2`, capped at `FIFTH_GEAR`) and the RPM interpolates
along pair `i + 1`. The RPM is smoothed by `MaxRPMInc` only when the gear
did not change, and then the gear and RPM are stored.

Four things in it are not what the tables suggest:

- **Pair 1 is never read.** Band 1 reads pair 2. As shipped the two are
  both (6500, 8500), so nothing shows; the fixture sets pair 1 to
  (1, 2) to prove it.
- **The last band reads past the table.** Band 5 — 80 to 89.51 — reads
  pair 6, and there are six. The eight bytes after `RPMTable` are
  `PostCollisionYawControlProfileData[0]`, which is (0, 0) once the static
  initialiser has run, so from `Gear5To6Speed` up the fake RPM heads for
  0, 50 a call. The port reads that element by name, and
  `car_check` asserts the adjacency from the ELF's symbol table.
- **Band 5's gear is fifth, not sixth.** `i + 2` is `SIXTH_GEAR` there and
  the cap takes it back to `FIFTH_GEAR`. Band 4 is fifth as well.
- **`TestRPM`'s "unset" is 100, not 0,** and when it is set the smoothed
  value is thrown away for it, so the smoothing's starting point — `RPM`
  or `TestRPM` — cannot be seen.

`smooth<float>` is `cur + rate` if that is under the target, else
`cur - rate` if the target is under that, else the target. The high side
is tested first. A target exactly at an edge comes back as itself, which
is the same number as the edge unless the two are zeros of opposite sign;
the `[smooth]` fixtures use signed zeros to tell `<` from `<=`.

### What the mutation pass said

Seventy-six mutations for the slice, sixty-nine caught on the first pass
and none unexplained. Three weak fixtures had been found by reading the
transcript before the pass ran — no drift boundary on the negative side,
no speed below -25.38 to reach the reverse clamp, and an off-origin
`IsCarInFront` pass whose other cars were all behind the car — and each
got a case first.

The seven equivalents:

| Mutation | Why nothing can see it |
|---|---|
| `rel-across-neg-product` | `(-a) * b` and `-(a * b)` are one float32 for every `a` and `b` |
| `front-turn-reversed` | a 16-bit turn has the same magnitude measured either way, -32768 included |
| `drift-yaw-le` | no reachable yaw is exactly 0.13f, over all 65536 deltas |
| `drift-yaw-always` | the test against 12 fails wherever `GetYaw`'s gate at 5 would answer 0 |
| `fr-frac-clamp-le` | at equality the clamp stores the value `frac` already holds |
| `fr-bands-from-0` | the loop runs only when `speed >= speeds[0]`, so its `i = 0` test cannot pass |
| `fr-smooth-from-rpm-only` | with `TestRPM` set the smoothed value is thrown away for it |

## What is in the fifth code slice

`FindFlatOnTrackPosition` (`0x00130c58`, 564 bytes) and `PutFlatOnTrack`
(`0x00130e90`, 80), in `cartrack.c`. They are Car's, and they are in
`Car.obj`, but they are the first of its methods to reach
`TopologyCoordinate`. `car.c` links into six checkers that have no use for
the topology, its slot pool and the terrain table. So, like `carmodes.c`,
they have a file of their own. The first version put them in `car.c`, and
`realdriver_check` and `realcontroller_check` stopped linking.

With them came `TopologyCoordinate`'s `bVector3` overload of
`SetInterestBBox` (`0x00134f28`), which the compiler emitted in `Car.obj`.
It is eight bytes: `j 0x0014f120`, the `bVector2` overload, with the
registers as they came, so x and y are read out of each vector and nothing
else is. It is in `track.c` as `topology_set_interest_bbox3`. Sixteen call
sites use it: `BeginMovement`, the camera movers, `EnsureTopology`.

### Five samples and two slopes

```
h[i]  = GetElevation(tc, pos + off[i]),   off = (0,0) (1,0) (-1,0) (0,1) (0,-1)
pos.z = ((h0 + Wheels[3].Radius) - Wheels[3].PositionZ) + CenterOfGravity.z
roll  = -cvt.w.s(((h1 - h0) - (h2 - h0)) * 0.5 * K)      low 16 bits
pitch =  cvt.w.s(((h3 - h0) - (h4 - h0)) * 0.5 * K)      low 16 bits
m     = eRotateY(eRotateX(eRotateZ(eIdentity, angle), pitch), roll)
```

Every sample starts at `pos.z`. GetElevation is asked for the terrain
only, into a local that nothing reads, and the probe's fourth lane is
whatever the stack held. Only `pos.z` is written, and `m` is overwritten
whole. Before any of it the image walks the five-element offset array once
with an empty body, the loop an empty constructor leaves behind, and that
is not ported.

- **K is 65536 / 6.28, not 65536 / 2π.** gp-32036 holds `0x46230eac`,
  which is `65536.0f / 6.28f` to the bit, where 65536 / 2π would be
  10430.378. Every slope comes out 0.05% steeper than it is. Kept, and a
  mutation to 2π and another one ulp up are both caught.
- **The slopes are differences of differences.** On a road it makes no
  odds. By Sterbenz's lemma, `h1 - h0`, `h2 - h0` and `h1 - h2` are all
  exact while the heights are within a factor of two of each other, and
  then so is the difference of the first two. They part only when one
  height is far from the rest, which means a sample that found nothing and
  got the probe's own z back. The checker's world has a gap too narrow for
  the five samples along x, and another along y. Before the y gap was
  added, `h3 - h4` in place of the pitch's difference survived the pass.
- **The x slope turns about y and is negated. The y slope turns about x
  as it is.** The negation is `subu s1,zero,s1`, a wrapping one, so the
  port negates unsigned.
- **`cvt.w.s` saturates, and only the low 16 bits are kept.** A slope
  scaled past 2^31 becomes `0x7fffffff`, which is BAM `0xffff`, or 1 once
  negated. Getting there takes a side sample that finds nothing under a
  probe billions high. The fixtures do it on both axes and in both
  directions, and C's own conversion in place of `ee_trunc_w`, which gives
  `0x80000000` either way on x86, is caught on each axis.
- **Only `Wheels[3]` is read**, its radius and its z. The checker gives
  the other three wheels different values.

### `PutFlatOnTrack`: the centre of gravity, unrotated

`FindFlatOnTrackPosition` runs on the car's own `BodyMatrix`, `Position`,
`Angle` and `TheTopologyCoordinate`. Then `GeometryPosition = Position -
CenterOfGravity` is done as one `vsub.xyzw`, so the fourth lane is
subtracted too. The centre of gravity stays in body space. It is not
rotated through the new body matrix the way
`CarState::CalculateGeometryPosition` does it, so on a tilted car the two
put the geometry in different places. That is kept.

### The check

`track_check` does the checking, because it has the topology loaded
already. It has six new ops:
- one each for the centre of gravity and a wheel of a `CarTypeInfo`;
- one to place the car;
- `FindFlatOnTrackPosition`, run on the model's `Car` at `0x01930000`,
  whose `pCarTypeInfo` is at +12;
- `PutFlatOnTrack`, with a TopologyCoordinate lent to the car for the call
  and handed back (nothing in one points into itself);
- `SetInterestBBox(bVector3)`.

Each call prints the position, the geometry position and the angle, the
whole matrix (filled with a sentinel first) and the last timing entry.

Two scenarios feed them:
- **The synthetic world.** It has a skew slope in 256ths, the two gaps, a
  cliff from 0 to 300, a floor at 30000 beside one at -40, and ground with
  nothing under it at all. It also has the saturating probes and six
  `PutFlatOnTrack`s, one of them twice.
- **TRACKB12.** Ninety probes stand 1.5 over the centroids of randomly
  chosen floor polygons, so each one lands on the road even under a
  bridge. Every one of them tilts.

Of 37 mutations to the slice, 36 are caught. The one that survives passes
NULL for the terrain, which is equivalent by construction: the local is
never read, and GetElevation's only use of the pointer is the store.

## What is in the sixth code slice

The reset group, in `carreset.c`:
- `ResetCore` (`0x001312c0`, 340 bytes);
- `ResetToPosition` (`0x00131418`, 104);
- `ResetToRoutePoint` (`0x00131480`, 252);
- `DebugSetPosition` (`0x001317d0`, 228).

Each one takes the car out of its movement mode, stands it on the ground
with `PutFlatOnTrack`, and puts the mode back, so the mover is torn down
and built again. That reaches `carmodes.c` and `cartrack.c` both, and
`car.c` links into checkers that carry neither, so the group has a file of
its own. `ReplayManager::RegisterInterestingEvent` (`0x0013c290`, 124) and
`InvalidateInterestingEvents` (`0x0013c310`, 20) came with it, in
`replay.c`, and `replay.h` now has the manager's first 116 bytes and a
snapshot's head.

### `ResetCore`

```
mode = TheMovementMode;  SetMovementMode(NO_MOVEMENT)
State.ResetCar();  TheTrackPathCoordinate.UpdatePosition(pos)
Angle = angle (andi 0xffff);  SteeringAngle = 0;  Position = *pos (lqc2/sqc2)
TheTopologyCoordinate.ClearInterestBBox();  ForwardSpeed = speed
PutFlatOnTrack()
bNormalize(&v, &BodyMatrix.v0, speed + 0.1);  Velocity = v (all four lanes)
VelocityMagnitude = sqrt((v.x*v.x + v.y*v.y) + v.z*v.z);  MatrixValid = 0
WheelAngularVelocity[i] = ForwardSpeed / Wheels[i].Radius,  i = 0..3
State.CalculateWheelMatrices();  pCarDriver->SetLowGear()   (slot 48)
SetMovementMode(mode)
if (pPlayer) pReplayManager->InvalidateInterestingEvents()
```

- **The velocity is along the body, and it is never zero.** It is row 0
  of the matrix `PutFlatOnTrack` just built, normalised to `speed + 0.1`
  (gp-32024, `0x3dcccccd`). A car reset at rest moves at a tenth.
  `VelocityMagnitude` is that vector's length, done on VU0 as
  `vmul.xyz`, `vaddy.x` and `vaddz.x`, so it is not the speed either.
- **The wheel speeds read `ForwardSpeed` back** from the state, once per
  wheel, and divide by each wheel's own radius.
- **`Position` is copied whole**, `pos`'s fourth lane with it. `z` is
  replaced by the ground. `x` and `y` are the ones the track path was
  measured from, before the car was set down.
- **The replay is not tested for NULL.** `lw a0,-23008(gp)` goes straight
  into the call when the car has a player. The port tests it, the one
  place in the slice where it differs on purpose. The port has no
  ReplayManager yet, so without the test a player's car would crash on
  its first reset. The image, run under mipsemu with a NULL manager, reads
  address 4 as 0 and does nothing either, and the checker has a case for
  it.

### The three that wrap it

- **`ResetToPosition`**: `ResetCore`, then `UpdatePosition` again from
  `Position`, whose `x` and `y` are `pos`'s still, then the controller's
  `FindWhereIAm` (slot 72) and `JustReset` (80), and `StopBlinking` as a
  tail call. `pCarController` is read from the car again for each of the
  two calls.
- **`ResetToRoutePoint`**: nothing at all without a route or without a
  point. Otherwise the position is the point's `x`, `y` and `Elevation`,
  built from three stores, and its fourth lane is a stack word nothing
  wrote. The heading is `bATan(Direction * direction)`, cut to sixteen bits
  by `ResetCore`'s `andi`, so a direction of -1 faces back down the route.
  After `ResetCore` and the second `UpdatePosition`, the controller gets
  `SetCurrentRoute(route, point)` (40) and `JustReset`. There is no
  `FindWhereIAm`. With `blink`, `StartBlinking(2.0)` follows.
- **`DebugSetPosition`** is the debug warp, and does none of `ResetCore`'s
  clearing. The state, the wheels, the driver and the replay are left as
  they were. `x` and `y` come from `pos`, and the track path is measured
  from `pos` itself. The heading is `angle` **plus** `bATan` of the track
  path's direction there, so it is relative to the road. It is stored in
  the state and read back for `bCos` and `bSin`, so it is the sixteen-bit
  one. Then `PutFlatOnTrack`, `ForwardSpeed = speed`, and a flat velocity,
  `speed` along the new heading with `z` a `sw zero`.

### `RegisterInterestingEvent`

While `CapturingFlag` is set, it walks `ReplaySnapshotList` (+108) and adds
`value` to `TotalInterestingValue` (+328) of every snapshot whose name
`bStrCmp`s equal to the string at `0x00292b80`, `INSTANT_REPLAY`. The
`description` argument is never read, so every caller's event lands on the
instant-replay snapshots and no others. `bStrCmp` is a signed-char
difference and only its zero is tested, so `strcmp` stands in.
`InvalidateInterestingEvents` passes `-99` and `"Invalidate"`.

### The check

`carmode_check` has the modes, the stand-in controllers and drivers and the
logged heap already, so it runs the resets too, after everything else.
- Fourteen `ResetToPosition`, `ResetCore` and `DebugSetPosition` calls and
  five `ResetToRoutePoint`s. Between them they cover the null, physics,
  mellow and stand-in movers, the null and a stand-in controller, a player
  with the replay capturing, idle and absent, a capturing replay with no
  player, and route direction 1, -1 and 0.5.
- The last three walk the track path. `UpdatePosition` keeps the point it
  had when the car has moved less than 128 units, and then looks only at
  that point's neighbours on the path, so it moves one point per call.
  From point 2, `150,40` reaches point 1 on the first update and point 0
  only on the second. `ResetToPosition` is sent there, then back to
  `50,90`, which leaves `ResetToRoutePoint`'s own `150,40` two points out.
  The second update in each wrapper is seen only this way, because its
  `x` and `y` are the first update's.
- The stand-in controller's entries 40, 72 and 80 log, and so does its
  driver's 48.
- The ground is the physics checkers' plane, asked for with no normal.
  `ClearInterestBBox` logs.
- The track path is a real one: a looping circle of twelve points, loaded
  through `LoaderTrackPath` with its QuickSplines' heap unlogged on both
  sides. So `PathDirection` turns, and `DebugSetPosition`'s heading is
  relative to something.
- The replay has five snapshots: two named `INSTANT_REPLAY`,
  `INSTANT_REPLAYS`, `INSTANT_REPLA` and `LAP`. Its free list is a real,
  empty ring.
- The route point's other floats are all distinct, so reading the wrong
  one shows.

Each reset prints the full step dump, then the track-path coordinate, the
blink timer and duration, and the five totals.

**The stack is poisoned and the run done twice.** Two words reach the
state from the stack: `ResetCore`'s `bNormalize` result's w, which is
copied into `Velocity`, and `ResetToRoutePoint`'s position's w. The port
writes 0 in both. The checker fills the 8 KB below `sp` at each of the
four entries, once with `0xC4424000` and once with `0x43A6A000`, and
merges the two transcripts. A line may differ between them only in the
fourth lane of a named vector. That covers `cs.Velocity`, `cs.Position`
and `cs.GeometryPosition`, plus the rebuilt movers' body and wheel lanes
those two feed. That token becomes `*` and matches whatever the port
printed. Any other difference stops the check. With just the two words
zeroed at their source, the two poisoned runs are identical, so nothing
else in the group reads the stack, and the mover constructors read
nothing of their own.

```
carmode_check  74 transitions, 19 resets, 32797 lines, 63 masked, 0 differ
```

No disagreement between the image and the port was found.

### What the mutation pass said

Seventy-four mutations for the slice, sixty-eight caught on the first
pass. The six that lived were three blind spots and three copies of work
`ResetCar` has already done.

- **Both second `UpdatePosition`s** (`rp-no-tpc`, `rr-no-tpc`) lived
  because every reset started from a coordinate that was either far away
  or already on its closest point. The first update then lands where the
  second would. The three walking resets above were added for them.
- **`if (pPlayer && pReplayManager)` to `if (pReplayManager)`** lived
  because no case had a capturing replay without a player. There is one
  now, and its totals stay where they were.
- **`SteeringAngle = 0`, `MatrixValid = 0` and `CalculateWheelMatrices`
  are equivalent**, and are recorded with their reasons. `ResetCar` zeroes
  the steering angle, clears the flag and builds the wheel matrices from
  zeroed angles and heights. Nothing `ResetCore` runs before its own copies
  touches any of those inputs: `UpdatePosition` writes only the coordinate,
  and only `GetTransformMatrix` sets the flag. The image does the work
  twice, and so does the port.

The whole of `carmode_check`'s pass, the fourth slice's 114 and these 74:

```
carmode_check --mutate  188 mutations, 185 caught, 3 equivalent, 0 unexplained
```

## What is in the seventh code slice

`AverageAir` (`0x00133e48`, 740 bytes) and `BeginMovement` (`0x001303a8`,
216), in `cartrack.c` beside the fifth slice. Between them they call only
GetElevation, `SetInterestBBox(bVector3)`, `HasTopology`, `bMulMatrix`
and `CarState::BeginTimestep`, all ported already, so `track_check` can
run them. `FinishMovement` is `AverageAir`'s one caller.
`BeginMovement` is the first thing in each of `Move`'s steps.

### `AverageAir`

```
*height = 0
down  = -(speed * ((FrontDownforce + RearDownforce) * 0.3) / Mass + 9.8)
M     = BodyMatrix rows 0..2, then Position with w = 1
acc   = sum over i of 0.25 * M * WheelMatrix[0] * (0, 0, -Wheels[i].Radius)
d0    = acc.z - GetElevation(acc)
n     = cvt.w.s(speed * *time * 0.33333334)
sum   = max(0, d0)
for i = 1 .. n-1:
    t = (*time * i) / n
    q = (fall * t + Velocity) * t + acc,   fall = (0, 0, down)
    d = q.z - GetElevation(q, normal)
    *height = max(*height, d)
    if !(0 < d): *time = t, i++, stop
    sum += d
return i == 1 ? sum : sum / i - 1
```

`speed` is `VelocityMagnitude`, read once.

- **Every wheel goes through `WheelMatrix[0]`.** The image loads the
  address `car+240` into `s3` before the loop and never steps it; only
  the radius moves on. So the start point is wheel 0's bottom, averaged
  over four radii. The port does the same. A mutation to
  `WheelMatrix[i]` is caught, because the checker's four matrices differ.
- **No half on the `t²` term.** The fall is `(g t + v) t`. With the
  downforce folded into `g`, the car falls faster at speed.
- **The mean has 1 taken off it**, and a sample that meets the ground is
  counted in `i` but not added to `sum`. So a car that is on the ground
  at its first sample returns `-1`, or less.
- **`*height` is zeroed before `*time` is read.** The checker has a case
  that passes the two as the same float. It gets no samples, and the
  start's clearance back.
- **`cvt.w.s` saturates.** From 10^10 × 1 the image asks for 0x7fffffff
  samples, and a car that starts under the ground stops at the first. A
  plain cast gives 0x80000000 on x86, and no samples. The checker has
  that case, and the one that saturates negative.
- The first GetElevation passes no out-parameters. The samples pass a
  normal, which nothing reads.

### `BeginMovement`

- **The old velocities are kept only for `0 < dt`**, `vOldVel` and
  `vOldAngVel` whole. `-0` does not count.
- **The interest box is `3 + speed / 20` round `Position`, led by
  `Velocity`.** Here `speed` is the velocity's own length, `x x + y y`
  and then `+ z z` on VU0, not `VelocityMagnitude`.
- **`LastInTroughPosition` takes `Position`'s x and y** when the car is
  over the topology and `nWheelsTouchingGround`, compared signed, is 2 or
  more.
- Then `CarState::BeginTimestep`, a tail call. It sets the four
  `CrossedWheelTerrain`s back to 1.

### The check

`track_check` has four new ops. Two set a car vector or word by number:
the body matrix, the two velocities, the four wheel matrices, the old
velocities, `Position`, the speed, the wheel count, the trough and the
type's mass and aero. The other two run `AverageAir` and `BeginMovement`
on the model's `Car`, with a TopologyCoordinate lent for the call as
`PutFlatOnTrack`'s is.

The scenario runs after the fifth slice's, on the same world. It starts
with twenty `BeginMovement`s:
- five values of `dt`, `-0` among them;
- seven wheel counts, including -1 and both extremes;
- positions over the gap, the cliff, the two high floors and nothing at
  all;
- a car whose speed and velocity disagree;
- a velocity whose length depends on the order it is summed in.

Then come sixty-five `BeginMovement` and `AverageAir` pairs, the order
`Move` and `FinishMovement` put them in:
- thirteen fixed flights over the slope, one with the time and height the
  same float;
- forty random ones;
- six over the gap, the cliff, the high floors and nothing;
- three that start under the slope, one of them too far under for the
  first pass;
- one that stays up for its whole window;
- two of a 2^-13 kg car, whose downforce is nearly all of `down`.

```
track_check  16149 ops, 11790 lines, 0 differ
```

No disagreement between the image and the port was found.

### What the mutation pass said

Sixty-two new mutations; the first pass caught 56. None of the six
survivors was a port bug:

- **Two are equivalent.** `air-first-normal` asks GetElevation for a
  normal and `air-sample-no-normal` stops asking. Either way the normal
  lands in a local nothing reads, and GetElevation only stores into the
  pointer.
- **`air-share-ulp`** moves the 0.3 by one ulp. At 1450 kg, gravity is
  nearly all of `down`, so the downforce term is lost in the rounding. Now
  a 2^-13 kg car is thrown up at `down` times its window. Near the end of
  the window the throw and the fall cancel, so one ulp of downforce
  becomes about ten ulps of height. The throw is set after
  `BeginMovement`, because a box built from that velocity would be 15000
  wide. The tree gathers only the squares under a box's four corners, and
  none of those would be the slope's.
- **`air-while-le`** takes one more sample. No flight used to last its
  whole window. Three do now.
- **`bm-speed-order`** sums the velocity the other way. The old fixture,
  (4096, 0.875, 0.875), does give radicands one ulp apart. But a square
  root halves a one-ulp difference, and this one rounds back to 4096. A
  search found (138.234375, 2.46875, 1.90625), whose speeds are one ulp
  apart and whose boxes are two ulps apart.
- **`air-no-floor`** drops the `max(0, d0)`. The new under-the-slope
  cases catch it. The old "under it" flight and a dozen random ones catch
  it too, but only now that the (4096, ...) velocity has been replaced.
  That velocity came before all of them, and nothing else before them
  changed. The likely reason: that car's box was about 420 wide.
  `SetInterestBBox` skips the rebuild while a new box fits inside the
  cached one, so every later flight over the slope used the table that
  box built from its four corners' squares. That is not yet confirmed.
  Run the mutant against the old velocity to check.

```
track_check --only (the 62)  62 mutations, 60 caught, 2 equivalent, 0 unexplained
```

The first 209 were rerun on their own after this slice's scenario was
added, and nothing moved:

```
track_check --only (the first 209)  209 mutations, 206 caught, 3 equivalent, 0 unexplained
```

## What is in the eighth code slice

The step, in `carmove.c`:
- `Move` (`0x00130200`, 388 bytes);
- `ChangeGear` (`0x00130ff8`, 120);
- `CalculateNewCatchupMultipliers` (`0x001334f0`, 220);
- `UpdatePosition` (`0x00130388`, 28).

`Move` is what the world calls for each car on each step. It reaches the
resets, so it has a file of its own for `carreset.c`'s reason. Four small
pieces came with it:
- `Timer` has its own header, `timer.h`, with `Timer::SetTime`
  (`0x00134ef0`) in `timer.c`. It was in `collisionbody.h`.
- `race.h` has the whole `RacingCar`, 192 bytes and thirty-seven Timers,
  and `Race::GetRacingCar` (`0x00146ad8`), which is `c->pRacingCar`.
- `player.c` has `Player::NumPlayers` and `pPlayersByNumber`.
- `difficultyinfo.{c,h}` has the 744-byte `DifficultyInfo` and its chunk
  loader and unloader, chunk `0x00034b00`.

### `Move`

```
CalculateNewCatchupMultipliers()
r = pCarMover->Move(dt)                         (slot 16)
UpdatePosition(&State.Position);  ChangeGear(State.CurrentGear)
if (ResetMe):
    ResetToRoutePoint(GetRoute(), GetRoutePoint(), 15.0, blink = 1, 1.0)
    ResetMe = 0;  return r
pen = GetLastPenetrationTime()
if IsBlinking() and pen is not 0 or 0x7fffffff
   and BlinkDuration - 0.5 < (WorldTimer - BlinkTimer) * tick
   and s = (WorldTimer - pen) * tick is in [0, 0.5):
    BlinkTimer += Timer::SetTime(0.5)           (2000 ticks)
return r
```

- **The mover's float is `Move`'s return on every path.** The reset and
  the blink come after it and do not change it.
- **The catchup comes before the mover's step**, so the step sees this
  step's `BoostFactor`.
- **`GetRoute` is called before `GetRoutePoint`.** The first port wrote
  the two as the reset's arguments. C leaves the order open and gcc on the
  host evaluates them right to left, so the checker's stand-in controller
  logged them the other way round. That was a port bug, not a
  disagreement: the port now calls them as two statements.
- **A reset leaves the blink alone.** `ResetToRoutePoint` starts its own
  blink, and `Move` returns before the tail. The NullController's route
  is NULL, so its reset does nothing, and the tail is still skipped.
- **The tail keeps a car blinking while it is still inside something.**
  A blink in its last half second, on a body that last penetrated less
  than half a second ago, is stretched by half a second. Both tests are
  strict. The penetration test is two, `s < 0.5` and then `0 <= s`, so a
  stamp after `WorldTimer` is not a penetration. Both elapsed times are a
  wrapping 32-bit subtract read as signed, like `IsBlinking`'s.

### `ChangeGear`

`DispGear` is the gear the animated driver has been told about. A change
out of neutral (1), or on a car with no driver model, is only stored.
Otherwise:
- leaving reverse (0) ends the backwards pose;
- every change queues the gear-change animation;
- going into reverse starts the pose.

`pAnimatedDriver` is read once for the test and the first call, then again
for each of the other two, as the listing does. Nothing builds an
AnimatedDriver yet, so its three methods are seams that abort if they are
reached unset.

### `CalculateNewCatchupMultipliers`

With a player, `Boost` on and exactly two players, `BoostFactor` is the
catchup graph at how far the car leads the other player, in metres. The
graph is TheDifficultyInfo's `TwoPlayerCatchup`, four knees, and a car
behind gets more than 1.
- **The lead is each car's own product, then the difference.** It is
  `me.laps * L - other.laps * L`, not `(me.laps - other.laps) * L`. On
  most leads the two agree once the graph's shallow slope has rounded
  them. The checker has two that do not, one ulp of boost apart.
- **The other player is `pPlayersByNumber[PlayerNumber == 0 ? 1 : 0]`.**
  A `PlayerNumber` of 1 or anything else reads player 0.
- Neither the entry nor either `RacingCar` is tested for NULL. The Graph
  is built on the stack for each call.

### `UpdatePosition`

The Espresso editor's live link: with an editor object, the car's position
goes to `espSetObjectPosition`. The only store into `pCaffeineObj` in the
image is the constructor's zero (`0x0012f514`, `sw zero,1992(s2)`). So on
the disc the arm is dead, and the port's seam aborts if it is ever
reached unset.

### The check

`carmode_check` runs the step after the resets, on the same world.
- **The difficulty table is GLOBALB.BUN's own.** It is read from offset
  761472. The unloader is asked about it and about a copy with a wrong
  id, and the loader is given the bad one first, which copies nothing.
- **Seventy steps**, the first one before the table is loaded. They
  cover:
  - the dispatch under the three real movers and the four stand-ins,
    whose `Move` logs and answers 0.5, 0.75, … in turn;
  - the editor link;
  - eleven gear changes, among them 0 to 0, a negative gear and a car
    with no driver model;
  - four resets: under a stand-in controller, under the NullController
    with and without a blink the tail would have stretched, and a
    `ResetMe` of -7;
  - twenty-five blink tails. They sit at each edge of both windows, on
    both sentinels and the stamps next to them, and past 2^31. Four of
    them set `WorldTimer` a quarter second past a sentinel or its
    neighbour, so that the stamp falls inside the window;
  - eighteen catchups: player 0, 1, 5 and -1, `Boost` 0 and -1, one and
    three players, no player, leads either side of each knee, and the
    two rounding cases;
  - one with all of it at once.
- **The stand-ins have three new entries.** Each mover's `Move` (16) logs,
  and each controller's `GetRoute` (48) and `GetRoutePoint` (56) log and
  answer the resets' route and point. The AnimatedDriver's three methods
  and `espSetObjectPosition` log.

Each step prints the answer, the two gears, `ResetMe`, the blink timer and
duration, and `BoostFactor`, which is set to 0.8125 before each one. Seven
also print the full step dump.

**One more lane is poisoned.** The body's `State` at 96, the angular
momentum, takes a stack word's fourth lane through the physics step that
follows a reset. It is in the merge's list beside the others.

```
carmode_check  74 transitions, 19 resets, 35405 lines, 103 masked, 0 differ
```

No disagreement between the image and the port was found.

### What the mutation pass said

Seventy-nine mutations for the slice, seventy-two caught on the first
pass. Of the seven that lived, two are equivalent, two missed the code
they were meant for, and three found a blind spot.

- **Two are equivalent**, and are recorded with their reasons.
  - `mv-s-unsigned` reads the penetration's elapsed time unsigned. A
    stamp after `WorldTimer` is a negative difference, which fails
    `0 <= s`. Read unsigned, it is at least 2^31 ticks, which fails
    `s < 0.5` instead.
  - `tm-plain-cast` truncates `SetTime` with a C cast in place of
    `cvt.w.s`. `Move`'s only call is `SetTime(0.5)`, which both truncate
    to 2000.
- **The two that pick the other player** (`cu-pick-inverted` and
  `cu-pick-by-one`) edited the comment above the code, which spells the
  same index. A pass replaces the first match, and the comment came first.
  The patterns now start at `c->pPlayer->`, and both are caught. No other
  mutation in the checker hits a comment first.
- **The three on the sentinels** (`mv-pen-zero-ok`, `mv-pen-max-ok` and
  `mv-pen-max-off`) lived because `WorldTimer` was `0x12345` for every
  step. Against that, a stamp of 0 is eighteen seconds old and a stamp of
  `0x7fffffff` is negative, so both failed the window without the
  sentinel test. Each case now sets its own `WorldTimer`. Four new cases
  put it a quarter second past 0, 1, `0x7fffffff` and `0x7ffffffe`. The
  two sentinels are left alone, and the stamps next to them stretch.

```
carmode_check --only (the 79)  79 mutations, 77 caught, 2 equivalent, 0 unexplained
```

The fourth and sixth slices' 188 were not rerun. The step runs after
everything they are caught on, so it cannot hide what they changed.

## What is in the ninth code slice

The methods of Car that make one call out of it, in `carrace.c`:
- `GetDistanceAndSpeed` (`0x001326b0`, 32 bytes), which is static;
- `FixBlownTires` (`0x00133450`, 44);
- `TriggerTireBlowOut` (`0x00133368`, 232);
- `PleaseResetMeLater` (`0x00131580`, 108);
- `GetDrivingLineSpeed` (`0x00131700`, 60);
- `DeliverMeFromEvil` (`0x001326d0`, 108).

That is 584 bytes, and Car is 61 of 80 methods. The file is apart from
`car.c` for `carreset.c`'s reason: `DeliverMeFromEvil` reaches
`SetMovementMode`, and `FixBlownTires` reaches RealDriver. Three small
pieces came with them:
- `carcollisionbody.c` has `DynamicCollisionBody::GetDistanceAndSpeed`
  (`0x001cd068`, 12 bytes). It is a stub on the disc,
  `sw zero,0(a0); jr ra; lwc1 $f0,0(a0)`, so the distance and the speed
  between any two cars are both 0.
- `race.h` has `TheRaceParameters.nMaxCops` (`0x0031277c`) as
  `RaceParametersMaxCops`.
- `car.h` has all twenty-six `CarEffect`s (type#1034).

### What each does

```
GetDistanceAndSpeed(d, a, b)   DCB::GetDistanceAndSpeed(d, a->pDCB, b->pDCB)
FixBlownTires()                BlownTireBits = NumBlownTires = 0, timer = 0
                               REAL_CONTROL: ForceEBrakeStop(pCarDriver, 0)
TriggerTireBlowOut(mask)       NumBlownTires = 0, timer = 7.0
                               BlownTireBits |= mask
                               for i in 0..3, if bit i is blown:
                                   NumBlownTires++
                                   if bit i is in mask:
                                       TriggerEffect(BLOWN_TIRE, 1.0,
                                                     0x50000 + i * 0x10000,
                                                     NULL)
                               pBaseCarSound: its TriggerTireBlowOut
PleaseResetMeLater()           ResetMe = 1, unless BeACop, nMaxCops > 0,
                               MyDriver is an AI racer, and
                               pCopManager->IsBeingPursued(this)
GetDrivingLineSpeed()          AI or TRAFFIC control: the controller's
                               GetCurrentDrivingLineSpeed; otherwise 0
DeliverMeFromEvil(p, a, s, t)  SetMovementMode(DELIVERY)
                               pCarMover->SetDestination(p, a, s, t)
```

What the listing says:
- **The count covers every blown tyre, and the effect only the mask's.**
  `TriggerTireBlowOut` clears `NumBlownTires`, then counts each of the
  four bits set after the `or`, old and new. The increment's store is in
  a branch delay slot, so a blown tyre is counted whether or not the mask
  has it. The effect goes off for each tyre in the mask, including one
  that was blown already.
- **Bits past the fourth tyre are kept.** The byte takes the whole `or`,
  and the loop looks at four bits.
- **The 7.0 is an immediate** (`lui 0x40e0`), not a gp constant.
- **`FixBlownTires` reads the mode before its three stores.** Nothing
  between them changes it, so the order is only the listing's.
- **`nMaxCops` is compared signed** (`blez`), and **the cop manager is
  passed untested** from gp-16500. So a car the cops are chasing in Be a
  Cop is not reset.
- **`DeliverMeFromEvil` reads `pCarMover` after `SetMovementMode`**, so
  `SetDestination` goes to the new DeliveryMover. The angle is masked to
  16 bits (`andi`) before the call. Under DELIVERY_MOVEMENT already,
  `SetMovementMode` still builds a new mover. The check's transcript shows
  the old one destroyed first.

### The seams

Five calls go to classes the port does not have yet:

```
tCopManager::IsBeingPursued                  0x00213128  task 26  aborts
AICarController::GetCurrentDrivingLineSpeed  0x0018ad18  task 26  aborts
DeliveryMover::SetDestination                0x001f0ba0  task 26  aborts
Car::TriggerEffect                           0x0011e328  task 27  skipped
BaseCarSound::TriggerTireBlowOut             0x00185200  task 29  skipped
```

The first three give the car an answer or move it, so reaching one unset
aborts, in `carmodes.h`'s style. The effect and the sound are only seen and
heard, so an unset one is skipped, in RealDriver's style. `TriggerEffect`
is Car's own method, 720 bytes, but it is one of the six compiled into
other objects. It belongs with the effect system, the render group that
task 27 inherits. Nothing sets any of the five yet.

### The check

`carmode_check` runs one more scenario after the steps. On the image's
side, the five seams and `RealDriver::ForceEBrakeStop` are stubbed. On the
port's side, the harness sets its own stand-ins, and each side logs the
arguments. The cases:
- `GetDistanceAndSpeed` both ways between the two cars, over a marked
  speed word;
- `FixBlownTires` under each of the five control modes;
- `TriggerTireBlowOut` over ten masks and prior bits: one new tyre, all
  four, one next to blown ones, the same two again, none, bits past the
  fourth, -1, a mask past the byte, and no sound;
- `PleaseResetMeLater` over twelve settings of `BeACop`, `nMaxCops` (0,
  -1 and `INT_MIN` among them), the driver's type, the cop manager's
  answer, and a NULL cop manager;
- `GetDrivingLineSpeed` under each control mode;
- `DeliverMeFromEvil` from four movement modes, DELIVERY among them, with
  an angle word past 16 bits.

```
carmode_check  74 transitions, 19 resets, 35602 lines, 103 masked, 0 differ
```

### What the mutation pass said

There are forty-three mutations for the slice, and forty-one were caught on
the first pass. The two that lived, `blow-where-base` and
`blow-where-step`, repeat the eighth slice's lesson. The comment above
`car_trigger_tire_blow_out` spells the same sum as the call, so the
mutants edited the comment. Their patterns now include the call's
`, NULL);`, and both are caught.

```
carmode_check --only (the 43)  43 mutations, 43 caught, 0 equivalent, 0 unexplained
```

## What is in the tenth code slice

One method, in `careffects.c`:
- `TriggerCarTerrainEffects` (`0x00131db8`, 1872 bytes).

That makes Car 62 of 80 methods. It has a file of its own for
`carrace.c`'s reason: it reads the terrain table and the topology and asks
the body damage, and `car.c` links into checkers that carry none of them.
Its one caller is `World::DoTimestep` (`0x0014b914`), which is not ported.
That passes the distance to the closest player, and calls only under 150
when `ShouldVisualEffectsBeGenerated` agrees. So from there the skid
smoke's own test against 150 always passes.

### A finding first: `NumTimesSkidding` is four bytes

The stab gives Car's `NumTimesSkidding` at 1984 as `ar1;0;3;11`, which is
`unsigned char[4]`. The listing agrees: a `lbu` and a `sb` a wheel, and
`pminw` against 255. `car.h` had one `int32_t`. It is `uint8_t[4]` now.
The offset is unchanged, so no layout moved. `car_check`'s fixture and its
one mutation name `NumTimesSkidding[0]`, and nine checkers still give 0
differ.

### What it does

```
for each wheel on the ground, in order, where = 0x50000 + i * 0x10000:
    ti = the wheel's terrain
    puddle, deep water, mud puddle (4, 5, 20): the wheel's bit in wet
    mag = |slip|
    distance < 150 and skid min < mag:
        n = NumTimesSkidding[i] + 1, at most 255, stored
        a smoke group: s = (mag - min) / (max - min)
            n < 2: 0    n < 20: s/4    n < 60: s/2    n < 120: 3s/4
            clamp to 0..1; above 0: SKID_SMOKE(s, where + terrain)
    otherwise NumTimesSkidding[i] = 0
    distance < 40, wheel 2 or 3, spew min < slip.x, a spew group:
        s = clamp((slip.x - min) / (max - min))
        above 0: TIRE_SPEW(s, where + terrain,
                           WheelMatrix[i] * (slip.x, slip.y, 0) + Velocity)
three or four wheels down:
    terrain = GetElevation(Position)'s
    drive, drive2 = each window's clamp, if its group's first byte is set
    drive + drive2 above 0:
        over = drive + drive2 - 1; above 0: the one whose window starts
            lower (the second, on a tie) loses 2 * over, floored at 0
        DRIVE_OVER(drive), DRIVE_OVER2(drive2), each above 0, at terrain
    s = clamp((the four bottom-outs summed - min) / (max - min))
    above 0: BOTTOM_OUT(s, terrain)
distance < 60, wet > 0, 10 < VelocityMagnitude:
    TurnWipersOnForDuration(now + 60, now + 180)
    pBaseCarSound: TriggerSplash((wet & 6) != 0, deep water ? 3 : 1)
pCarDamage: radiator bits set: DAM_RADIATOR
            0.8 < visible total damage: DAM_ENGINE
NitroEffectFlag, or a player's physics car's engine on nitro: NITRO
NumBlownTires: each blown tire on the ground:
    DRIVE_ON_FLAT_TIRE(clamp((mph - 4.470272541) * 0.04474), where)
```

What the listing says:
- **The count is kept whether or not the terrain smokes.** A wheel over
  the minimum counts its frame even with no smoke group, and any other
  wheel on the ground is cleared. A wheel in the air keeps its count.
- **The first frame shows nothing.** The ladder's `n < 2` gives 0, so
  smoke starts on a wheel's second frame of skidding.
- **Tire spew reads the slip's x, not its length**, and only for the rear
  two wheels. The point is the whole wheel matrix times `(x, y, 0)`,
  translation and all, and then `vadd.xyzw` adds the velocity in all four
  lanes, pad included.
- **The ground is the car's own**, from `GetElevation` at `Position` with
  only the terrain asked for, and only with three or four wheels down.
- **The drive-over pair test only their names' first bytes**, with no
  NULL test. Bottom-out has no group test at all, so a puddle bottoms out
  though it names no group.
- **Twice the excess.** When the two drive-overs come to more than 1, the
  one that starts at the lower speed gives up `over + over`. On a tie
  (`c.lt.s` false) that is the second.
- **`wet` is tested signed** (`blez`). "Right" is wheel 1 or 2 wet, the
  mask 6.
- **The radiator is breakable item 14**, bits 28 and 29 of the word. Any
  damage at all and it steams.
- **Both blown-tire bytes are read signed** (`lb`). The flat tire's scale
  has no test above 0, so a tire under 2 m/s is passed on at 0.
- **The terrain table is indexed with `madd`**: the table's address goes
  into `lo` by `mtlo`, and the R5900's three-operand multiply-add leaves
  `base + terrain * stride` in the register. The model had never met it,
  or `pminw`. `mipsemu.py` has both now.
- **The where.** The two wheel effects name the wheel and add the terrain.
  The ground's three name the terrain alone. The damage and nitro
  effects name 0.

### The seam

One call goes to a class the port does not have yet:

```
BaseCarSound::TriggerSplash  0x00185038  task 29  skipped
```

It is only heard, so an unset one is skipped, as `TriggerTireBlowOut`'s
is. `car.h` gives its 24 bytes as a comment. `TriggerEffect` is the
ninth slice's seam again.

### The check

`carmode_check` runs one more scenario after the ninth slice's. Both
sides place the car, set its velocity, and give each wheel its own matrix.
Then fifty-four cases set the wheels and the ground, the distance, the
speed, the damage, the player, the nitro, the blown tires, the sound, the
wipers and the frame clock. The ground is set only around the call, so
the physics car's own setup reads the checker's plane as before. The
effect logs its point's four lanes when it has one, and the splash logs
its two arguments. The cases:
- no wheel down, and too far for smoke;
- the count ladder at each of its edges, 254 and 255 among them;
- a length exactly at the minimum, no smoke group, and dirt's narrower
  window;
- tire spew on the rear two, at 40 and under, with a slip under the
  minimum and a terrain with no group;
- two wheels down, and a touch byte of `0x80`;
- the splash left and right, 1 and 3, with no sound, at 60 and at
  10 m/s, a wet wheel in the air, the wipers running, and a window open;
- terrain 4's drive-over window moved, three ways: to tie the second's
  minimum, to lie above it, and to lie above the speed;
- bottom-out on the road, in a puddle, and on no terrain, and three
  wheels down with the fourth's bottom-out counted;
- snow, whose drive-over window has no group;
- the radiator's bits and the visible damage's edge;
- the nitro flag, and the engine's flag under PHYSICS with a player and
  without, and a player under no movement;
- the blown tires: bits with a count of 0, a blown tire in the air, a car
  slow enough for a scale of 0, a fast one, and bytes of `0x80` and
  `0xf8`.

```
carmode_check  74 transitions, 19 resets, 35875 lines, 103 masked, 0 differ
```

### What the mutation pass said

There are 107 mutations for the slice. On the first pass, 104 were
caught and 3 survived, and all three are equivalent by construction:
- `fx-spew-pad-ignored`: `bMulMatrixVec3` forces the vector's w to 1, as
  the image's `bMulMatrix` does, so the pad the port writes is never
  read.
- `fx-spew-by-mag` and `fx-spew-min-le`: the spew's gate against its
  minimum. The scale is `(slip.x - min) / (max - min)`, which is at most
  0 wherever the gate could differ, and only a scale above 0 goes off.
  The slip's length is never below its x.

`fx-damage-no-test` drops the NULL test on `pCarDamage`, and the harness
crashes on the first case without damage. That counts as caught.

```
carmode_check --only (the 107)  107 mutations, 104 caught, 3 equivalent, 0 unexplained
```

## What is in the eleventh code slice

One method, in `carfinish.c`:
- `FinishMovement` (`0x00130480`, 2008 bytes).

That makes Car 63 of 80 methods. It has a file of its own because it
reaches Collision, the world's car table and the Player, and `car.c`
links into checkers that carry none of them. Its one caller is
`World::DoTimestep`, ported with World's timestep in task 27. That calls
it for every car once the moves and the collisions are done, through
`gCarFinishMovementFn`, which aborted while unset. `main.c` sets it now.

### What it does

```
0 < dt:  Acceleration        = (Velocity - vOldVel) * (1 / dt)
         AngularAcceleration = (AngularVelocity - vOldAngVel) * (1 / dt)
speed = VelocityMagnitude
!(speed < 0) and !(1000 < speed):  Odometer += speed * dt
the track path coordinate's UpdatePosition(Position)
(loop + 7) & 31 == 0, a movement mode, no topology at Position
    nor at Position + (1, 0):  ResetMe = 1
off = |coordinate - its point| in the plane, 0 with no point
off > 5000:  ResetMe = 1, unless BoringAIForCameraTuningOn
else off > 300, loop % 60 == 0, a movement mode:  ResetPosition(Position)
UpdateHeadlightsAndHorn
no player: done
in zone 6 or 7 with a wheel down:  ClearZone(sound)
(loop + 3) & 7 != 0: done
40 < speed, fewer than 4 wheels down, |yaw| < 3.14/32:  CarInAir, 2
not g_DisableAutoReplay, in neither zone, no wheel down, not the wrong
way, 30 < speed:
    t = 3, AverageAir(&t, &h), now = WorldTimer * 0.00025
    AirTimeSwitch = t < 0.9 ? now + 5 : t * 0.5 + now
    1.5 < h, 0.5 < t, IsJumpCamAvailable:
        RequestZone(6, 0, 1, 1), and CleanUpJumpCam if it says no
    zone read again
in zone 6:
    falling, and EyeVerts[2].z below Position.z:  EyeVerts[2].z = Position.z
    AirTimeSwitch < now:  ClearZone(no sound), RequestZone(7, 0, 0, 1)
40 < speed:  CloseCars, half a point for each AI car within 40
30 < speed:
    3.14/8 < |yaw|:  CarSlidingSideways, 1
    the body's first collision, a player's car in it, touched less than
    half a second ago:
        two cars and 40 < speed:  CarCollision, 3
        else a smokeable body and 30 < speed:  SmokeableCollision, 5
```

`loop` is `WorldLoopCounter`. `speed` is read again once the eighth-step
test passes, and the rest of the method uses that value.

What the listing says:
- **The accelerations are VU0's**, `vsub` and `vmulx` over all four lanes,
  pad included. `-0` is not positive. A denormal `dt` is, and the EE's
  `div.s` reads it as zero, so `1 / dt` is `ee_div`'s FLT_MAX.
- **The odometer's tests are both `<`**, so a NaN speed is added, and at
  a speed of `+0` a `-0` odometer becomes `+0`.
- **The phases never meet.** The topology runs on `loop ≡ 25 (mod 32)`,
  the player's section on `loop ≡ 5 (mod 8)`, and the search on a
  multiple of 60. The first two are odd and never the same residue; the
  third is even. The remainder is signed, so `-60` searches too.
- **The topology is asked twice**, at the car and a metre along +x, and
  only a miss at both marks the car.
- **The distance is worked out twice**, the same way, both times from the
  point the coordinate holds after its update. A car past 5000 is never
  searched afresh, even when the camera tuner keeps it. With no paths at
  all there is no point, and the distance is 0.
- **The yaw is `CarState::GetYaw`'s**, which is 0 below a `ForwardSpeed`
  of 5. So a car moving sideways at 50 counts as flying straight.
- **AverageAir starts from three seconds.** `AirTimeSwitch` becomes half
  the jump or, for one under 0.9 s, five seconds.
- **`EyeVerts[2].z` keeps the highest point**: while the car falls it only
  ever rises to meet it. The test is `<`, so a `-0` under a `+0` car stays.
- **The first `RequestZone` skips the zone's own timer**, and only its
  answer decides the clean-up. The zone is read again after it, so a
  request that took shows in the next test at once.
- **CloseCars runs `AICarPos` up to `CopCarPos`.** The world is not tested
  for NULL, and the car itself is not skipped. Only a player's car gets
  this far, so it would count itself only from inside that run.
- **The contact's age is signed**: `WorldTimer` minus the stamp as an
  `int32`, times the tick. A stamp in the future is less than half a
  second old.
- **RegisterInterestingEvent is called with no test** on
  `pReplayManager`. The port tests it, as `carreset.c` does, because
  there is no ReplayManager yet. The event's name is never read.

Three things in the listing are left out, because they change nothing:
- After CarCollision it asks for the colliding cars and swaps the two
  when the second is the player's own. Nothing reads either afterwards.
  The call is kept; it only reads.
- The tail, reached when `DoScreenPrintf` or `TerminalPrintPosition` is
  set and the camera follows this car. It calls
  `Race::AreAllPlayersFinishedRacing`, `GetCurrentZoneNumber`,
  `DisplayCullingStats` and `Race::GetRacingCar`, each for a print that
  was compiled out. Both switches are 0 in the image.
- The second `30 < speed` before the smokeable, which the first has
  already passed.

`g_DisableAutoReplay` (`0x00323040`) is Car.obj's, and 0 in the image. It
is in `car.c`.

### The seams

Four calls go to the Player, which task 26 has not brought yet:

```
Player::ClearZone(bool)            0x00171c70  aborts if unset
Player::RequestZone(int, 3 bools)  0x00171610  aborts if unset
Player::IsJumpCamAvailable         0x00170408  aborts if unset
Player::CleanUpJumpCam             0x00170488  aborts if unset
```

They move the camera between zones, which changes the game, so an unset
one aborts. Only a player's car reaches them. `player.h` names the three
fields the method reads, `nZoneCurrent` (76), `bWrongWay` (736) and
`EyeVerts` (1600), with a layout check. `TrackPathCoordinate::ResetPosition`
(`0x00134f18`, in Car.obj) is in `trackpath.c`: it forgets the point, then
updates.

### The check

`carmode_check` runs one more scenario after the tenth slice's. Both sides
set the car to no control, and make a player, a world with a five-car
table (the car, then four others), a Collision, a witness and a plain
body. Each case sets the velocities, the old velocities, the position,
the odometer, the speed, the wheels, the yaw's two inputs, the track path
coordinate, the counters and switches, the player's three fields, the
table's positions and, if it has one, the collision. The topology's
answers are scripted, one per question, and a leftover answer fails the
case. The four Player calls log, and `RequestZone` answers as the case
says and moves the player when it says yes. The replay's snapshots are
zeroed before the call and printed after it, which is where the events
show.

The 105 cases:
- `dt` at 0, negative, `-0`, a denormal and 2;
- the odometer at 0, `-0`, below 0, at 1000, above it, NaN, and `+0` on a
  `-0` odometer;
- the topology on and off its phase, each answer pair, no movement mode;
- lost exactly at 5000 and one float past it, and kept by the tuner;
- searched afresh: exactly 300 and one float past it from a point that a
  search stops at though another is nearer, at loop 0, 60 and -60, off
  the phase, with no movement mode, and lost from there at 5100;
- no paths at all;
- a player off the eighth step: the zone clear in both zones, with and
  without a wheel down, and loop 9, which a mask of 15 or 3 would take;
- a jump the jump cam takes, falling and not, and each thing that stops
  or undoes it;
- AverageAir's edges, found by reading the image's frame after the call:
  exactly 0.9 s, exactly 0.5 s, exactly 1.5 high and the next float up,
  and never down in three seconds;
- the speeds at 40, just over 30 and at 30;
- the yaw at 1023 and 1024 BAM either way round, and too slow to have one;
- the jump cam's zone: the height kept while falling, `-0` under a `+0`
  car, the switch either side of now and at it, and the zone after;
- CloseCars: one, three, three at exactly 40, two just inside, two off
  the axes either side of 40, the car itself when the run starts at it,
  a run one slot longer, no AI, a run that ends before it starts, and a
  speed of 40;
- sliding at 4093 and 4094 either way round, and at a speed of 30;
- the collision: two cars above 40, at it and under it, a smokeable
  either way round, a static body, a witness with no Collision, the half
  second at 1999 and 2000 ticks, a stamp 100 ticks in the future and
  one 2^31 away, a car's own body that is not a car's, and no replay.

The poison runs cover it: the stack is scrubbed around the call, and no
line of the scenario is masked.

```
carmode_check  74 transitions, 19 resets, 36396 lines, 103 masked, 0 differ
```

No disagreement between the image and the port was found.

### What the mutation pass said

There are 88 mutations for the slice. Four of the cases were added for
them before the pass: `+0` on a `-0` odometer, loop 9, the `-0` height
and two cars at exactly 40. Each one splits a `<` from a `<=`, or a mask
from a narrower one, that no other case did. The first pass then caught
82, and the 6 that survived are equivalent by construction:
- `fm-air-yaw-le` and `fm-slide-le`: the yaw's `<` and `<=`. GetYaw is a
  BAM difference, one of 65536, times `BAM_TO_RAD` and folded past pi. A
  scan of all of them finds none exactly on 3.14/32 or 3.14/8. The
  nearest are 1023 and 1024 (and 64512 and 64513) for the first, and
  4093 and 4094 (and 61442 and 61443) for the second. The cases sit on
  those.
- `fm-air-name`: RegisterInterestingEvent never reads the event's name.
- `fm-col-no-colliding-cars`: the call's two answers are never read.
- `fm-col-smoke-no-else`: the first branch needs two car bodies, and then
  neither is smokeable.
- `fm-col-smoke-no-speed`: the second `30 < speed`, which the first has
  passed, on a local nothing in between changes.

Six mutants crash the harness, which counts as caught. The four that
move, widen or cut short the topology's test either reach it with no
answer scripted or leave one over. `fm-close-with-cop` reads a NULL slot
past the table's cars. `fm-replay-untested` calls into no replay on the
case that has none, which is the one place the port adds a test the
image does not have.

The rest of `carmode_check`'s mutations stand: the new scenario only adds
lines after the others, so nothing caught before can be missed now, and
the eight equivalents from the earlier slices were rerun and still
survive.

```
carmode_check --only (the 88)  88 mutations, 82 caught, 6 equivalent, 0 unexplained
carmode_check --only (the 8)   8 mutations, 0 caught, 8 equivalent, 0 unexplained
```

## What is not ported yet

The measure that matters for planning is whether a method makes a direct
call — a `jal`, or a `j` out of its own body — to anything that is not a
Car method. Scanned over all eighty, that splits them 34 and 46.

Of the **thirty-four that make no outside call**, thirty-three are
ported — `SetToPhysicsMode` and `SetFrictionBoost` came with the fourth
slice and `PutFlatOnTrack` with the fifth. The one left is
`DoWheelForces`, which is `if (pPlayer) CalcForceParameters(...)`, and that
is force feedback — six `PortSetForceConditionData`, six
`PortSetForcePeriodicData`, `PortPlayShake`. It drives the wheel
peripheral's motors, not the physics.

Of the **forty-six that do**, thirty are ported: `CalculateDraftFactor(Car *)`,
whose calls are Graph and Table; `WorldToCar`, whose one is
`CarState::WorldToCar`; the third slice's seven; `SetControlMode` and
`SetMovementMode`, whose outside calls are the movers' and controllers'
constructors — eight of them task 26's, reached through seams
([car-modes](car-modes.md)); `FindFlatOnTrackPosition`, whose are
GetElevation and the four `eMath` matrix calls; the sixth slice's
four, whose are the track path, the topology, `bNormalize`, `bATan`,
`bCos`, `bSin` and the replay; the seventh slice's two, whose are
GetElevation, the two `SetInterestBBox`es, `HasTopology`, `bMulMatrix` and
`CarState::BeginTimestep`; and the eighth slice's four, whose are
`Timer::SetTime`, the three AnimatedDriver methods, `Race::GetRacingCar`,
the Graph and `espSetObjectPosition`; and the ninth slice's six, whose are
`DynamicCollisionBody::GetDistanceAndSpeed`, `RealDriver::ForceEBrakeStop`,
the cop manager, the AI's controller, the DeliveryMover and the car's
sound; and the tenth slice's one, whose are GetElevation, `bMulMatrix`,
`BodyDamage::GetVisibleTotalDamage`, `TriggerEffect` and
`BaseCarSound::TriggerSplash`; and the eleventh slice's one, whose are the
track path's `UpdatePosition` and `ResetPosition`, `HasTopology`,
`CarState::GetYaw`, four Player methods, `CollisionBody::GetCollision`,
Collision's four questions and the replay. The AnimatedDriver, the editor
link, the ninth slice's four classes that are not ported, the splash and
the Player's four are seams.

Seventeen are left, and every one reaches a class that is not ported:
- the constructor and destructor (`0x0012f240`, `0x0012f660`);
- `TriggerEvents` (`0x00131a58`): the event manager, the ferns,
  `Player::TriggerVisibleDrivingLine`;
- `AssignAnimatedDriver` and `UnAssignAnimatedDriver`;
- `DamageAbove` and `DamageCap`: `ePoly`, `Player::IsNisPlaying` and the
  cop manager;
- the render group: `InitRenderInfo`, `CloseRenderInfo`,
  `TriggerEffect` and `SwitchSkin`;
- force feedback and rumble: `DoWheelForces`, `CalcForceParameters`,
  `StartForceImpact`, `MaybeRumble` and `MaybeCameraShake`;
- `DoSnapshot`, which waits on `ReplaySnapshot`.

They belong to tasks 26, 27 and 29. The constructor is the nearest: it
builds the null controller, driver and mover the fourth slice ported
(`car_new_null_controller` is the first two), but among the sound and
render objects that are task 29's.

The debt the third slice carried is paid: `wheel_install_seams()` runs
once at boot in `main.c`, before anything can build the `PhysicsCar`
whose `Suspension` needs it ([car-wheel](car-wheel.md)).

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
