# Car

The hub of task 25, and deliberately not its physics. Eighty methods and
22876 bytes — seventy-four of them, 20460 bytes, in `Car.obj`
(`0x0012f150 .. 0x00134f6c`), and six the compiler emitted in other objects
— and a 2016-byte record. The simulation itself lives in the movers that
`SetMovementMode` constructs. Car owns the
state they write into, the lights, the horn, the wipers, the blown tyres
and the blinking, and it hands everything else off.

Ported in slices. This document covers the record, which is whole, and
two code slices. The first is the seventeen methods that reach nothing
outside Car, CarState and the two world clocks, plus `Car::WorldToCar`,
which reaches only a CarState method ported since. The second is the
vtable seam, the nine methods that are pure dispatch through it, three
fields Car borrows from other classes, the draft, and the object's static
initialiser. Thirty-two of the eighty methods are ported, 2316 of the
22876 bytes.

Ported to `3DS Files/source/car.{c,h}`, `topology.h`, `vtable.{c,h}`,
`world.{c,h}`, `collisionbody.h`, `carcontroller.h`, `sound3d.h` and
`sinit.{c,h}`. Cross-checked by `tools/car_check.py` — 42 scenarios, 3864
lines, 0 differing; 178 mutations, 169 caught, 9 equivalent, 0 unexplained — and the boot walk by
`tools/sinit_check.py`, 6 mutations, 6 caught.

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

## What is not ported yet

The measure that matters for planning is whether a method makes a direct
call — a `jal`, or a `j` out of its own body — to anything that is not a
Car method. Scanned over all eighty, that splits them 34 and 46.

Of the **thirty-four that make no outside call**, thirty are ported. The
other four:

- `SetToPhysicsMode` dispatches through the controller, and its other arm
  tail-calls `SetMovementMode(MELLOW_MOVEMENT)`, whose jump table
  constructs every mover. It comes with `SetMovementMode` and PhysicsCar.
- `SetFrictionBoost` stores into `PhysicsCar` at +108 when the car is under
  `PHYSICS_MOVEMENT`: PhysicsCar's slice.
- `DoWheelForces` is `if (pPlayer) CalcForceParameters(...)`, and that is
  force feedback — six `PortSetForceConditionData`, six
  `PortSetForcePeriodicData`, `PortPlayShake`. It drives the wheel
  peripheral's motors, not the physics.
- `PutFlatOnTrack` goes to `FindFlatOnTrackPosition`, which needs a real
  `TopologyCoordinate` (task 27).

Of the **forty-six that do**, two are ported: `CalculateDraftFactor(Car *)`,
whose calls are Graph and Table, and `WorldToCar`, whose one is
`CarState::WorldToCar`. Six more call nothing outside Car that is not
already ported, and they are the next slice:

| Method | Size | Its outside callee |
|---|---:|---|
| `IsCarToLeft`, `IsCarToRight` | 68 + 68 | `CarState::WorldToCar`, ported |
| `GetRelativeCarPosition` | 220 | `bNormalize2`, ported |
| `GetPostCollisionYawControlBoost` | 132 | `Graph::GetValue`, ported |
| `IsDrifting` | 116 | `CarState::GetYaw`, ported |
| `ComputeFakeRPM` | 576 | `smooth<float>`, a 52-byte template in `Car.obj` |

`IsCarInFront` (124) is one step further: its only callee is `bToPolar`
(`0x002424a0`), which the math library port has not brought over yet.

Everything else — the constructor and destructor, the reset and damage
groups, the render and sound groups, force feedback, `SetMovementMode`
and `SetControlMode` — reaches a class that belongs to tasks 26, 27 or 29,
or the movers.

One piece of carried debt lands here: `wheel_install_seams()` is defined
in `wheel.c` and never called. Its home is the `MM_PHYSICS` arm of
`Car::SetMovementMode`, which constructs the `PhysicsCar` that owns the
`Suspension` and the four `Wheel`s. It has to run before that car's first
`ResolveForces`, or every corner reports airborne.

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
