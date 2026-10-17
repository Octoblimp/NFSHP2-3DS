# Aerodynamics

`Aerodynamics.obj` (0x001a4b58 .. 0x001a4e28): four functions and a
static initialiser, 720 bytes. Part of task 25, after
[RigidBody](rigid-body.md) and [PhysicsSystem](physics-system.md).

Ported to `3DS Files/source/aerodynamics.{c,h}`. Cross-checked by
`tools/aerodynamics_check.py` against `tools/src/aerodynamics_test.c`.

## The shape of it

Aerodynamics computes the drag and the two downforces on a car body. It is
**not a PhysicsComponent**: it has no state and no vtable. PhysicsCar and
MellowMover each own one. Once a frame they call ResolveForces, before the
suspensions, and pass its answer -- the total downforce -- to them as load.

The constructor is inlined into its owners, and so are the four setters
(`SetBoost`, `SetDraft`, `SetThrottle` and `SetGroundEffect`, one store
each). The only out-of-line functions are ResolveForces,
GetDownforceAtSpeed, DoSnapshot and the slot pool's operator delete.

## Layout

24 bytes on the PS2.

| Off | Field | |
|----:|-------|---|
| 0 | AI | `const AeroInfo *`, the 16 bytes at CarTypeInfo+752 |
| 4 | pBody | `RigidBody *` |
| 8 | Boost | divides the speed; 1 from the constructor |
| 12 | Draft | multiplies the drag; 1 from the constructor |
| 16 | Throttle | 0 from the constructor |
| 20 | GroundEffect | 0, or at least 0.5 for the second arm |

AeroInfo is `Drag`, `FrontDownforce`, `RearDownforce` and
`AutoBalanceDownforce`. Nothing in this object reads the fourth.

The inlined constructor in PhysicsCar (0x00135504) stores Boost and Draft
from `$f20`, which holds 1.0, then pBody, AI, and zeroes Throttle and
GroundEffect.

## The data

| Where | What | Value |
|-------|------|-------|
| .sdata 0x00323ee8 (gp-19720) | `OffThrottleDragFactor` | 2.0 |
| .sdata 0x00323eec (gp-19716) | `OffThrottleDragCenterHeight` | -0.1 |
| .bss 0x003096b0 | `FrontDownforceLocation` | (1, 0, 0, 0) |
| .bss 0x003096c0 | `RearDownforceLocation` | (-1, 0, 0, 0) |
| gp-29476 | the speed floor | 1e-4 |
| gp-29472, -29468 | the front and rear shares | 0.40, 0.41 |
| `lui 0x3f00` | the ground-effect threshold | 0.5 |

The two .sdata floats are writable tuning, and ResolveForces reloads both
on every call. The static initialiser (0x001a4de8) writes the x, y and z
lanes of each location and never the w lane, which stays the zero .bss
starts with.

## ResolveForces

0x001a4b80. With `s = |Velocity| / Boost`:

```
drag       k = s*Draft*Drag + (s*Draft*Drag)*(OffThrottleDragFactor - 1)*(1 - Throttle)
           ApplyForce(-k * Velocity, at (0, 0, z))
               z = OffThrottleDragCenterHeight * (1 - Throttle)  if GroundEffect >= 0.5
                   0                                             otherwise

downforce  u = R.v2.z floored at 0, or 1 if GroundEffect >= 0.5
           v = Velocity * (1 / s)  if s > 1e-4,  else (1, 0, 0)
           c = max(dot(v, R.v0), 0)^4
           w = c * u
           GroundEffect == 0:  front = (s*0.40*w) * (Front + Rear)
                               rear  = (s*0.41*w) * (Front + Rear)
           otherwise:          front = (s*Front) * w
                               rear  = (s*Rear)  * w
           ApplyForceInFrame((0, 0, -front), FrontDownforceLocation)
           ApplyForceInFrame((0, 0, -rear),  RearDownforceLocation)

*out = front + rear, if out is not NULL
```

u is the body's up axis against world up, and c is the forward axis
against the direction of travel, raised to the fourth power. A car going
sideways or backwards gets no downforce. Neither does a car on its roof,
unless GroundEffect is on.

Two things in there are not what they look like:

* **v is not a unit vector unless Boost is 1.** It divides the velocity by
  s, which is the speed over Boost. With Boost at 2, the "direction" has
  length 2, and c picks up a factor of 16.
* **The downforce is linear in speed, not quadratic.** Only the drag is
  quadratic, because it multiplies s by the velocity again.

### The comparisons

Each boundary uses a different test, and the transcript has a case on each
one:

| Test | Instruction | At the boundary |
|------|-------------|-----------------|
| speed floor | `c.lt.s floor, s` | s exactly 1e-4 keeps the default direction |
| ground-effect point, forced up | `c.le.s 0.5, GE` (twice, on two reads) | 0.5 counts |
| which downforce arm | `c.eq.s GE, 0` | only exactly 0 takes the first |

So a GroundEffect between 0 and 0.5 takes the second formula without
moving the drag's point or forcing u to 1.

### The w lanes

The drag is `vmulx.xyzw`, so the velocity's w lane is scaled along with the
rest and lands in `ForceAccumulator.w`. The in-frame pushes go through
bMulMatrixVec3, which forces w to 1 going in and writes all four lanes
coming out. That gives each pushed force and each pushed point a w of
`R.v3.w`, and it reaches both accumulators through ApplyForce's
`vadd.xyzw` and its cross product's kept w. Nothing downstream reads those
lanes, but the transcript prints them. A port that dropped one would still
be a different function.

**The one deviation:** the drag's application point has its x, y and z
written and its w left as whatever the stack held. That value flows into
`MomentAccumulator.w`. The port zeroes it, as RigidBody's port zeroes the
accumulators' own w lanes.

## GetDownforceAtSpeed

0x001a4dc8 returns `max(speed, 0) * (Front + Rear)`, the downforce the
second arm gives at full weight. Calibrate uses it. The `max.s` is the
EE's, which compares sign-magnitude: `max(+0, -0)` is +0, and so is the
port's.

## DoSnapshot

0x001a4b58 (retail's 0x001add48). When either of two snapshot bytes (56
and 57, OR'd, in the demo; retail's are 60 and 61) is set, it clears
GroundEffect, Boost and Throttle, in that order. Since TASKS 72b the port
tests the real `ReplaySnapshot`'s TakingSnapshotFlag and
RestoringSnapshotFlag. Boost 0 would make ResolveForces divide by zero,
and PhysicsCar::Move sets Boost again before the next call.
`carsnap_check` runs it against retail.

## Cross-check

```
python tools/aerodynamics_check.py            # 7 scenarios, 110 lines, 0 differ
python tools/aerodynamics_check.py --mutate   # 74 mutations, 74 caught
```

The model is written from the listing. Offsets come from the mdebug record
and are cross-checked against every load in ResolveForces. Constants come
from gp and from the `lui`s. The static initialiser is *run*: its
`lui`/`addiu`/`mtc1`/`swc1` stream is interpreted over sentinel memory. The
constructor's values are decoded from PhysicsCar's inlined copy.

The RigidBody side -- ApplyForce's clamps, its moment taken from the
unclamped force, and bMulMatrixVec3's w lane -- comes from rigidbody_check
and bvector_check, imported rather than written again.
**ApplyForceInFrame had no checker before this one.** It is modelled from
0x00193170 as two bMulMatrixVector calls, the first an 8-byte thunk to
bMulMatrixVec3, followed by an ApplyForce. Five of the mutations are in
`rigidbody.c` and `bmatrix.c` on its account.

One hole turned up on reading the first transcript, before any mutation
ran. **`at-floor` and `over-floor` printed the same thing.** Both
velocities lay along x, where the default direction and the real one
coincide. Both now move along y, so the default direction gives
c = R.v0.x = 0.6 and the real one gives R.v0.y = 0.8, and
`dir-floor-inclusive` is caught there.

Two mutations survived the first pass, and both were fixed:

* **`dot-bracket`**, `xx + (yy + zz)` for `(xx + yy) + zz`, survived
  because no velocity had squares that round differently when grouped the
  other way. A search over one-decimal velocities found (15, 4.3, 0.7).
  It is now the `bracket` case.
* **`sdata-height` was a no-op.** `-0.1f` is the same float as the
  image's `-0.100000001f`. It is now `-0.125f`, and caught.
