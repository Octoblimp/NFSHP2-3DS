# Engine, and the Table it is built on

`Engine.obj` and the `Table` class. The second slice of task 25, after
[CarState](car-state.md).

Ported to `3DS Files/source/engine.{c,h}` and `table.{c,h}`.
Cross-checked by `tools/engine_check.py` against `tools/src/engine_test.c`.

## Table

A one-dimensional lookup over an evenly spaced argument range, with linear
interpolation. 20 bytes.

| Off | Field | Type |
|----:|-------|------|
| 0 | pTable | const float * |
| 4 | NumEntries | int32_t |
| 8 | MinArg | float |
| 12 | MaxArg | float |
| 16 | IndexMultiplier | float |

Table is **not an object file**. It is a header-inline class, so its five
methods were emitted into whichever compilation unit used them -- which is
why they sit at 0x00181100, 0x001810b8, 0x00187268, 0x00187298 and
0x00187330 rather than in one run.

It does not own its entries. `pTable` points into the `*Info` struct handed
to the constructor, which lives in the car type data; nothing copies or
frees it.

`CalcIndexMultiplier` (0x00181100) is
`(NumEntries - 1) / (MaxArg - MinArg)`, with no guard against an empty
table or an empty range. `GetValue` (0x00187298) clamps, scales to a
fractional index, truncates with `cvt.w.s` and interpolates.

Two details that a casual reading loses:

* **The clamps are sequential, not a min/max pair.** The high test is only
  reached when the low one did not fire. With an inverted range
  (`MaxArg < MinArg`) they stop being interchangeable, and a NaN argument
  fails both and falls through unclamped. The transcript covers both.
* **The last entry is returned without interpolating.** The guard exists to
  avoid reading `pTable[NumEntries]`, one past the caller's array. It
  cannot change a returned value -- when it fires, the interpolation weight
  is exactly zero -- so it is an equivalent mutant in the transcript, and
  argued as one.

`Table::InverseLookup` (0x00187330) is not ported; its only caller is the
tyre model, which is still outstanding.

## Engine

92 bytes. A one-state integrable: the state is the crankshaft angular
velocity in rad/s, and the derivative is total torque over moment of
inertia.

| Off | Field | Type |
|----:|-------|------|
| 0 | *(base)* | 8 bytes |
| 8 | *(vtable)* | pointer, written by the ctor, never read here |
| 12 | State.w | float, rad/s |
| 16 | EI | const EngineInfo * |
| 20 | pCarState | CarState * |
| 24 | TorqueCurve | Table |
| 44 | EngineBraking | Table |
| 64 | IsHP | int32_t (a bool stored as a word) |
| 68 | Throttle | float |
| 72 | RoadTorque | float |
| 76 | ThrottleOverride | float |
| 80 | NitroFlag | int32_t (a bool stored as a word) |
| 84 | NitroBoostTimer | float |
| 88 | CatchupTorqueMultiplier | float |

`EngineInfo` is 64 bytes: IdleRPM 0, RedLineRPM 4, MaxRPM 8,
MomentOfInertia 12, `TorqueCurveTable[9]` at 16, `EngineBrakingTable[3]`
at 52.

### Recording the layout on a 64-bit host

CarState could carry its pointer widening as a single `CARSTATE_SLACK`
term because its pointers sit at the front. Engine's do not: `EI` at 20
forces eight bytes of alignment padding on a 64-bit host with no PS2
counterpart, so the shift stops being a constant times the pointer growth.

So `engine.h` records the PS2 layout as a **mirror struct** with every
pointer narrowed to `uint32_t`, and asserts all twelve offsets against it.
Be clear about what that proves: the offsets claimed are self-consistent
and add up to 92. It does *not* prove the live struct matches, because the
live struct is the one with real pointers. That half is established by the
behavioural transcript, which walks every field.

This is the pattern the remaining task-25 objects will need, since they are
all pointer-heavy.

### Units

**State.w is rad/s; both curves are indexed in RPM.** The object converts
at every boundary using two constants from the pool, `0x3dd67745` and
`0x4118c9f3`, which are 2pi/60 and 60/2pi to the bit. The rad/s-to-RPM
value appears **twice** in the pool, at gp-30440 and gp-30436; they are the
same number, so the port uses one macro.

Other constants, with the image's own symbol names where `.symtab` has one:

| Address | Bits | Value | Name |
|---------|------|-------|------|
| gp-21124 | 0x3f866666 | 1.05 | `TorqueHPMultiplier` |
| gp-21128 | 0x41700000 | 15 | `MaxRPMEffect` |
| gp-30432 | 0x3ecccccd | 0.4 | -- |
| gp-30428 | 0x3983126f | 1/4000 | -- |
| gp-20224 | int32 | -- | `WorldTimer` |

### Behaviour

**The constructor** (0x001823d8) builds both Tables over
`IdleRPM..MaxRPM` -- nine entries for the torque curve, three for engine
braking -- stores `EI` and `pCarState`, and sets `ThrottleOverride` and
`CatchupTorqueMultiplier` to 1. **It does not initialise `Throttle` or
`RoadTorque`**, so a fresh Engine inherits whatever was in the allocation
until the first `SetThrottle` and `ComputeAuxiliaries`. The transcript
prints both to pin that down.

**ComputeAuxiliaries** (0x00182578) clamps `State.w` into
`[IdleRPM, MaxRPM]` converted to rad/s, then clears `RoadTorque` ready for
the next timestep's `ApplyTorque` calls. The two clamps run in a fixed
order and the second overwrites the first, which is only observable when
the range is inverted -- the transcript carries a degenerate `EngineInfo`
with `IdleRPM > MaxRPM` so that order is pinned.

**GetTorque** (0x00182618) is the torque curve at the current RPM, times
`CatchupTorqueMultiplier`, times `TorqueHPMultiplier` when `IsHP`, and then
the rev limiter. **The limiter does not cut torque, it reverses it**: once
`rpm >= MaxRPM - 100` the result becomes `-15 * t`. `GetEngineTorque`
(0x00182760) is the same calculation at a caller-supplied RPM; the listing
spells the limiter test the other way round and orders the multiply the
other way round, and the port keeps both spellings.

**GetTotalEngineTorque** (0x001826a0):

```
eff     = Throttle * ThrottleOverride
drive   = GetTorque() * eff             (times 3 while nitro is lit)
braking = EngineBraking(rpm)
total   = drive + -braking * (1 - eff)
```

and then, **for a player-driven car only** (`CarState::DriverMode == 1`), a
negative total is scaled by 0.4. An AI car takes the full engine braking.
Engine is the only object in this group that branches on `DriverMode`.

**GetDerivative** (0x001825c8) writes
`(GetTotalEngineTorque() + RoadTorque) / MomentOfInertia` and returns 0;
the integrator takes the count from `GetSize`, which is always 1.
`GetAngularAcceleration` (0x00183ee0) computes the same value.
`GetTorqueResponse` is `1 / MomentOfInertia`. `ApplyTorque` accumulates
into `RoadTorque`, and `ComputeAuxiliaries` is what clears it.

**DecrementNitro** (0x001827e0) clears `NitroFlag` once
`NitroBoostTimer + 4` seconds have passed, where world time is
`WorldTimer * 0.00025` -- so the clock ticks at 4000 Hz. `WorldTimer` is
loaded with `lwc1` and then `cvt.s.w`: it is an integer that gets
converted, not reinterpreted. Its owning object is not ported yet, so the
port keeps its own `WorldTimer` and the harness drives it.

`DoSnapshot` (0x001824d8) is **not** ported -- it needs `ReplaySnapshot`,
the same dependency that stopped `CarState::DoSnapshot`.

## Cross-check

```
python tools/engine_check.py            # 8 scenarios, 413 lines, 0 differ
python tools/engine_check.py --mutate   # 56 mutations, 54 caught, 2 equivalent
```

Two mutation survivors on the first pass were real coverage gaps rather
than equivalents, and the scenarios were extended to close them: no table
had an inverted range, so the sequential clamps looked interchangeable; and
no `EngineInfo` had `IdleRPM > MaxRPM`, so the clamp order in
`ComputeAuxiliaries` was unpinned. Two more mutations pointed at macros in
`engine.h` while the mutation list only rewrote `engine.c`, and reported
themselves as "pattern not found" rather than passing quietly -- the
checker now treats a missing pattern as a failure.

The two remaining survivors are argued in `EQUIVALENT`: dropping Table's
last-entry guard cannot change a returned value (the interpolation weight
is exactly zero when it fires; what the guard prevents is a read one past
the array), and DecrementNitro's early-out is a speed optimisation with no
semantics behind it.
