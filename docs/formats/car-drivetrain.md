# DriveTrain

There is no `DriveTrain.obj`. The class is a contiguous run of 39 symbols
at 0x00182828 .. 0x00183e10, 5608 bytes, inside `Engine.obj` — whose
`.text` the linker map puts at 0x001823d8, 0x1b98 long, with Engine's own
nine functions before the run and twenty-five after it and nothing of
Engine's interleaved. That is also why `ClutchSpeed`, the vtable and the
pooled literals below are all quoted as Engine.obj's `.data`, `.rodata`
and `.lit4`: DriveTrain has no sections of its own.

The ninth slice of task 25, after
[CarState](car-state.md), [Engine](car-engine.md),
[CarTypeInfo](car-type-info.md), [CarDriver](car-driver.md),
[Steering](car-steering.md), [RigidBody](rigid-body.md),
[Suspension](car-suspension.md) and [Wheel](car-wheel.md) — and the first
one whose every dependency was already on the handheld.

The gearbox, the clutch and the differential: everything between the
crankshaft and the four rims. It is a `PhysicsComponent` with exactly one
state float, and that float is not a physical quantity — it is how far the
clutch pedal is up, from 0 to 1.

Ported to `3DS Files/source/drivetrain.{c,h}`. Cross-checked by
`tools/drivetrain_check.py` against `tools/src/drivetrain_test.c`.

## The record

148 bytes, on the same 12-byte `PhysicsComponent` base
[Engine](car-engine.md), [Suspension](car-suspension.md) and
[Wheel](car-wheel.md) have.

| Off | Field | Type |
|----:|-------|------|
| 0 | pNext | `bNode *`, owned by the list |
| 4 | pPrev | `bNode *` |
| 8 | *(vtable)* | pointer, 0x00297a30 |
| 12 | State | `DriveTrainState`: one float, `clutch` |
| 16 | DTI | `const DriveTrainInfo *` |
| 20 | pEngine | `Engine *` |
| 24 | pDriveWheel | `Wheel *[4]` |
| 40 | pCarState | `CarState *` |
| 44 | DesiredGear | `Gear` |
| 48 | CurrentGear | `Gear` |
| 52 | PreviousGear | `Gear` |
| 56 | CurrentClutchState | `ClutchState` |
| 60 | Shifting | int, a bool stored as a word |
| 64 | DifferentialAngularVelocity | float, a cache |
| 68 | GearHoldTime | float |
| 72 | SportGear | `Gear` |
| 76 | ShiftUpRPM | `float[9]` |
| 112 | ShiftDownRPM | `float[9]` |

`.mdebug` gives `DriveTrain (size=148)`; every offset above was
re-derived from the listing. The base class was pinned by matching
`!1,020,2785` — DriveTrain's compilation unit — against `!1,020,974`, the
one Engine, Suspension and Wheel share. Type numbers in `.mdebug` are
local to a compilation unit, so a bare grep for `020` collides across
objects and proves nothing.

Every pointer sits in one contiguous run and `DTI` is already eight-byte
aligned at 16 on a host, so the host widening is a single term times the
number of pointers an offset has passed. No alignment pad appears
anywhere, which is why `drivetrain.h` needs one `DRIVETRAIN_SLACK` where
[wheel.h](car-wheel.md) needed a table of multipliers.

### Gear indices are the enum, not zero-based

`Gear` is `4Gear`, type #1053, and two of its values are negative:

| Value | Name |
|------:|------|
| -2 | `SPORT_SHIFT` |
| -1 | `AUTOMATIC` |
| 0 | `REVERSE` |
| 1 | `NEUTRAL` |
| 2 .. 8 | `FIRST_GEAR` .. `SEVENTH_GEAR` |

Every comparison against a gear in the listing is a signed `slt`, never
`sltu`. The two negatives are modes rather than gears: `AUTOMATIC` asks
`SetDesiredGear` to choose, and `SPORT_SHIFT` asks it to follow
`SportGear` and hand back `AUTOMATIC` when the driver has stopped
shifting.

The image indexes `GearRatios`, `ShiftUpRPM` and `ShiftDownRPM` with
`CurrentGear` **directly**, so `GearRatios[2]` is first gear and entries 0
and 1 of all three arrays belong to reverse and neutral. `GetShiftUpRPM`
and `GetShiftDownRPM` are unguarded, and `CalculateShiftPoints` never
writes entries 0 and 1, so asking either accessor about reverse reads
whatever the slot pool left behind.

### ClutchState, and the string table that proves the order

```
0  CLUTCH_DISENGAGING
1  CLUTCH_DISENGAGED
2  CLUTCH_ENGAGING
3  CLUTCH_ENGAGED
```

The order matters twice: `GetDerivative` indexes `ClutchSpeed` with it,
and `ComputeAuxiliaries` switches on it with a chain the compiler built
from `slti v0,v1,2` plus two compares. It is not guessed —
`ClutchStateString` at 0x00307f40 holds `"Disengaging"`, `"Disengaged"`,
`"Engaging"`, `"Engaged"` in exactly this order.

## The tuning set

Eight writable globals in `.sdata` at 0x00323970. The names are the ones
`PS2 Files/NFSHP2.MAP` gives them, which removed all guesswork about
naming for this slice — a source of ground truth this port had not
exploited before.

| Address | Name | Value |
|---------|------|------:|
| 0x00323970 | `gEngineBrakingFactor` | 40.0 |
| 0x00323974 | `gShiftUpDetune` | 0.95 |
| 0x00323978 | `gShiftDownDetune` | 0.95 |
| 0x0032397c | `gGearShiftMethod` | 1 |
| 0x00323980 | `gLimitedSlip` | 0.35 |
| 0x00323984 | `gClutchLimiter` | 300.0 |
| 0x00323988 | `gClutchMatchedThreshold` | 50.0 |
| 0x0032398c | `gMaxDownShiftOver` | 1.1 |

`gEngineBrakingFactor` is never read in this object; it is declared
because it sits in the run and a later slice will want it.

`WorldTimeElapsed` at 0x00323d00 is not DriveTrain's. The game loop owns
it and this object only adds it to `GearHoldTime`, which is why it is
named bare rather than with a `g` — the same distinction
[engine.h](car-engine.md) draws for `WorldTimer` at gp-20224. It is 0.0 in
the image because it is written every frame, so a transcript that never
sets it sees the hold timer stand still.

**`gLimitedSlip` is one global doing two jobs.** In `ApplyClutchTorque` it
is the threshold the spin share is tested against *and*, halved, the share
the differential clamps to. Move it and both ends move together; the `ac
tightslip` line in the transcript is there to keep that visible.

### ClutchSpeed

0x00307f30, four floats in `Engine.obj`'s `.data` that only
`DriveTrain::GetDerivative` reads: `-3.0`, `0.0`, `1.5`, `0.0`. The clutch
falls out at 3 per unit of `ShiftSpeed`, comes in at 1.5, and holds still
at both ends. It is const data rather than a tuning knob, so the port
spells it in the header instead of declaring it `extern`.

### Two conversions that are not 2pi/60

The pooled literals at 0x00321558 and 0x00321560 are 0x3dd67745 and
0x4118c9f3. The correctly rounded floats of 2pi/60 and 60/2pi are
0x3dd67750 and 0x4118c9eb — eleven and eight ulps away.

0x4118c9f3 is the decimal 9.549304: the five-place tabulated value of
60/2pi, spelled out to seven. 0x3dd67745 is exactly its float reciprocal,
so the pair round-trips to exactly 1.0 while both sit a little off the
constant they stand for. A port that wrote 2pi/60 here, or kept one and
spelled the other as `1.0f / it`, would agree with the image on the round
trip and disagree on every conversion: every idle test in `Idling` and
every shift point in both automatic paths would move.

An earlier draft of `drivetrain.h` claimed the opposite — that the two are
*not* reciprocals and multiply to 0.99999994. That was wrong, and the
transcript's `rpm roundtrip 1` is what caught it.

### The literal pool, one slot per use site

0x00321518 .. 0x00321574, twenty-four slots. Six of them hold 0.001, six
hold 0.999, three hold 0.2, two hold 0.3 and two hold 9.549304: the
compiler pooled per use site, not per value. `drivetrain.c` collapses each
family into one macro.

That collapse is checked rather than assumed.
`drivetrain_check.py:check_pool` reads all twenty-four slots out of the
ELF separately and refuses to run if any family disagrees with itself. The
values themselves are checked through behaviour — the `dv edge` scenario
straddles 0.001 and 0.999 on both sides of both tests, `sv mph` straddles
the mph conversion, and the `ca` and `au` scenarios straddle every
throttle limit — because the macros live in `drivetrain.c` where the
harness cannot see them.

## CalculateShiftPoints, and where the two arms join

0x00182828. Not a method: a file-scope function the constructor calls, and
the only place `ShiftUpRPM` and `ShiftDownRPM` are ever written.

With `gGearShiftMethod` set — which is how the game ships — each up point
is found by walking the RPM up from `(IdleRPM + MaxRPM) / 2` in 50 RPM
steps, looking for the first speed at which the torque *at the wheels in
the next gear* beats the torque in this one:

```
torque(rpm)  <  torque(rpm * next / ratio) * next / ratio
```

If nothing crosses over before `MaxRPM - 200`, the point falls back to
`MaxRPM - 200`.

**Both outcomes are then scaled by `scale`.** The crossover arm and the
fallback join at 0x001829a0, one instruction *before* the `mul.s
$f0,$f0,$f26`. The interpolated arm — `IdleRPM + ShiftUpPoint *
(RedLineRPM - IdleRPM)`, taken when `gGearShiftMethod` is clear — joins
the common tail at 0x001829cc instead, after the multiply, and so never
sees `scale` at all.

An earlier draft of this port had it backwards, with the fallback
unscaled. The `sp fallback` scenario is built from a flat torque curve
precisely so that every gear takes the fallback and the scaling is
visible.

### The loop shape, and the fixture that pins it

The image spells a `do { } while` behind an entry test: a `bc1f` before
the loop and a `bne` after it. The `searching` flag is set in the entry
branch's **delay slot**, so it is 1 even on the path where the loop never
runs — which is what makes the fallback fire for a degenerate engine.

Replacing the entry test with an unconditional loop is invisible for most
engines: a `do/while` that runs once on a flat curve finds no crossover,
leaves `searching` set, and falls out to the same fallback. The
distinguishing fixture is `sp noloop2` — a narrow idle-to-limiter band
with a *falling* curve, where the geared probe clamps to the top of the
table and the first iteration does cross over. Without that fixture the
loop-shape mutation survives; with it, it moves six lines.

### The down points

```
down[i + 1] = gShiftDownDetune * up[i] * next / ratio
```

The gear *above* gets its down point from the gear *below*'s up point,
geared across. Entry `FIRST_GEAR` of `down` is therefore never written by
this function, and `up[NumGears + 1]` is set to `MaxRPM` on the way out so
the top gear never shifts up.

## Construction, and four fields it does not write

0x00182a60. The listing stores to offsets 20, 8, 16, 24, 40, 44, 12, 56,
48 and 60 and stops.

**`PreviousGear`, `DifferentialAngularVelocity`, `GearHoldTime` and
`SportGear` are not initialised.** A caller that reads `GetSportGear`
before the first `SetDesiredGear(SPORT_SHIFT)` reads whatever the slot
pool left behind. The port keeps the omission; the harness zeroes the
record first, so the transcript is reproducible without hiding the fact,
and the `ct` scenario prints all four.

## The differential is queried, not stored

There is no differential speed in the record the integrator owns.
`GetDifferentialAngularVelocity` reads the four wheels every time it is
called, and `ComputeAuxiliaries` caches the answer in
`DifferentialAngularVelocity` for the rest of the frame. Writing that
field does nothing — `SetDifferentialAngularVelocity` writes the
*wheels*.

`TorqueSplit` is the rear share. `>= 0.001` drives the rear pair, `<=
0.999` drives the front; both are true in between, which is how
four-wheel drive is spelled. There is no third flag.

### Two of the three queries halve, and they disagree about when

| Function | Rear only | Front only | Both |
|----------|-----------|------------|------|
| `GetDifferentialAngularVelocity` | pair mean | pair mean | mean of the two |
| `GetDifferentialAngularAcceleration` | pair mean | pair mean | mean of the two |
| `GetDriveWheelSlippage` | pair mean | **half** the pair mean | mean of the two |

The first two carry a `both` flag: the `bnel` that halves is *inside* the
front arm and is skipped entirely when the front arm does not run, so a
rear-drive car gets its pair's mean and a four-wheel-drive car gets the
mean of the two pairs. `GetDriveWheelSlippage` has no such flag — the
halving is unconditional inside its front arm.

So a front-drive car reports **half** its front wheels' mean slip. With
both front wheels slipping at exactly 1.0 the answer is 0.5; the
transcript's `ds fwd unit 0.5` line exists to keep that from being tidied
away. Whether it was intended is unknowable from the image, but it is what
the image does, and the only consumer is a `0.0f < slippage` test in
`ComputeAuxiliaries`, so halving it never changes a decision — only a
future caller that compares against a threshold would notice.

### SetDifferentialAngularVelocity

0x00182d60. The inverse of the query, applied to the wheels: it works out
the shortfall against the speed asked for and adds an equal share of it to
every driven rim.

Below 40 mph, **or** with *both* wheels of a pair off the ground, the pair
is first averaged to a common speed. That is the launch and the wheels-up
case, where letting the two rims disagree is what makes a standing start
unstable. The low-speed test is `<`, and the transcript's `sv mph1` line
sits exactly on 40 mph to pin that down. The test is recomputed per pair,
so a rear pair with both wheels up does not drag the front pair into the
average.

The per-wheel step `delta / ratio` is computed in the `beq`'s delay slot,
before the averaging and regardless of it — though since it depends on
nothing the averaging writes, that ordering is a shape claim rather than
an arithmetic one, and no C mutation can make it observable.

## ComputeAuxiliaries: the clutch state machine

0x00183100. Once per frame. Caches the differential speed, drives the
engine's `ThrottleOverride`, decides when the clutch has come home or
fallen out, and starts a shift by dropping to `CLUTCH_DISENGAGING` when
`CurrentGear` and `DesiredGear` disagree.

| State | Pedal | What it does |
|-------|------:|--------------|
| `DISENGAGING` | 0.0 | falls out; at zero, becomes `DISENGAGED` |
| `DISENGAGED` | 0.0 | **the gear actually changes here**; throttle past 0.3 or a pending shift brings it back to `ENGAGING` |
| `ENGAGING` | 0.7 | clamps the clutch at 1; `ClutchMatched` or `NEUTRAL` promotes to `ENGAGED`; idling drops it |
| `ENGAGED` | 1.0 | the clutch physics below |

The `DISENGAGING` arm compares the clutch against the zero it has just
written to `ThrottleOverride` and then copies that same zero back into the
clutch. The image reloads the word it stored rather than reusing the
register, so the right-hand side of both is the engine's field, not a
literal — the port keeps that shape.

The `ENGAGED` arm is the interesting one. With the throttle open past 0.2
**and** the driven wheels slipping, it throws the drivetrain's speed away
and snaps everything to the engine. Otherwise it drags the engine 4% of
the way towards the differential. Both write the engine's state directly.

`NEUTRAL` skips every bit of that and goes straight to the shift test —
but the `ThrottleOverride = 1.0` store still happens, because it is the
branch's delay slot.

`GetDriveWheelSlippage` is called at 0x0018317c, *before* the throttle
compare at 0x00183194, not behind it. It reads nothing the function has
written, so the order only matters for the shape; the port hoists it into
a local rather than letting C short-circuit it away.

## ApplyClutchTorque, and a differential that clamps backwards

0x00183328. Splits a crankshaft torque across the driven wheels and takes
the same amount back off the engine's `RoadTorque`.

**In `NEUTRAL` it does nothing at all, including the `RoadTorque`
subtraction.** The early return is before it, so a torque applied in
neutral vanishes instead of braking the engine.

Within a pair the split follows the spin share, so the faster rim normally
takes more — an open differential. The limited-slip part is the clamp, and
it goes the *other* way:

```
share = named.w / (named.w + other.w)

if share < threshold            share = 1 - gLimitedSlip * 0.5   // 0.825
else if 1 - threshold < share   share = gLimitedSlip * 0.5       // 0.175
```

A rim whose share has fallen below the threshold is the one being held
back, so it is handed the large share; a rim that has run away is cut to
the small one. That is what moves torque off a spinning wheel. Between the
two thresholds the differential is open.

With *either* wheel of the pair airborne the threshold widens from 0.35 to
0.5, which leaves no open band at all — every share is clamped one way or
the other except an exact tie. The `ac air` block walks that.

### The split is diagonal under BurnOutState

`CarState::BurnOutState` overrides the whole calculation: 1 forces `1 -
threshold` and 2 forces `threshold`. Which wheel that favours depends on
which one the pair "names", and the two blocks disagree — the listing
loads `32(a0)` at the front and `32(a3)` at the rear, so **the front block
names its second wheel and the rear block names its first.**

For the open and clamped cases that is invisible: they are symmetric under
`share -> 1 - share`. For the burnout cases it is not. `BurnOutState` 1
therefore hands the large share to wheels 1 and 2 and the small one to 0
and 3 — diagonally:

```
ac burn1  282.100006  523.899963  599.949951  323.050018
ac burn2  523.899963  282.100006  323.049988  599.949951
```

That is almost certainly a copy-and-paste in the original rather than a
design, but it is what the image does. The port carries the asymmetry in
an explicit `name_first` argument rather than reproducing it by accident.

A brake-locked wheel takes nothing, and its share is **not** redistributed
to the other rim of the pair.

### A pair standing still divides zero by zero

Both pairs are split whatever `TorqueSplit` says, so on a rear-drive car
the front pair is split too, with a torque of exactly 0. Two stopped rims
make the share `0 / 0`. On a car sitting in gear on the grid, that happens
every frame.

IEEE answers NaN. The NaN is multiplied by the pair's torque, zero or not,
and added into AppliedTorque, and from there it reaches the wheels, the body
and the whole car within a frame. The R5900 has no NaN: a `div.s` by zero
gives FLT_MAX signed by the XOR of the operands' signs, whatever the
dividend. The clamp then turns +FLT_MAX into the small share for the named
wheel, and -FLT_MAX into the large one.

The port divides there with `eefpu.h`'s `ee_div`, which gives the EE's
answer for a zero or denormal divisor and the plain quotient otherwise.
`+0 + -0` is `+0`, so of the four signed-zero pairs, only `-0` over `+0`
is negative:

```
ac still 0 0 -> 0 0 323.049988 1522.94995
ac still -0 0 -> 0 0 1522.94995 323.050018
```

A pair spinning opposite ways at the same speed is also an exact zero
divisor. IEEE gives that an infinity, which clamps the same as FLT_MAX
would, so only the zeros tell the two apart. The mutation
`ac-share-ieee-divide` puts the plain divide back, and the `ac still` block
catches it.

PhysicsCar's checker found this: it runs the shipped code under `mipsemu`
with `eediv`, the same function on the model side, and lists every
instruction that took it. These two divides are the only ones the car
reaches ([PhysicsCar](physics-car.md#cross-check)).

## GuessClutchTorque and ModifyClutchTorque

0x001835a8 and 0x00183688, called in that order.

`GuessClutchTorque` does nothing while `DISENGAGED`. The two moving states
apply `slip * ClutchStiffness * clutch`, with the slip clamped to
±`gClutchLimiter`. `ENGAGED` applies the engine's whole torque.

`ModifyClutchTorque` runs only while `ENGAGED`. It is the correction that
makes the engine and the drivetrain accelerate together: the difference
between the two accelerations, divided by the summed inverse inertia of
everything the clutch is tied to.

It recomputes `Engine::GetDerivative`'s expression inline rather than
calling it — the add and the divide are both in this function — and its
inertia sum reads **one wheel per axle**, `pDriveWheel[0]` and
`pDriveWheel[2]`, never the odd ones. The `mc oddmoi` lines move the odd
wheels' inertia by a factor of 500 to show that the answer does not budge.

`FinalizeClutchTorque` at 0x00183830 is `jr ra`. It is ported as empty so
that the call site a later slice writes has somewhere to go.

## SetDesiredGear

0x00183900, and the largest function in the object. Anything that is
neither `AUTOMATIC` nor `SPORT_SHIFT` is written straight into
`DesiredGear` and handed back.

**AUTOMATIC** shifts up when the engine passes `ShiftUpRPM[CurrentGear]`
and all four wheels are on the ground with `CurrentSlip` under 4 — eight
conditions in one chain, any of which vetoes the shift. It shifts down
below `ShiftDownRPM[CurrentGear]`, except in first and second, which have
no table down point: there, with the throttle under 0.2, it drops out
below `IdleRPM + 100`, and with the throttle open it never drops out at
all. That is what stops the car stalling at a crawl. Out of reverse or
neutral it only ever asks for first; there is no reverse logic in this
object.

**SPORT_SHIFT** follows `SportGear`, accumulating `WorldTimeElapsed` into
`GearHoldTime` *before* the engaged test, so the timer runs even while the
clutch is out. Its down test is not the `ShiftDownRPM` table but
`MaxRPM * gMaxDownShiftOver * ratio[current] / ratio[current - 1]` — the
question is whether the engine would still be over the limiter in the gear
below. It hands the driver back to the automatic after ten seconds of not
shifting, or immediately if they have shifted up into the limiter.

### Nineteen instructions that cannot be reached

The arm at 0x00183b94 would fall back to `AUTOMATIC` when the engine bogs
down. Control arrives there only if `DesiredGear` and `SportGear` are
neither equal nor ordered:

- `beq a0,v1` handles equality,
- `slt v1,a0` handles one ordering,
- `slt a0,v1` handles the other.

They are two `int32_t`. A signed comparison has no third case, so nothing
reaches it — not in the image, not in the port, and not in the model.

It is ported as written rather than deleted. The mutation pass records
`ss-unreachable-arm-returns-g` as a survivor with the argument above
attached, because deleting nineteen instructions on the strength of an
argument is how a port quietly stops being a port.

## Not ported

`DoSnapshot` (0x00182b00) needs `ReplaySnapshot` — the same dependency
that has held up CarState, Engine, CarDriver, Steering, RigidBody,
Suspension and Wheel. `operator new` and `operator delete` are the PS2
slot allocator (`DriveTrainSlotPool` at 0x00323090). The destructor is
`PhysicsComponent`'s plus that delete. `PrintCurrentState` (0x00183c28) is
`jr ra` — the debug print compiled out, like Wheel's `SetSliderValue` —
and is ported as empty.

`CheckFunction` is declared in `.mdebug` and has no code in the image.

## Cross-check

`tools/drivetrain_check.py` models the object from the disassembly and
diffs its transcript against `tools/src/drivetrain_test.c`. Every constant
the model uses is read out of `PS2 Files/NFSHP2.ELF` by address, so a typo
in the header shows as a diff rather than as two files agreeing with each
other.

`Table` and `Engine` come from `engine_check`'s model rather than being
written again — `GuessClutchTorque` and `ModifyClutchTorque` both call
`GetTotalEngineTorque`, and re-deriving the torque curve would duplicate a
model that already has its own transcript. `Wheel` and `CarState` are
local stand-ins, because DriveTrain touches nine fields of the
four-hundred-byte Wheel and three of CarState.

Eighteen scenarios, 498 lines.

```
python tools/drivetrain_check.py
python tools/drivetrain_check.py --mutate
```

### Fixtures are spelled, not computed

Every fixture float is its own decimal literal on both sides — `0.33f`,
not `0.32f + 0.01f`. The model rounds each literal once; the C would round
a sum twice, and `0.32f + 0.01f` is 0.329999983, one ulp below
`f32(0.33)`. Fixtures are not the thing under test, so they are written so
the two sides cannot disagree about them.

The same care applies to labels: the `ac share` lines are tagged with the
numerator rather than the ratio, because a ratio computed on one side in
double and on the other in float is a fixture disagreeing with itself.

### The engine the transcript drives

The crossover search only does work when the torque curve falls hard past
its peak. The test is `torque(rpm) < torque(rpm * next / ratio) * next /
ratio`, and with `next / ratio` around 0.7 the right-hand side is already
a third smaller before the curve is consulted — so the only way the left
side loses is for the curve to have dropped a long way between the geared
probe and the current one.

The first fixture engine used a gently falling curve, and four gears out
of five took the fallback: the search loop ran but never found anything,
which left most of its mutations resting on a single gear. The curve was
steepened until every gear crosses over at a different RPM (6080, 5890,
5700, 5605, 5652.5).

### What the mutation pass moved

The first full pass over 176 mutations left **eighteen survivors**. The
transcript agreed with the model on every line at the time, which is the
point of running the pass at all: a clean diff says the two sides compute
the same thing, not that the scenarios reach the code. Sixteen of the
eighteen were reachable and are now killed; the other two cannot be
killed by any input, and the arguments are in `EQUIVALENT` beside them.

Four groups, and what each was missing.

**Fixtures that agreed with themselves.** `ct-shift-points-use-down-detune`
swaps which detune the constructor hands to `CalculateShiftPoints`, and
the image ships `gShiftUpDetune` and `gShiftDownDetune` both at 0.95, so
the swap was invisible. `ca-neutral-skips-pedal` drops the pedal store in
NEUTRAL, and `Engine::Engine` leaves `ThrottleOverride` at 1.0, which is
exactly what the arm writes. `au-low-gear-bound` turns the automatic's
`current < FIRST_GEAR` into `current < NEUTRAL`, and the store it guards
writes `FIRST_GEAR` into a `DesiredGear` the constructor had already set
to `FIRST_GEAR`. Each of these is now driven from a value the code would
have to go out of its way to produce: detunes 0.8 and 0.6, a pedal at
0.25, a `DesiredGear` of fifth.

**State the transcript never printed.** `ca-neutral-runs-physics` lets the
ENGAGED arm run its slip block in NEUTRAL. That block writes the cached
differential speed and the four wheels and does not touch the engine's
own speed on the wheelspin path — and the NEUTRAL case printed only the
engine. It prints the wheels and the cache now.

**Boundaries nothing sat on.** Three of the mutants turn a `<` into a
`<=` and so need the two sides exactly equal.
`au-up-test-inclusive` and `au-down-inclusive` are driven by writing the
shift point back as the very RPM the object will compute, from the same
product on both sides, so the comparison is against itself; choosing an
engine speed and hoping the product lands on a table entry would only be
true to a few ulps. `ss-refuse-inclusive` needed an engine speed whose
sport RPM is exactly second's 900 RPM crawl point, and `94.2477036` is
the one float whose product with the object's rads-to-RPM constant is
exactly 900 — the floats either side land an ulp away.

`ss-limiter-margin` is a fourth boundary of a different shape: it deletes
the 300 RPM margin, leaving `MaxRPM < rpm`. Killing it needs an RPM
inside that band, which 720 rad/s gives at 6875.5. The two speeds already
there, 760 and 400, are over both thresholds and under both.

**Engines the search never worked on.** `sp-midpoint-is-redline` moves
the crossover search's start from `(idle + MaxRPM) / 2` to
`(idle + RedLineRPM) / 2`. Both are multiples of the 50 RPM step and
every fixture crossed over far above both, so the two starts converged.
A curve that falls hard from idle crosses on the first probe and pins the
start. `sp-crossover-not-strict` needed `here` and `there` exactly equal,
which only a zero curve gives: `there` is scaled by `next / ratio < 1`,
so a flat non-zero curve always comes out strictly smaller.

#### The four that survive

`ss-unreachable-arm-returns-g`, argued above: nineteen instructions no
machine can reach.

`gc-clamp-inclusive` makes `gClutchLimiter < slip` inclusive. The two
differ on one input, `slip == gClutchLimiter`, and there the mutant
assigns `slip` the value it already holds. The scenario *does* sit on
that boundary — `gc DISENGAGING slip 300` drives it exactly, the fixture
putting the differential at 200 and the engine at 200 + slip against a
limiter of 300 — and the mutant survives it. That is the argument, not a
gap in it.

`au-down-into-neutral` drops the second half of
`rpm < down && !(current < FIRST_GEAR)`. The arm is only reached past
`if (current < FIRST_GEAR) { DesiredGear = FIRST_GEAR; return g; }`, and
nothing writes `current` in between — it is read once from
`CurrentGear` at the top. The dropped test is true on every path that can
reach it. The image tests it anyway: the PS2 compiler reloaded
`CurrentGear` and compared it again rather than proving the same thing.

`h-slack-is-zero` is listed for a different reason. `DRIVETRAIN_SLACK`
appears only inside the layout assert, so pinning it to 0 makes the
assert wrong on a 64-bit host and the mutant does not compile — it is
reported as caught here. It is in `EQUIVALENT` so that a future run on a
32-bit host, where the same edit compiles and changes nothing, reports it
as equivalent instead of stopping on a hole that is not one. The pass
counts the equivalents that actually survived rather than the length of
the list, so naming it costs nothing on this machine.
