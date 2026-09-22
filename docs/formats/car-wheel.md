# Wheel

`Wheel.obj` (0x00199c40 .. 0x0019b9e8), 7592 bytes: 72 methods in the symbol
table, the destructor, a static constructor at 0x0019b558 and two
file-local helpers. The seventh slice of task 25, after
[CarState](car-state.md), [Engine](car-engine.md),
[CarTypeInfo](car-type-info.md), [CarDriver](car-driver.md),
[Steering](car-steering.md), [RigidBody](rigid-body.md) and
[Suspension](car-suspension.md).

The tyre. Where [Suspension](car-suspension.md) owns the travel along the
wheel's z axis, this owns everything in the contact patch: how much force
the patch can deliver before it lets go, which way that force points, how
fast the rim is spinning, and the two questions the suspension asks of the
ground underneath.

Ported to `3DS Files/source/wheel.{c,h}`. Cross-checked by
`tools/wheel_check.py` against `tools/src/wheel_test.c`.

## The record

400 bytes, on the same `PhysicsComponent` base
[RigidBody](rigid-body.md) and [Suspension](car-suspension.md) have.

| Off | Field | Type |
|----:|-------|------|
| 0 | pNext | `bNode *`, owned by the list |
| 4 | pPrev | `bNode *` |
| 8 | *(vtable)* | pointer, 0x00298f20 |
| 12 | WI | `const WheelInfo *` |
| 16 | TI | `const TireInfo *` |
| 20 | CI | `const ControlInfo *` |
| 24 | CS | `CarState *` |
| 28 | State | `WheelState`: `a` the rotation, `w` the spin rate |
| 36 | MomentOfInertia | float |
| 40 | *(pad)* | 8 bytes, quadword-aligning Matrix |
| 48 | Matrix | `bMatrix4`, the spin about y |
| 112 | WorldMatrix | `bMatrix4` |
| 176 | CarMatrix | `bMatrix4` |
| 240 | Velocity | `bVector4`, the contact patch's, in the world |
| 256 | Slip | `float[2]`, the slide recorded when the tyre let go |
| 264 | AppliedTorque | float |
| 268 | BrakeLocked | int |
| 272 | LastSign | int, a three-way memory of the spin direction |
| 276 | GroundForce | `float[2]`, longitudinal and lateral, wheel frame |
| 284 | *(pad)* | 4 bytes, quadword-aligning WorldGroundForce |
| 288 | WorldGroundForce | `bVector4` |
| 304 | ContactPoint | `bVector4` |
| 320 | ContactNormal | `bVector4` |
| 336 | Terrain | `TerrainType`, a 32-bit enum |
| 340 | Slipping | byte |
| 341 | TouchingGround | byte |
| 342 | NumTimesSkidding | short |
| 344 | ZForce | float |
| 348 | RoadNoise | float |
| 352 | CurrentSlip | float |
| 356 | OldSlip | float |
| 360 | TractionUsage | float |
| 364 | Damage | float |
| 368 | Brake | float |
| 372 | EBrake | float |
| 376 | TractionBoost | float |
| 380 | CatchupFrictionMultiplier | float |
| 384 | TheSkidMaker | `SkidMaker`, one pointer |
| 388 | *(pad)* | 12 bytes, tail padding to 400 |

There is no mass field. `GetMass` returns a literal 1.0, which is worth
knowing before reading any force in this object as a force in newtons.

### Terrain is an enum, and the four bytes that cost

The slack multiplier climbs 1, 2, 3, 4 across `WI`, `TI`, `CI` and `CS`,
picks up the host's own alignment pad in front of `WI` to reach 5, holds 5
for the whole span from `State` to `CatchupFrictionMultiplier`, and reaches
6 at `TheSkidMaker`, where a second pad lands in front of the pointer
inside it. 400 bytes on the handheld, 432 on a 64-bit host.

The first draft of `wheel.h` had `Terrain` as a `void *`, on no better
grounds than that a field called Terrain sounds like it points at one. It
does not, and three independent things say so:

* `.mdebug` gives `Wheel::Terrain` as type#140 at `offset=2688 bits=32` —
  four bytes.
* the mangled name of the setter is `SetTerrain__5Wheel11TerrainType`, and
  `11TerrainType` is a plain enum, four bytes on both toolchains.
* `GetDerivative` multiplies the field by 140 to index
  `gTerrainTypeInfoTable`. A pointer would not be scaled by the size of the
  thing it already pointed at.

As a pointer it cost a slack term of its own *and* an alignment pad in
front of it, which pushed everything from `Damage` to the end eight bytes
further along and made `sizeof(Wheel)` 440 rather than 432. The mistake was
invisible while `Wheel` was only a layout nothing linked. It became four
diff lines in `suspension_check.py` the moment `wheel.c` was linked into
that checker's build — `sizeof Wheel 440` against 432, `woff Damage 392`
against 384 — which is the whole argument for keeping the older checkers in
the suite and re-running them when a new object joins the link.

`TerrainTypeInfo` is 140 bytes with two `char *` in it, and the second lands
four bytes past an eight-byte boundary, so its slack climbs 1, 2, 3 rather
than 1, 1, 2: one term for `Name` widening, one for the pad in front of
`SkidTextureName`, one for `SkidTextureName` widening. 152 bytes on a
64-bit host.

## The tuning set

Thirteen `.sdata` words at 0x00323d18..0x00323d5c, immediately in front of
[Suspension](car-suspension.md)'s ten — one block, which is why `wheel.c`
includes `suspension.h` for `gLoadFactor`, `gWheelForceFrame`,
`gTireForceEllipseRatio` and `gUglyTimestepHack` rather than declaring its
own copies.

| Address | Name | Shipped |
|---------|------|--------:|
| 0x00323d18 | gWheelMomentOfInertia | 0.00999999978 |
| 0x00323d2c | gRollingFriction | 0.00200000009 |
| 0x00323d30 | gMaxSlipAngleGlobal | 0 *(constructor writes it)* |
| 0x00323d34 | gMaxStaticSlip | 0.5 |
| 0x00323d38 | gBrakingTorque | 4 |
| 0x00323d3c | gEBrakingTorque | 10 |
| 0x00323d40 | gStaticToDynamicBrakeForceRatio | 1.20000005 |
| 0x00323d44 | gBrakeLockAngularVelocityFactor | 0.100000001 |
| 0x00323d48 | gZForceScale | 1 |
| 0x00323d4c | gPilotFactor | 0.850000024 |
| 0x00323d50 | gWheelDebugInfo | 0 |
| 0x00323d54 | gCorneringScale | 1 |
| 0x00323d58 | gUseNewTireForces | 1 |
| 0x00323d5c | gNewCorneringScale | 2.5 |

`gMaxSlipAngleGlobal` is the odd one: zero in the image and written
0.223402172 — the literal at 0x00321800 — by the static constructor, which
then hands it to the cornering table as that table's upper bound. Read the
field out of the ELF and you get 0; read the constant the constructor
loads and you get the number the game actually runs with. The model reads
both and prints both, because a port that initialised the table from the
`.sdata` value would build a curve that tops out at zero and would not
crash doing it.

### The literal pool, and a pi that is one ulp low

0x00321788..0x003217fc is Wheel's own `.lit4` run. Two entries are worth
naming.

`WHEEL_IMAGE_PI` is 0x40490fd0 — **3.14159012**, one ulp below the
0x40490fd8 that [bMath](bmath.md) keeps in its pool and about 2.4e-7 below
pi. Both slip-angle folds use it. `WHEEL_IMAGE_HALF_PI` is **1.57079649**,
not a rounded `1.5708f` and not the 0x3fc90fdc that
[Steering](car-steering.md) and [Suspension](car-suspension.md) load from
*their* pool. Three objects in one game with three different pi/2s is the
normal state of a PS2 build, and it is the reason the model reads its
constants out of the image by address rather than out of the port's header:
a model that copied the `#define` would agree with a typo.

`-100.0f`, the value `CheckTerrain` returns when the surface faces away, is
not in the pool at all. It is `lui at,0xc2c8` at 0x0019a370 — an immediate,
because the top sixteen bits are all it needs.

## The curves

Eight [Table](engine-table.md)s, built by the static constructor at
0x0019b558 out of `.data` at 0x00308e28.

`gCorneringForce` is seven entries over [0, `gMaxSlipAngleGlobal`], rising
0, 0.4, 0.8, 1.2, 1.6, 1.75 and then **falling** to 1.65 — a tyre past its
peak, which is the whole point of the last entry.

`gLoadSensitivity[7]` is seven curves of six entries each, spanning [0, 10]
— slip angle 0, 2, 4, 6, 8, 10 and 12 degrees, against normalised load. The
zero-degree curve is all zeros, which makes the interpolated force fade to
nothing as the slip angle goes to zero without needing a special case.

The image also keeps a `Table *` array at 0x00308fb0 pointing at the seven
`Table` objects, which sit **24 bytes apart** at 0x00308f08 although a
`Table` is 20 bytes. Nothing reaches them except through that array, so the
spacing cannot be observed and the port makes them a plain array. The
checker asserts the pointers are where it thinks they are so that a
differently laid out image fails loudly rather than being modelled wrong.

## Construction, and a Calibrate with no load

`Wheel::Wheel` is nine stores and no arithmetic: the four info pointers, the
vtable, `LastSign` to 1, `CatchupFrictionMultiplier` and `TractionBoost` to
1.0, and the skid set to NULL. It does *not* write `MomentOfInertia`.

`Calibrate` does, and it is the only `Calibrate` in the car that does not
take a load: every other component in task 25 derives something from the
corner weight, and this one assigns a global. Twelve bytes, one store.

The destructor runs `~SkidMaker(this + 384, 2)` and then
`~PhysicsComponent(this, 0)`, the second argument being the old g++ "also
free me" flag. What SkidMaker's destructor does is task 27's to say, so the
port does not guess: it performs the vtable handover, which is the only
part of the chain that belongs to Wheel.

## ComputeAuxiliaries

Called once a frame, before the forces are resolved. It rebuilds `Matrix`
as a rotation about y from `State.a`, clears `GroundForce`,
`AppliedTorque` and `CurrentSlip`, and then does two small things that are
easy to get wrong.

### The angle folds, and gives up

```
if (ROT_FOLD < a)        { a -= ROT_FOLD; if (ROT_GIVE_UP < a)  a = 0; }
else if (a < -ROT_FOLD)  { a += ROT_FOLD; if (a < -ROT_GIVE_UP) a = 0; }
```

`ROT_FOLD` is 628.317993 — a hundred turns, not one — and `ROT_GIVE_UP` is
6283.17969, ten times that. So the angle is allowed to wind up to a hundred
revolutions before it is folded at all, and if one fold is not enough to
bring it back inside a thousand revolutions the wheel's rotation is thrown
away rather than folded again in a loop. A wheel that has been spinning
absurdly fast for one frame snaps to zero instead of costing the frame a
`while`.

### LastSign is a three-way memory

Not a sign: a state. 0 means the wheel was last turning forwards, 2
backwards, 1 means it was stopped. It is applied *before* it is updated, and
what it does is refuse a reversal inside one frame:

```
if (sign == 0 && w < 0)  w = 0;     // was going forwards, can't be reversing
if (sign == 2 && 0 < w)  w = 0;     // was going backwards, can't be forwards
```

and only then is the new value taken, against a `SPIN_EPSILON` of 1e-5.
`sign == 1` — stopped — passes everything through, so a stopped wheel may
start either way but a turning one must pass through stopped first. Every
one of the three cases is in the transcript, crossed against spins on both
sides of the epsilon, because two of the three are unreachable in an
ordinary lap.

## ExchangeZForces returns zero, always

The one fact about this object most likely to be ported wrong.

```
ExchangeZForces(touching, z):
    TouchingGround = touching
    if touching: ContactPoint = ContactNormal * -Radius + WorldMatrix.v3
    if z <= 0:   ZForce = 0;  return 0.0
    t = WorldMatrix.v1 x ContactNormal
    u = t x WorldMatrix.v1
    d = max(4 * (u . ContactNormal) - 3, 0.3)
    ZForce = z * d
    return 0.0
```

Both exits end `mtc1 zero,$f0` before `jr ra`. The airborne arm stores a
zero and returns the same register, which looks like "returns the ZForce it
just set"; the loaded arm computes a real force, stores it, and *then*
clears `$f0`. [Suspension](car-suspension.md)'s `ResolveForces` writes the
return value straight into its own `GroundForce`, so that field is zero on
every frame of the shipped game.

The transcript prints the return and the stored `ZForce` on the same
scenario, next to each other, so the two can never be conflated; the
mutation that makes it return `ZForce` is caught on the first loaded
scenario.

The `d` term deserves a word. `(up × N) × up` is the part of the ground
normal that lies in the wheel's plane; dotting it back with `N` gives 1 for
a wheel square to the ground and less as it leans. The affine map
`4x - 3` turns [0.75, 1] into [0, 1] and everything below 0.75 negative,
and the 0.3 floor then catches it — so a wheel leaning more than about 41
degrees still carries 30% of its load rather than none.

## CheckTerrain asks for a height, not a terrain

`FindDrivingSurface` is a forty-byte forwarder: it calls `CheckTerrain`
with the wheel's *own* `ContactNormal` and `Terrain` as the out-parameters.
`CheckTerrain` then asks the topology for an elevation and a normal, adds
the road noise, and returns how far the ground is along the suspension's
axis:

```
elev  = TopologyCoordinate::GetElevation(topo, pos, NULL, normalOut)
noise = GetRoadNoise({pos.x, pos.y}, <the terrain the wheel already had>)
RoadNoise = noise
align = normalOut . r.v2
if (align < EPSILON) { *terrainOut = 0; return -100.0 }
return (normalOut . ({pos.x, pos.y, elev + noise} - pos)) / align
```

The third argument to `GetElevation` is `move a2,zero` at 0x0019a300 — a
NULL terrain out-parameter. Two instructions later `lw a1,0(s4)` loads the
terrain for `GetRoadNoise`, and `s4` is the wheel's `Terrain` field, not the
stack slot a real out-parameter would have used. **`CheckTerrain` never
learns what it is driving on.** The terrain type it feeds the road-noise
query is whatever `SetTerrain` last put there, which is one frame stale by
construction, and the only write in the whole function is the reject arm's
`= 0`.

The port had this wrong on the first pass — forwarding `terrainOut`, and
writing 0 through it in the NULL-seam fallback — and the harness now proves
the argument is NULL by *writing 77* through any out-parameter the stand-in
is handed. A port that forwarded it would report a terrain of 77 and be
caught on every scenario at once, rather than on none of them, which is
what happens when the stand-in politely writes the terrain the caller
expected.

`-100.0` is not a height. It is "no surface", and the suspension adds the
wheel radius to it and falls through to the fully-extended arm.

## GetDerivative, and the guard that is not commutative

```
out[0] = State.w
acc    = (AppliedTorque - GroundForce[0] * Radius
          - (State.w * RollingFrictionMultiplier) * gRollingFriction)
         / MomentOfInertia
out[1] = acc
if (BrakeLocked)                  out[1] = 0
if (!Slipping && EPSILON < hack)  out[1] -= CurrentSlip / (Radius * hack)
```

The rolling friction is scaled by the *terrain's* multiplier before the
global, not after, and `gTerrainTypeInfoTable` is NULL until task 27 — so
the port reads 1.0 through a NULL table rather than crashing, and the
transcript runs both the NULL and the populated table so the scaling is
pinned either way.

The last two lines are not commutative and the image's order matters: a
locked wheel's derivative is zeroed and *then* has the no-slip correction
subtracted from it, so a locked, gripping wheel does not have a zero
angular acceleration. Swapping them survives every plausible input and is
caught only because the transcript crosses `BrakeLocked` with `Slipping`.

Like [Suspension](car-suspension.md)'s, this returns **NULL** rather than
`out` — the integrator uses the buffer it passed in, and the two components
disagree about what to hand back.

## The brake lock, and a blend done in double

`CheckForBrakeLock` compares the demand on the tyre against what the brakes
can produce:

```
torque    = gBrakingTorque * Brake * CI.Brake
          + gEBrakingTorque * EBrake * CI.EBrake
threshold = torque * gStaticToDynamicBrakeForceRatio
demand    = v * Radius + |State.w| * gBrakeLockAngularVelocityFactor
if (demand < threshold) { BrakeLocked = (1.0 < threshold); State.w = 0 }
else                      BrakeLocked = 0
```

Two details. The wheel is **stopped** whenever the demand is below the
threshold, whether or not it ends up flagged as locked — so a wheel with
the brakes barely touched and no road speed stops dead without ever
reporting a lock. And the `1.0 < threshold` gate means a brake producing
less than one newton-metre of scaled torque can never lock anything, which
is what keeps a stationary car with no brake input from being reported as
locked on every frame.

`GetPilotFactor` is the driver aid: rear wheels only, forward only, not
while locked, ramping the available grip from `gPilotFactor` at
13.4108181 m/s up to 1.0 at 22.3527927 m/s.

```
t = (ForwardSpeed - 13.4108181) * 0.111803398    clamped to [0, 1]
return (float)((double)gPilotFactor + (1.0 - (double)gPilotFactor) * (double)t)
```

The blend is `fptodp` / `dpsub` / `dpmul` / `dpadd` / `dptofp`, with the 1.0
built by `ori a0,zero,0xffc0` and `dsll32 a0,a0,14` rather than loaded — the
compiler promoted the whole expression because `1.0` was written without an
`f`. Spelling it in float moves the result on most inputs in the sweep, so
the port spells it in double and says why.

## GuessGroundForce

996 bytes and the heart of the object. Its `bVector2 *` argument is never
read; everything lands in the wheel's own fields.

**The brakes go on first.** Both torques oppose the spin, and both are
refused outright once the wheel has locked — a locked wheel is stopped by
`CheckForBrakeLock`, not slowed by more torque.

**Then the slip angle**, from the velocity rotated into the wheel frame by
the transposed `WorldMatrix` with its translation column zeroed, through
`bATan` and out as BAMs scaled by 9.58738019e-05. It folds once against pi,
then, if the wheel is travelling backwards along its own x, adds pi and
folds again.

**Then the longitudinal slip**, `State.w * Radius - vx`, into both
`CurrentSlip` and `OldSlip`. A slip more negative than `-gMaxStaticSlip`
with a negative applied torque and *no handbrake* damps the torque by
0.5 — a wheel being dragged backwards under power gets half of it, unless
the handbrake is what is dragging it, in which case it gets all of it.

**Two early-outs** then decide whether the tyre is even asked the question:
a zero slide magnitude, or a car that is not moving in either direction.
Both jump straight to the gripping arm.

**Three triggers** put the tyre into the slipping arm: longitudinal slip
past `gMaxStaticSlip`, slip angle past the tyre's `MaxSlipAngle`, or a
locked brake. They are an `if / else if / else if`, so the transcript has to
reach each of them with the earlier ones false.

**The slipping arm** puts the whole friction circle to work along the slide
direction, and then does something strange:

```
if (ForwardSpeed * 2.23693633 < 1.0 && 0.100000001 < dynamic) {
    GroundForce[1] = fy / dynamic;
    GroundForce[0] = fx / dynamic;
}
```

Below one mile an hour — and only if the friction coefficient is above 0.1,
which is what stops the divide exploding — the sliding force is *divided*
by the coefficient it was just multiplied by, cancelling it. A car sliding
at walking pace gets the grip of a car on dry tarmac no matter what it is
sliding on, which is what keeps a stationary car from creeping down a
slope on ice. The 0.1 gate and the 1 mph gate are each a scenario.

**The gripping arm** takes the longitudinal force straight from the torque,
`AppliedTorque / Radius`, and the lateral force from the tyre curves, signed
by the slip angle and then again by the direction of travel — so the force
points the same way whichever way the car is pointing.

## GetLateralForce: two models, and an index with no floor

`gUseNewTireForces` is 1 in the image, so the old model — one cornering
curve scaled by `gCorneringScale` and the wheel's own `ZForce` — is dead
code in the shipped build. It is a `.sdata` word the debug menu moved, so
the transcript runs both.

The new model:

```
load  = (zforce * gLoadFactor) / TI.MaxLoad
index = ((slipAngle * 57.2957764) * (11 / TI.MaxSlipAngle)) * 0.5
i     = (int)index                       // truncates toward zero
frac  = index - i
if (i < 6) v = load[i] + frac * (load[i+1] - load[i])
else       v = load[6]
return TI.ForceScale * gNewCorneringScale * v
```

The `11 / MaxSlipAngle` and the 0.5 together map the tyre's own maximum
slip angle onto 5.5 curve-steps, so a tyre with a bigger `MaxSlipAngle`
reaches the same curve at a bigger angle. `slti v0,s1,6` is a **signed**
compare and nothing floors the index, so a negative slip angle would index
behind `gLoadSensitivity` and interpolate against whatever is in front of
it. Every caller passes `fabsf(angle)`, so it cannot happen in the game;
the transcript records the shape of the guard rather than adding one the
image does not have.

## FinalizeGroundForce

1216 bytes: clamp the force into the friction circle, record how much of it
was used, bleed some lateral force into the longitudinal, and rotate the
result into the world.

**The ellipse.** A wheel under power has its longitudinal force multiplied
by `gTireForceEllipseRatio` before the clamp and divided by it again after
— *but only if the clamp did not fire*. The multiply makes the tyre hit its
limit sooner under power; if it hits the limit, the scaling stays, and if
it does not, it is undone. `else if` and not a second `if`, and the two are
distinguishable whenever a wheel is both driven and over its limit.

**The traction usage ladder** is four assignments, and their order is the
whole behaviour:

```
TractionUsage = (EPSILON < maxForce) ? min(mag / maxForce, 1) : 1
if (Slipping || BrakeLocked) TractionUsage = 1
if (!TouchingGround)         TractionUsage = 0
```

An airborne *and* sliding wheel reports 0, not 1. Swap the last two and it
reports 1, and every scenario where the wheel is on the ground still agrees
— which is why `TouchingGround` is crossed with `Slipping` and
`BrakeLocked` rather than being set once and left.

**The lateral bleed** subtracts `sin(angle) * GroundForce[1] * 0.5` from the
longitudinal force, but only when the wheel is moving along its own x
faster than 1 m/s. The threshold is a plain 1.0, not an epsilon, and a
wheel rolling below walking pace does not bleed at all.

**Four frames, three of them dead.** `gWheelForceFrame` selects which basis
the wheel-frame force is rotated through:

| Value | Frame |
|------:|-------|
| 0 | identity — the force stays in the wheel frame |
| 1 | the wheel's `WorldMatrix` rows *(shipped)* |
| 2 | `WorldMatrix` rows 0 and 1 projected off the contact normal, row 2 the normal |
| 3 | as 2, but row 0 normalised and row 1 rebuilt as `normal × row0` |
| 4 | `WorldMatrix` rows 0 and 1 unprojected, row 2 the contact normal |

It ships as 1, so frames 0, 2, 3 and 4 never run in the game. They are in
the transcript because a `.sdata` word the debug menu moves is not really
dead code, and because frame 4 has a detail worth pinning: it clears the w
lane of row 2 and **leaves rows 0 and 1 carrying `WorldMatrix`'s** — which
frame 2 does not, and which changes the result because the multiply is
affine.

## DoSnapshot: a list of clears with four holes in it

The replay serialiser. `MoveData` runs in whichever direction the snapshot
is going, so one body both records and plays back; `BeginNamedSection` is
handed the string `"Wheel"` at 0x00323d10.

Three moves: `State.a`, `State.w`, and then **four words from `LastSign`** —
`MoveData(this + 272, 4)`, which covers `LastSign`, both `GroundForce`
floats and the four bytes of padding behind them. The image hands the pad to
the replay and the port hands over the same four words, which is safe to
spell as one pointer and a count precisely because the slack multiplier is
constant at 5 across that whole span: the four words are the same four
fields on the handheld and on a 64-bit host.

Then, if either of two bytes in the snapshot is set, twenty-three
`bMemSet` calls clear most of the record. What is *not* on the list is the
interesting part:

* **`MomentOfInertia`** — survives, so a restored wheel does not need
  recalibrating.
* **`LastSign`** — survives, because it was just moved.
* **`RoadNoise`** (348) and **`Damage`** (364) — survive, and the clear list
  steps around both: it goes 344 for four bytes, then 352; 360 for four,
  then 368. Damage surviving a rewind is deliberate — a car that lost a
  wheel does not get it back — and road noise surviving is probably not,
  but it is what the image does.
* **the pad at 284** — survives, because the clears jump from 276+8 to 288.

`TractionBoost` and `CatchupFrictionMultiplier` *are* cleared, to **0**, not
to the 1.0 the constructor gave them. A wheel restored from a rewind has no
grip multiplier at all until something writes them, and nothing in this
object does.

The three matrices are cleared with `bMemSet`, so they come back as
sixteen zeros, not as an identity.

## SetState(CarState, CarTypeInfo, …): the other elevation call

472 bytes, and the only method in the object that places a wheel from
outside the simulation — the replay and network path. Its `CarTypeInfo *`
argument arrives in `a2` and is **never read**; `a2` is overwritten with a
stack address before anything looks at it.

```
SetState(a, w)                              // State.a, State.w
CS->SteeringAngle              = steeringAngle
CS->WheelAngularVelocity[n]    = w
CS->WheelAngle[n]              = a
CS->WheelSuspensionHeight[n]   = suspensionHeight
CS->CalculateWheelMatrices(n)

place  = CS->BodyMatrix rows 0..2, row 3 = CS->Position with w = 1
world  = eMulMatrix(CS->WheelMatrix[n], place)
CarMatrix   = CS->WheelMatrix[n]
WorldMatrix = world

r        = world.v3 - CS->Position                    // all four lanes
Velocity = (r x CS->AngularVelocity) + CS->Velocity

elev = GetElevation(CS->pTopologyCoordinate, &world.v3, &terrain, &normal)
CS->SetWheelTouchingGround(n, 1)
CS->SetWheelTerrain(n, terrain)
ContactPoint   = { world.v3.x, world.v3.y, elev, <uninitialised> }
ContactNormal  = normal
Terrain        = terrain
TouchingGround = 1
```

Two things to note against `CheckTerrain`. This call **does** ask for a
terrain type — `a2` is a real stack slot, not zero — and it is the only
place in the object that learns one. And the cross product is taken as
`r × ω`, not the `ω × r` that [Suspension](car-suspension.md)'s
`GetPointVelocity` uses; the `vopmula`/`vopmsub` pair has `r` in the first
operand. The port takes it in the image's order without theorising about
which is right.

`ContactPoint.w` is read out of a stack slot the function never writes.
The port writes a defined 0.0 there, which is the same treatment the other
uninitialised lanes in this object get, and the mutation list checks the
claim that it cannot be observed rather than asserting it.

`TouchingGround` is set to 1 unconditionally. This function does not check
whether the wheel reached the ground, because the state it is restoring
already decided that.

## Not ported

`MaybeMakeSkids` (0x0019b2d0, 632 bytes) still has a body — it calls
`MakeSkid` and `MakeNoSkid` on the `SkidMaker` — and belongs to task 27 with
the rest of the skid trails. `MaybeMakeSmoke` (0x0019b2c8) and
`MaybeMakeTireSpew` (0x0019b548) are each a bare `jr ra` in the shipped
image: whatever particle work they used to do was compiled out, and the
port is two empty functions with a note saying so rather than two TODOs.

`SetSliderValue` in the 152-byte gap at 0x0019b230 is the debug menu's, and
also empty.

## Two globals that hide their own callers

`gUseNewTireForces` is 1 and `gWheelForceFrame` is 1, and between them they
make the old tyre model and three of the four force frames unreachable in
the shipped build. Both are `.sdata` the debug menu writes, so neither is
dead in the sense that matters, and a transcript that ran only the shipped
values would pin about two thirds of this object's force code.

This is the same shape [Suspension](car-suspension.md) found five instances
of, and the rule that came out of it applies again: **a value that is zero,
or one, or the wrong side of a floor makes the code that produced it
invisible, and only the mutation pass will notice.**

## The two seams, and the call that is owed

`Suspension` reaches `Wheel::FindDrivingSurface` (0x0019a2a0) and
`Wheel::ExchangeZForces` (0x0019a1c8) through `gWheelFindDrivingSurfaceFn`
and `gWheelExchangeZForcesFn`. Those pointers are a port artifact and not
something the image has -- at 0x0019bdd4 and 0x0019c104 the PS2 build makes
two ordinary `jal`s -- and they exist only because `suspension.c` had to
compile before `wheel.c` did. `wheel.c` owns both now, and
`wheel_install_seams()` points them at the real methods.

**Nothing in `3DS Files/source/` calls `wheel_install_seams()`, so on the
handheld the seams are still NULL.** That is the honest state rather than a
bug to paper over: no car is constructed on hardware yet, so there is no
`Suspension` for them to serve. The call belongs to whichever slice first
builds a car -- `PhysicsCar` or `Car` -- and it has to land before that
car's first `ResolveForces`, or the suspension runs with no ground under it
and every corner reports airborne. `tools/src/wheel_test.c`'s `[seams]`
scenario is the only caller today; it installs twice and prints both
results, so the idempotence the eventual caller will rely on is pinned.

## Cross-check

```
python tools/wheel_check.py            # 19 scenarios, 10693 lines, 0 differ
python tools/wheel_check.py --mutate   # 154, 144 caught, 10 equivalent
```

The mutation pass takes about seven minutes.

The model is written from the disassembly and reads the thirteen tuning
globals, the whole literal pool and all eight curves out of
`PS2 Files/NFSHP2.ELF` by address. It asserts that the pool's duplicate
entries really are duplicates, that `gUseNewTireForces` and
`gWheelForceFrame` are both 1 and that `gMaxSlipAngleGlobal` is 0, so a
retuned image fails loudly here instead of being modelled with the wrong
constant.

Survivors are argued in `EQUIVALENT` at the foot of the checker.

### What the mutation pass moved

The first full pass came back with twelve unexplained survivors, and
working through them changed both the transcript and two of the mutations.
Six were coverage holes:

* The whole pilot speed list agreed whether the blend was done in double or
  in float. `13.5429182f` puts `t` at 0.0147753973, which is one of the
  inputs where it does not, and the `fptodp`/`dptofp` pair the image emits
  is pinned by that single number.
* `ExchangeZForces` tests `!(0.0f < z)`. Every z in the list sent both that
  and `z < 0.0f` the same way. **Negative zero** is the one input that does
  not: the first spelling is airborne and stores a clean `+0`, the second
  falls into the loaded arm and stores `-0.0f * d`.
* The zero-magnitude early-out was **never reached at all**, and the
  comment claiming it was is the more useful half of this finding — see
  below.
* `|slip|` exactly `gMaxStaticSlip` was already in the transcript, but with
  a vx of 0 and a vy of -3, which puts the slip angle far past
  `MaxSlipAngle` and sets `Slipping` on the *next* test whichever way the
  trigger goes. The equality was pinned for `CurrentSlip` and not for the
  branch. The new pair keeps vy at zero and vx positive so the trigger is
  the only thing deciding.
* The dot product's left-to-right association needed more than a pair of
  vectors that disagree by one ulp: frames 2 and 3 spend the dot on
  `N * -d + row`, where both terms are the same size and the last bit
  rounds straight back off. The row has to be nearly parallel to the
  contact normal first, so that flattening cancels almost all of it and the
  residue carries the whole error. Frame 3 then normalises the residue and
  it reaches the fifth significant digit of the world force.
* `SetSliderValue` is empty, and nothing in the transcript could have said
  otherwise: it takes no wheel and returns nothing, so the only trace a
  body could leave is in the tuning globals. They are re-dumped straight
  after the call now, and the call passes 0.375 rather than 0.5, because
  `gMaxStaticSlip` already *is* 0.5 and a body assigning the slider's value
  to it would have written back the number that was there.

**A comment that says a case is covered is not coverage.** The transcript
claimed, in both the harness and the model, that `vx` 0.4 with a spin of
1.25 put the slip at exactly zero and so reached the `mag == 0` early-out.
It does not: `1.25 * 0.32f` is 0.399999976, which leaves a slip of
-2.98e-08 and a magnitude to match. The guard was never reached, the
mutation that deletes it survived, and the comment had been read twice as
evidence that it could not have. `37.5 * 0.32f` is 12 with no rounding at
all, and that is the pair the `gm` block uses.

The other six survivors are equivalent, and the two most interesting are
worth repeating here.

**An explicit alignment pad cannot be checked by deleting it.**
`TerrainTypeInfo._pad0[2]` sits at 14, in front of a pointer. Take it out
and the ABI puts the same two bytes back, every following offset lands
where it did and `sizeof` is unchanged, so the layout assert passes and the
transcript cannot tell. What pins `SkidTextureName` at 16 is the `offsetof`
in the assert, not the pad.

**`Table::GetValue`'s last-index guard is protecting the read, not the
arithmetic.** When `i == last` the interpolation weight `frac - (float)i`
is exactly zero — for every argument in `g_table_args` that gets there, on
both table shapes — so deleting the guard computes
`pTable[last] + (pTable[last + 1] - pTable[last]) * 0.0` and gets
`pTable[last]` back. The number is right and the load is one element past
the end of the array. No transcript can see that; a sanitiser build would.
