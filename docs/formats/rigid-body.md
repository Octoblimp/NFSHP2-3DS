# RigidBody

`RigidBody.obj` (0x00192438 .. 0x0019400c), 47 functions and 4508 bytes.
The sixth slice of task 25, after [CarState](car-state.md),
[Engine](car-engine.md), [CarTypeInfo](car-type-info.md),
[CarDriver](car-driver.md) and [Steering](car-steering.md).

Ported to `3DS Files/source/rigidbody.{c,h}`. Cross-checked by
`tools/rigidbody_check.py` against `tools/src/rigidbody_test.c`.

RigidBody is a prerequisite the task list never named. Suspension holds a
pointer to one, Wheel pushes forces at one, PhysicsCar owns one, and Car
reaches through all three — nothing else in task 25 can be finished first.

## The shape of it

This is Baraff's rigid body, near enough to the SIGGRAPH course notes that
the variable names survive. The integrated state is

| | |
|---|---|
| `X` | position |
| `R` | orientation, as a matrix rather than a quaternion |
| `P` | linear momentum |
| `L` | angular momentum |

and velocity, angular velocity and the world transform are *auxiliaries* —
recomputed from that state every step rather than integrated. Forces and
moments accumulate into two vectors that `ComputeAuxiliaries` clears and
re-seeds with gravity.

## Layout

384 bytes on PS2. The vptr is at 8, inside the `PhysicsComponent` base,
which is itself a `bNode` — two list links the object never touches and the
list that owns it does.

| Off | Field | Type |
|----:|-------|------|
| 0 | pNext | `bNode` link |
| 4 | pPrev | `bNode` link |
| 8 | *(vtable)* | pointer |
| 12 | RBI | `const RigidBodyInfo *` |
| 16 | State | `RigidBodyState` |
| 144 | Velocity | `bVector4`, auxiliary |
| 160 | AngularVelocity | `bVector4`, auxiliary |
| 176 | Matrix | `bMatrix4`, auxiliary |
| 240 | ForceAccumulator | `bVector4` |
| 256 | MomentAccumulator | `bVector4` |
| 272 | MotionDamping | `int32_t` |
| 276 | IsHP | `int32_t` |
| 280 | Mass | `float` |
| 284 | Mass_inv | `float` |
| 288 | I_body_inv | `bMatrix4` |
| 352 | CenterOfGravity | `bVector4` |
| 368 | MaxMomentZ | `float` |
| 372 | SpeedLimiter | `float` |
| 376 | CatchUpMultiplier | `float` |

`RigidBodyState` is 128 bytes: `X` 0, `R` 16, `P` 80, `L` 96,
`MotionDampingFactor` 112, and twelve bytes of tail padding.
`RigidBodyInfo` is 80: `Mass`, `Xdim`, `Ydim`, `Zdim`, then the inertia
tensor at 16.

The two list links are 32-bit slots and nothing in this object dereferences
them, so the port declares them `uint32_t` and the layout stays exact
through offset 12. From `RBI` on, the host struct grows: four bytes of
alignment padding in front of the wider pointer, then the pointer's own
four. `RIGIDBODY_SLACK` carries both, and the static assert spells out
which four is which rather than hiding them in one number.

## The w lane is load-bearing, and not consistently

Every quadword move in this object is `lqc2`/`sqc2`, so an assignment or an
add moves all four lanes. The cross products are not: `vopmula.xyz` /
`vopmsub.xyz` write xyz only, and the destination register's w survives
untouched. In every caller that register holds the *position* vector, so a
moment's w lane is the w lane of the point the force was applied at.

The constructor clears xyz of six vectors and **leaves w alone** in all six.
`bMulMatrixVec3` writes four floats, not three — it forces the input w to 1
and stores the product's w into the destination's fourth lane — so every
rotated vector in this object carries a computed w rather than a leftover.

The transcript prints w on every vector for exactly this reason.

## ApplyForce and ApplyImpulse are not the same function

They look identical. They are not.

```
ApplyForce(f, at):           ApplyImpulse(j, at):
  v = clamp(f, 1200)           v = clamp(j, 1000)
  FA += v                      P += v
  m = clamp(at x f, 100)       m = clamp(at x v, 10)
  MA += m                      L += m
          ^ unclamped                    ^ clamped
```

`ApplyForce` reloads the caller's vector — `lqc2 vf1,0(a1)` at 0x001930f0,
reading through `a1` after the clamped copy has already gone into the
accumulator. `ApplyImpulse` reloads the stack copy instead, at 0x00193264.
So a force above 1200 N contributes a full-strength moment and a reduced
force, while an impulse above 1000 contributes a reduced impulse *and* a
reduced moment. Whether that is deliberate is not knowable from the image;
it is what the image does.

`ApplyImpulseScaled` scales the moment **after** the clamp, so the scale is
not bounded by the 10 the clamp enforces.

`ApplyForceInFrame` rotates both the force and the point through `R` first,
by `bMulMatrixVec3`, which means both pick up the translation row and both
come out with w = 1.

## SetState inverts three floats, not a matrix

`SetState` needs the body-frame inertia tensor, and the object only stores
its inverse. Rather than call `bInvertMatrix`, it builds an identity and
writes three reciprocals into the diagonal:

```
ibody = I
ibody[0][0] = 1 / I_body_inv[0][0]
ibody[1][1] = 1 / I_body_inv[1][1]
ibody[2][2] = 1 / I_body_inv[2][2]
L = R * ibody * R^T * omega
```

For a diagonal tensor that is exact and much cheaper. For one with
off-diagonal terms it is **wrong**, and quietly: the object round-trips
through `SetState` into a different angular momentum than it came from.
Every car in the image has a diagonal tensor, so the shortcut never bites,
but the port keeps it. The transcript builds one body with off-diagonal
terms and watches it not round-trip.

`P` is scaled by `Mass` on the way in — the argument is a velocity, not a
momentum, even though the field is momentum.

## VectorStarMatrix

The derivative of a rotation matrix is `omega* R`, where `omega*` is the
skew-symmetric matrix of the angular velocity. The image never builds
`omega*`; it cross-products each row of `R` with `omega` directly:

```
out.row_i.xyz = cross(omega, R.row_i)
out.row_i.w   = 0
out.v3        = (0, 0, 0, 1)
```

Three rows, not four. The fourth is written as the identity's bottom row
regardless of what `R` had there, so a translation in `R` does not
propagate into `Rdot`.

## ComputeAuxiliaries

```
V   = P * Mass_inv
W   = R * I_body_inv * R^T * L
if (MotionDampingFactor < 0) MotionDampingFactor = 0
Matrix = R rows 0..2, with X in row 3 and w forced to 1
FA = MA = 0
ApplyForce((0, 0, -9.8 * Mass), at origin)
```

Gravity is applied here rather than in the integrator, which is why the
accumulators are cleared in the same function: anything applied before
`ComputeAuxiliaries` in a frame is discarded.

**The one deliberate divergence in this port.** The image clears the two
accumulators with `sqc2` from a register it never writes, so their w lanes
come from whatever the stack frame left behind. That is genuinely
uninitialised memory, not a value; the port writes zero. Downstream the w
lanes reach `GetDerivative`'s output and then the integrator, which only
reads 29 of the 32 floats — so nothing observable depends on it. The
divergence is recorded here rather than papered over.

## GetDerivative, and the speed limiter

The derivative is laid out to match the state array: `Xdot` at 0, `Rdot` at
4, `Pdot` at 20, `Ldot` at 24, and the damping-factor rate at 28.

Before any of that, the speed limiter can rewrite the force accumulator.
It runs only when `SpeedLimiter` is non-zero:

```
limit = SpeedLimiter * CatchUpMultiplier + 1.9
if (IsHP) limit *= 1.03
```

The 1.9 is a floor in metres per second, so a limiter of zero still permits
a walking pace. The HP bonus is three percent, and it is the police-car
advantage: an HP unit chasing you is allowed to exceed its own limiter by
exactly the margin needed to close.

Then the slope, read off `R.v0.z` — how steeply the body's own x axis is
pointed up or down:

```
uphill   (slope > 0):  slope = min(slope, 0.3); limit *= 1 - 0.1 * slope / 0.3
downhill (slope <= 0): slope = min(-slope, 0.3); limit *= 1 + 0.1 * slope / 0.3
```

so the limit is scaled between 0.9 and 1.1 and the clamp at 0.3 means
anything steeper than about seventeen degrees counts the same.

The speed compared against it is **ground speed only** — `sqrt(Vx² + Vy²)`,
z left out — times 2.23602486. That constant is metres per second to miles
per hour, and it is wrong: the true factor is 2.2369363. The limiter is
therefore about 0.04% permissive, which matters not at all, but it does
place the whole comparison in mph and confirms the limiter is a designer's
number rather than a physics one.

If the car is over the limit *and* driving into it —
`0 < dot(R.v0, ForceAccumulator)` — the accumulator is rotated into body
space, its x component replaced by

```
brake = max(-slope * 5, -0.5)
```

and rotated back. Note what that is: not a scaling of the driving force but
a fixed *negative* force along the body's x axis, floored at −0.5, and
zero on flat ground. The limiter does almost nothing on the level; it is
there to stop cars running away downhill.

## The two damping terms

Angular momentum damping is unconditional:

```
Ldot += L * -AngularMomentumDampingTable(|W|)
```

over a six-entry table spanning 0..10 rad/s, from 0.05 up to 5.0 — so a
body spinning fast is dumped hard and a body barely turning is left alone.

Motion damping is conditional on the `MotionDamping` flag and proportional
to the state's own damping factor:

```
Ldot += L * (-2 * MotionDampingFactor)
Pdot += P * (-8 * MotionDampingFactor)
```

and the factor has its own rate, on `out[28]`: it rises at 0.1/s toward a
target read off an eight-entry table, and falls at 10/s away from it. The
asymmetry is a hundred to one — the damping engages slowly and releases
almost instantly. The table's argument is

```
max(|V| / 4, |W| / 2)
```

spanning 0..1, and the entries run from 1.5 down to 0.0, so the target is
highest when the body is nearly still. This is the "settle a car that has
stopped moving" mechanism, and the fast release is what stops it feeling
like treacle the moment the player touches the throttle.

## The MaxMomentZ clamp reads the wrong vector

Last in `GetDerivative`, when `MaxMomentZ` is non-zero:

```
mz = MomentAccumulator.z
if (mz > MaxMomentZ)  Ldot.z =  MaxMomentZ
if (mz < -MaxMomentZ) Ldot.z = -MaxMomentZ
```

It tests the **accumulator** and writes the **derivative**. Both damping
terms have already been added into `Ldot.z` by this point and the
comparison does not see them, so the clamp can fire on an accumulator that
damping had already brought inside the limit, or fail to fire on a `Ldot.z`
that damping pushed outside it. The port keeps the discrepancy; a mutation
that reads `out[26]` instead is caught on four lines.

## GetSize answers 32

The integrator is told the state is `sizeof(RigidBodyState) / 4` floats,
which is 32, even though only 29 carry anything. The three past
`MotionDampingFactor` are the struct's tail padding, and
`GetStateArray`/`SetStateArray` never move them — the integrator copies
them around as whatever they were. Reporting 29 would be tidier and would
also be a different program; the transcript pins 32.

One thing does write them. `PhysicsSystem::IntegrateEuler` advances every
component's state in place through the pointer `GetState()` returns, all
`GetSize` words of it, and `GetDerivative` has written only 29 of the
body's. So the pad words take `dt` times whatever the integrator's stack
array held at those three slots, which on the PS2 is someone else's frame.
Nothing reads them back. The port's integrator clears its array first
(see [PhysicsSystem](physics-system.md#integrateeuler)), so on the 3DS
the padding stays as the allocator left it. physicscar_check found this
by running the shipped integrator over a whole car and dumping the body.

## What is not ported

`PrintCurrentState` (0x00193c90) is ported as an empty function. It is not
empty in the image — it computes a dozen values into stack temporaries and
leaves one in `$f0` — but the `printf` is gone, the function is `void`, and
every store is dead. There is nothing observable left, and a port that
recomputed the dead arithmetic would be inventing a side effect the image
does not have.

`DoSnapshot` came with the replay, TASKS 72b; `tools/carsnap_check.py` checks it against retail.

`operator new` / `operator delete` are the PS2 slot allocator again, and
are not ported for the same reason as everywhere else.

## Cross-check

```
python tools/rigidbody_check.py            # 10 scenarios, 935 lines, 0 differ
python tools/rigidbody_check.py --mutate   # 78 mutations, 76 caught, 2 equivalent
```

**Seventy-eight, where this said seventy-seven.** `rb-info-tensor-at-12`
came over from `cartypeinfo_check` when `RigidBodyInfo` moved out of
`cartypeinfo.h` and into this header -- a checker mutates the file it owns.
It puts the inertia tensor where `Zdim` is, which shifts every field after
it by four, and it is caught.

Four survivors from the first pass needed work rather than acceptance:

* **`rb-len3-assoc`** — rebracketing the sum of squares survived, because
  no input had squares far enough apart for the two orders to round
  differently. Added a force of `(4096, 1, 1.5)`: 4096² is exactly 2²⁴, so
  the other two squares straddle the last representable unit and the two
  bracketings land two ulps apart. Caught on twelve lines, through the
  clamp's scale factor.
* **`rb-deriv-hp-always`** — applying the HP bonus unconditionally
  survived, because in every limiter case the speed was so far over the
  limit that three percent could not flip the comparison. The bonus only
  ever decides *whether* the brake fires, never how hard. Added a pair of
  cases at 14.445 m/s, which scales to 32.30 — above the flat-ground limit
  of 31.90 and below the 32.86 an HP car gets.
* **`rb-deriv-planar-has-z`** — putting z back into the ground speed
  survived, because every case with the limiter active had `Vz = 0`. Added
  a car climbing at 5 m/s: 31.30 along the ground, 33.24 through the air,
  one either side of the limit.
* **`rb-tables-swapped`** was caught by a segfault rather than by the
  transcript — swapping the `table_init` target left the other table with a
  null pointer. Rewritten to swap the *value arrays* instead, so both
  tables are still built and the transcript does the catching, on 120
  lines.

### The two survivors, and why no transcript can catch them

`rb-clamp-inclusive` changes `cap < len` to `cap <= len`, so a vector whose
length is exactly the cap gets scaled where the image leaves it alone. The
scale is `cap / len`, and IEEE division of a value by itself is exactly
1.0. Multiplying all four lanes by exactly 1.0 returns each one unchanged,
sign of zero included. The extra multiply is the identity on every input,
not merely on the ones the transcript happens to use.

`rb-energy-halves-together` changes `lin * 0.5f + ang * 0.5f` to
`(lin + ang) * 0.5f`. Halving is exact — 0.5 is a power of two, so the
mantissa is untouched and only the exponent moves — and rounding therefore
commutes with the scaling. The identity does fail once halving itself
becomes lossy, in the subnormal range below about 1e−38, but an energy
that small would need momenta near zero and their squares nearer still.

Note the contrast with [Steering](car-steering.md)'s one survivor, which
was equivalent only *because* the image's pi is eleven ulps low. These two
are equivalent by the arithmetic itself, which is a stronger claim and a
cheaper one to check.
