# Suspension

`Suspension.obj` (0x0019bc58 .. 0x0019c468), 29 methods. The sixth slice of
task 25, after [CarState](car-state.md), [Engine](car-engine.md),
[CarTypeInfo](car-type-info.md), [CarDriver](car-driver.md),
[Steering](car-steering.md) and [RigidBody](rigid-body.md).

One corner of the car: a spring and a damper along the wheel's z axis, a
sway bar tying it to the corner on the other side, and the bookkeeping that
turns the result into a wheel matrix and a force on the body.

Ported to `3DS Files/source/suspension.{c,h}`. Cross-checked by
`tools/suspension_check.py` against `tools/src/suspension_test.c`.

## The record

176 bytes, on the same `PhysicsComponent` base
[RigidBody](rigid-body.md) has: two list links and the vtable pointer at 8,
the old g++ ABI's append-the-vptr shape again.

| Off | Field | Type |
|----:|-------|------|
| 0 | pNext | `bNode *`, owned by the list |
| 4 | pPrev | `bNode *` |
| 8 | *(vtable)* | pointer, 0x00298fb0 |
| 12 | SI | `const SuspensionInfo *` |
| 16 | pSwayBar | `Suspension *`, the opposite corner, not owned |
| 20 | State | `SuspensionState` |
| 28 | Force | float |
| 32 | Position | `bVector4`, wheel centre, body frame |
| 48 | Matrix | `bMatrix4`, Position as a translation |
| 112 | TouchingGround | int |
| 116 | MagicForce | float |
| 120 | RestLoad | float |
| 124 | *(pad)* | 4 bytes, quadword-aligning RestPosition |
| 128 | RestPosition | `bVector4` |
| 144 | pWheel | `Wheel *`, not owned |
| 148 | pBody | `RigidBody *`, not owned |
| 152 | pSteering | `Steering *`, not owned, **may be NULL** |
| 156 | WheelPosition | int, index into the steering matrices |
| 160 | GroundForce | float |
| 164 | *(pad)* | 12 bytes, tail padding to 176 |

`SuspensionState` is eight bytes: `z` the suspension height and `v` its rate
of change.

Both paddings are written out in the header rather than left to the
compiler. Neither target gives `bVector4` sixteen-byte alignment on its own,
so an implicit version of either would be four or twelve bytes of nothing on
ARM — which is exactly the mistake `steering.h` had made and this header
does not repeat.

### The widening does not fit one slack term

[CarState](car-state.md)'s and [RigidBody](rigid-body.md)'s layouts both
have their pointers gathered at the front, so one `sizeof(void *) - 4` term
covers the whole record on a 64-bit host. This one does not: five real
pointers are scattered through it, and the host inserts two bytes of
alignment padding — in front of `SI` and in front of `pWheel` — that the PS2
does not need.

The multiplier climbs 1, 2, 3 across the front, sits at 3 for the whole span
from `State` to `RestPosition`, then climbs 4, 5, 6, 7 through the four
pointers at the back. The header's assert spells out every one, because the
alternative is a single term that happens to be right.

[Wheel](car-wheel.md)'s is the same shape and `wheel.h` carries the same
treatment: the multiplier climbs 1, 2, 3, 4 across `WI`, `TI`, `CI` and
`CS`, picks up the pad in front of `WI` to reach 5, holds 5 for the whole
span from `State` to `CatchupFrictionMultiplier`, and reaches 6 at
`TheSkidMaker`, where a second pad lands in front of the one pointer inside
it.

An earlier draft of this paragraph said 7 at `Damage`, on the theory that
`Terrain` was a pointer. It is not: `.mdebug` gives `Wheel::Terrain` as
type#140 at 32 bits, `SetTerrain` takes an `11TerrainType`, and
`GetDerivative` multiplies the field by 140 to index the terrain table. A
32-bit enum is four bytes on both toolchains and costs no slack at all. The
mistake cost `suspension_check.py` four transcript lines the moment
`wheel.c` was linked into it, which is the only reason it did not survive
into the port.

### The four bytes the ARM build found

That last paragraph said something different until the port was compiled for
the handheld, and the difference is worth writing down because it is the one
class of bug the cross-check cannot see.

The PS2 record has four bytes of padding at 284, between `GroundForce[2]`
and `WorldGroundForce`, because `bVector4` is a quadword type there and has
to start 16-aligned. **This port's `bVector4` is a plain four-float struct
with four-byte alignment**, so nothing makes that gap appear — the compiler
puts `WorldGroundForce` straight after `GroundForce` at 284, and the record
comes out 396 bytes instead of 400, with every vector behind it four bytes
early.

On the 64-bit host this was invisible. The four pointers in front widen by
sixteen bytes and pick up an alignment pad of four on the way, so by
`GroundForce` the record has grown by twenty; `WorldGroundForce` only needed
to grow by sixteen to land where the SLACK arithmetic said. The missing gap
and the extra widening cancelled, the multiplier read 4 instead of 5, and
the model and the harness agreed on a record that was wrong for the target.

`wheel.h` writes the gap out as `_pad2[4]` now — the same treatment
`suspension.h` already gave `_pad0` and `_pad1` — and the multiplier is a
flat 5 across all three contact vectors. The transcript prints the extent of
`_pad2`, because shortening a pad is the mutation that moves everything
behind it without changing anything the offsets alone would catch.

Two process points come out of this. The assert was originally wrapped in
`#if __SIZEOF_POINTER__ == 4`, so it was compiled by *neither* toolchain:
skipped on the host, and the ARM build had not been run yet. A claim that no
compiler checks is a comment. And the host harness is a cross-check for
*arithmetic*; it is not a second opinion on the target's layout, because it
is not the target. Build for ARM before calling a record done.

## The tuning set

Ten globals in `.sdata` that the suspension and tyre code share, at
0x00323d60 .. 0x00323d84. They are writable and the debug menu moved them,
so the port keeps them as variables rather than folding the values in.

| Address | Name | Ships as |
|---------|------|---------:|
| 0x00323d60 | `gLoadFactor` | 0.8 |
| 0x00323d64 | `gWheelForceFrame` | 1 |
| 0x00323d68 | `gTireForceEllipseRatio` | 1.5 |
| 0x00323d6c | `gNoSlipCorrectionFactor` | 0.1 |
| 0x00323d70 | `gUglyTimestepHack` | **1.0** |
| 0x00323d74 | `gGroundPenaltyImpulse` | 0.2 |
| 0x00323d78 | `gGroundPenaltyForce` | **0.0** |
| 0x00323d7c | `gMaxGroundPenetration` | 0.15 |
| 0x00323d80 | `gProgressiveDampingFactor` | 0.1 |
| 0x00323d84 | `gNoWheels` | 0 |

Two of them ship at values that hide the code reading them, and both needed
handling in the transcript rather than a footnote. See
[below](#two-globals-that-hide-their-own-callers).

`UglyTimestepHack` is the image's name, not this port's. It is a timestep
that is not a timestep.

## The state does not integrate

`GetDerivative` (0x0019c170) writes two zeroes and returns the pointer it
was given. `GetSize` (0x0019c410) is `addiu v0,zero,2` — two floats, which
is `sizeof(SuspensionState) / 4`, and unlike RigidBody's 32-for-29 this one
is honest: both floats are moved by `GetState` and `SetState`.

So the object is a `PhysicsComponent` the integrator can walk, and walking
it does nothing. `ComputeAuxiliaries` recomputes `z` from the ground every
frame and differences it against the previous `z` for `v`; the record keeps
the old value only long enough to subtract it.

## Construction and calibration

The constructor (0x0019bc58) is nine stores and no arithmetic. Note what it
does *not* do: `State`, `Force`, `Position`, `Matrix`, `TouchingGround`,
`RestLoad` and `RestPosition` are all left as the allocation found them, and
`pSwayBar` is nulled. `Calibrate` and `ComputeAuxiliaries` are expected to
run first. The transcript constructs over a scribbled record to show which
fields survive.

`Calibrate` (0x0019bd40) sets `RestLoad` and computes the wheel's position
relative to the body's centre of gravity. The subtraction is **a whole
quadword**, and `WheelInfo::Position` is three bare floats with `Radius`
behind it, so

```
RestPosition.w = WI->Radius - pBody->CenterOfGravity.w
```

Nothing reads that lane — every later use of `RestPosition` goes through
`bMulMatrixVec3`, which forces `w` to 1 — but the port reproduces it rather
than zeroing a lane the image fills.

## ComputeAuxiliaries

0x0019bd78, 872 bytes, and the whole of the object's arithmetic. In order:

1. Put `RestPosition` through the body's rotation and add the body's
   position. `bMulMatrixVector` here is the `bVector3` overload, which
   forces `w` to 1 going in and writes the product's `w` back out, so the
   four-lane add that follows carries a computed `w` and not a leftover.
2. Ask the wheel what is under that point: `Wheel::FindDrivingSurface`.
3. Add `WheelInfo::Radius` to the answer — **before** either bump stop is
   consulted — and clamp.
4. Difference `z` for `v`.
5. Build the wheel's matrix, steer it, wobble it by the damage, and hand
   both the car-frame and world-frame copies to the wheel along with the
   velocity of the contact point.
6. Spring, damper, sway bar and penetration into `Force`.

### Neither bump-stop comparison is strict

```c
if (si->BumpStop[0] < surface)        { /* compressed */ }
else if (surface < si->BumpStop[1])   { /* airborne   */ }
else                                  { /* in travel  */ }
```

A wheel sitting *exactly* on the compression stop falls through to the else,
and so does one sitting exactly on the droop stop — which means a fully
extended wheel at the droop limit still counts as touching the ground.

Only one of those two is worth anything. At the **compression** stop the
distinction is invisible: both arms write `BumpStop[0]` into `z` (the else
writes `surface`, which *is* `BumpStop[0]` there), both set
`TouchingGround`, and the penetration the extra arm computes is
`surface - BumpStop[0]`, which is zero — the value the variable already
held. The clamp is idempotent at its own boundary. Making that test
non-strict is equivalent on every input, and the mutation table says so.

At the **droop** stop the two arms disagree about `TouchingGround`, so the
same change is caught on sight: a wheel exactly on the stop is on the ground
under one reading and in the air under the other.

Getting a case to land on a stop exactly is not free. The scenarios ask the
stand-in for `stop - 0.32f` and step 3 adds the radius back, so the question
is whether that round-trips. At the compression stop it does — 0.18 and
0.32 are both positive and within a factor of two, so the subtraction is
exact by Sterbenz. At a negative stop the magnitudes *add* instead of
cancelling, and the sum's ulp is twice the stop's, so the result can only
land on every other float near the stop. **−0.22f is not one of them**:
it is 0xbe6147ae, an odd mantissa, and no float the stand-in can return
reaches it — checked by walking the neighbourhood a bit at a time rather
than assumed. The fixture's droop limit is **−0.25** for that reason,
because 0.25 + 0.32f happens to be exact.

### A penetration too big is discarded, not clamped

```c
penetration = surface - si->BumpStop[0];
s->State.z = si->BumpStop[0];
s->TouchingGround = 1;
if (gMaxGroundPenetration < penetration)
    penetration = 0.0f;
```

It is a sanity check on the terrain query, and a query that comes back
absurd contributes nothing rather than contributing the limit.

### The damage wobble

A wheel with nonzero `Damage` gets an extra rotation about z, with the
damage as the amplitude and the wheel's own rotation angle as the phase:

```c
angle = wheel->Damage * bSinF(wheel->State.a);
c = bSinF(angle + HALF_PI);
sn = bSinF(angle);
```

There is no cosine call — the image spells cosine as `bSinF(angle + pi/2)`,
the same idiom [Steering](car-steering.md) uses, and out of the same `.lit4`
pool entry. That constant is the one this slice got wrong on the first pass;
see [below](#the-constant-the-checker-caught).

### The force

```
spring  = max(z, 0) * Progression * Stiffness
spring += Stiffness
spring *= z

damping = v * (v <= 0 ? Damping[1] : Damping[0])

f  = RestLoad + spring + damping
f += SwayBarStiffness * (z - pSwayBar->State.z)
f += penetration * gGroundPenaltyForce

Force = f < 0 ? 0 : f
```

The progression term only stiffens the spring in compression — `max.s`
against a register the function zeroed — but the whole product is then
scaled by a `z` that can be either sign, so a droop-side spring is linear
where a bump-side one is not. The total floors at zero rather than going
negative; the transcript has a case with a rest load of −90000 and a sway
bar four units out to reach it.

`max.s` is modelled as the comparison it is rather than as `fmaxf`, which
would drag in a NaN rule the R5900 instruction does not have.

**It dereferences `pSwayBar` unconditionally** whenever `TouchingGround` is
set, and the constructor leaves that NULL. `SetSwayBar` has to have been
called. The port does not add a guard the image does not have.

## The two force paths

`ResolveForces` (0x0019c0e0) hands the wheel `Force`, plus the caller's
extra when the wheel is down:

```c
z = s->Force;
if (s->TouchingGround) z += extra;
s->GroundForce = Wheel::ExchangeZForces(s->TouchingGround, z);
```

The extra is skipped in the air; `Force` is passed either way, and so is the
flag.

`ResolveMoreForces` (0x0019c120) applies the wheel's `WorldGroundForce` at
the contact point, and does nothing at all when `gNoWheels` is set — but the
offset vector is **computed first**, so the debug flag skips the force and
not the arithmetic. The port keeps that ordering; it is a claim about the
listing, and the mutation table says so rather than pretending the
transcript covers it.

`ApplyGroundPenaltyImpulse` (0x0019c1b8) is the impulse that stops a wheel
sinking into the ground. It takes the velocity of the wheel centre, dots it
against the contact normal, and returns zero if the point is already moving
away. `gNoWheels` skips the `ApplyImpulse` and **still returns the
magnitude**.

The dot product is `vmul.xyz` then two `vadd` lanes into x — three lanes,
not four — so the junk `w` the cross product left behind never reaches it.

## GetPointVelocity, and the w lane that survives

0x0019c180, a free function in this object rather than a method: the
velocity of a point offset `r` from a body's centre, `v + w × r`.

The cross product is `vopmula.xyz` / `vopmsub.xyz`, which writes xyz and
leaves the destination's fourth lane alone. The destination here is the
angular velocity register, so the four-lane add that follows carries

```
out.w = v.w + w.w
```

Three of this object's four vector expressions have a `w` lane like this,
and the port keeps all of them. The transcript prints `w` everywhere for
that reason.

## The two seams

`Wheel::FindDrivingSurface` (0x0019a2a0) and `Wheel::ExchangeZForces`
(0x0019a1c8) are genuinely Wheel's own work — the first forwards to
`Wheel::CheckTerrain`, the second rewrites four Wheel fields — so they are
function-pointer seams rather than a Wheel port smuggled in early, the same
shape `gTrackPathDistanceFn` has.

```c
extern WheelFindDrivingSurfaceFn gWheelFindDrivingSurfaceFn;
extern WheelExchangeZForcesFn    gWheelExchangeZForcesFn;
```

Both paths read a NULL seam as zero and carry on rather than faulting, and
the transcript covers the NULL state as well as the wired one.

**The Wheel slice has landed, and the handheld is still in the NULL state.**
`wheel.c` defines both pointers and `wheel_install_seams()` points them at
`Wheel::FindDrivingSurface` and `Wheel::ExchangeZForces` -- but nothing in
`3DS Files/source/` calls it. That is not an oversight to fix here: there is
no car on the handheld to install them for, because nothing constructs a
`Suspension` or a `Wheel` yet. The call belongs to whichever slice first
builds a car -- `PhysicsCar` or `Car` -- and it has to happen before the
first `ResolveForces`, or the suspension silently runs with no ground under
it. `tools/src/wheel_test.c`'s `[seams]` scenario is the only caller today,
and it checks that installing twice is idempotent for that reason.

The seams are a port artifact, not something the image has: the PS2 build
calls both methods directly. They exist to keep `suspension.c` compilable
before `wheel.c` existed, and once the car is built they could be collapsed
back into direct calls.

`wheel.h` exists only to give `Suspension` the offsets it indexes; it says
so at the top, and it is **a layout, not a port**. Its assert is compiled on
both hosts now — see “The four bytes the ARM build found”.

## Not ported

`Suspension::DoSnapshot` (0x0019bc88) needs `ReplaySnapshot`, the same
dependency that has held up `CarState`, `Engine`, `CarDriver`, `Steering`
and `RigidBody`. `operator new` and `operator delete` are the PS2 slot
allocator.

## Two globals that hide their own callers

`gGroundPenaltyForce` ships as **0.0**. The penetration that
`ComputeAuxiliaries` works so hard to compute, sanity-check and discard then
multiplies by nothing, so in the shipped build a wheel 0.07 into the ground
and a wheel 0.22 into it come out with the same `Force` to the bit. The
first draft of the transcript had `bottomed` and `deep` printing identical
numbers and the whole branch unobservable.

`gUglyTimestepHack` ships as **1.0**. The velocity divide divides by one,
and the guard in front of it —
`if (TIMESTEP_EPSILON < gUglyTimestepHack)` — never takes its false arm.

Both are `.sdata` the debug menu moved, so the fix is the same in both
cases: run the same heights again with the global moved, which is a state
the program could really be in, and let the transcript pin the arithmetic
there. `pen-small` and `pen-huge` differ by exactly 0.07 × 800 = 56;
`hack-half`, `hack-two` and `hack-tiny` pin the divide and both arms of the
guard.

### …and three more of the same shape, found only by mutating

The two globals above were found by reading. Three more hiding places were
found only by the mutation pass, and all three are one failure: **a scenario
that reaches a line but cannot observe what it did.**

* **The airborne early return.** Deleting `return;` after `Force = 0.0f`
  survived. With the fixture's rest load of 3400 the fall-through computes
  about −7200, the floor takes that back to zero, and the branch that
  was supposed to have returned lands on the same answer.
  `airborne-loaded` carries a rest load of 50000 so the fall-through would
  come out positive.
* **The progression clamp.** Replacing `max(z, 0)` with `z` survived for
  the same reason: `negative-z` floored to zero too. Its rest load went from
  3400 to 8000, and the two spellings now differ by 147 N.
* **The penalty impulse, entirely.** Every case in `[penalty]` varied only
  the *z* lane of the contact normal, and with the body's velocity what it
  is, all four came out approaching away from the surface. All four took the
  early return; the impulse, the mass factor, the `gNoWheels` path and the
  `w` lane were never executed at all, and **five mutations survived on that
  one mistake**. The scenario varies the whole normal now, and adds a
  `grazing` case with a zero normal, where the three-lane dot is +0, the
  approach is its negation −0, and `-0 < 0` is false — so it falls
  through the guard, applies a zero impulse, and returns a −0 that a
  `<=` would have turned into a +0.

That is five instances of one shape in this object alone, and the camera's
structurally zero velocity record was the first in the repo, so it is worth
stating as a rule. **A value that is zero, or one, or the wrong side of a
floor makes the code that produced it invisible. A transcript that only runs
plausible inputs will not notice, and only the mutation pass will.**

## The constant the checker caught

The first draft of `suspension.h` had

```c
#define SUSPENSION_IMAGE_HALF_PI 1.5708f   // 0x3fc90ff9
```

The model reads its constants out of the ELF rather than out of the header,
and the two disagreed on the first run. `lwc1 $f12,-29656(gp)` with
`gp = 0x00328bf0` is 0x00321818, and that word is **0x3fc90fdc** — the
one-ulp-high pi/2 that [Steering](car-steering.md) loads from the same pool,
not a rounded 1.5708f, which would have been 0x3fc90ff9 and thirty ulps
away.

The two objects were compiled against one constant and the port has to spell
it the same way in both. This is the argument for the model reading primary
data instead of the port's own header, stated as concretely as it gets: a
model that had copied the `#define` would have agreed with the bug.

## Cross-check

```
python tools/suspension_check.py            # 10 scenarios, 1108 lines, 0 differ
python tools/suspension_check.py --mutate   # 68 mutations, 66 caught, 2 equivalent
```

The two survivors are argued in `EQUIVALENT` at the foot of the checker.
`su-more-forces-flag-first` moves the `gNoWheels` test above the subtraction
that builds the application point: the subtraction has no side effects and
its result is dead on that path, so only the instruction order changes.
`su-bumpstop-inclusive` turns `BumpStop[0] < surface` into `<=`: at equality
the clamp assigns the value the height already has, `TouchingGround` is 1 on
both arms, and the penetration is 0 either way, so the two spellings cannot
be told apart from outside.

Nine other survivors were *not* equivalent, and closing them is most of what
the scenario table is for; the five penalty ones and the three that hid
behind the force floor are written up above.
