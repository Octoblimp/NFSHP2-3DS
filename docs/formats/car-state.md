# CarState

`CarState.obj`, 0x001b6170..0x001b6f60. The car's state record and the
sixteen functions that maintain it. Everything else in the car simulation
meets here: the physics writes it, the renderer, the sound and the AI read
it, and the car-to-world basis they all go through is cached in it.

Ported to `3DS Files/source/carstate.{c,h}`. Cross-checked by
`tools/carstate_check.py` against `tools/src/carstate_test.c`.

Nothing on the disc is a CarState -- the game builds them at runtime -- so
unlike TrackRoute there is no file format here, and a field at the wrong
offset is a compile-time question rather than a decode one.

## Layout

1024 bytes on the PS2. Offsets are decimal, from `.mdebug`.

| Off | Field | Type |
|----:|-------|------|
| 0 | pCarInfo | CarTypeInfo * |
| 4 | pTopologyCoordinate | void * |
| 8 | *(hole)* | 8 bytes |
| 16 | GeometryPosition | bVector3 |
| 32 | Position | bVector3 |
| 48 | Velocity | bVector3 |
| 64 | Acceleration | bVector3 |
| 80 | BodyMatrix | bMatrix4 |
| 144 | AngularVelocity | bVector3 |
| 160 | AngularAcceleration | bVector3 |
| 176 | WheelMatrix[4] | bMatrix4 |
| 432 | BrakeMatrix[4] | bMatrix4 |
| 688 | WheelAngularVelocity[4] | float |
| 704 | WheelAngle[4] | float |
| 720 | WheelZForce[4] | float |
| 736 | WheelRoadNoise[4] | float |
| 752 | WheelBottomOutMagnitude[4] | float |
| 768 | WheelSuspensionHeight[4] | float |
| 784 | WheelTouchingGround[4] | int8_t |
| 788 | WheelTerrain[4] | TerrainType |
| 804 | CrossedWheelTerrain[4] | TerrainType |
| 820 | WheelSlip[4] | bVector2 |
| 852 | WheelTractionUsage[4] | float |
| 868 | Angle | uint16_t (BAM) |
| 870 | SteeringAngle | uint16_t (BAM) |
| 872 | Odometer | float |
| 876 | TractionUsage | float |
| 880 | SkidLeft | float |
| 884 | SkidRight | float |
| 888 | nWheelsTouchingGround | int32_t |
| 892 | ForwardSpeed | float |
| 896 | VelocityMagnitude | float |
| 900 | CurrentGear | Gear |
| 904 | Throttle | float |
| 908 | RPM | float |
| 912 | RedLineSyncRPM | float |
| 916 | ClutchEngaged | int32_t |
| 920 | DriverMode | int32_t |
| 924 | BoostFactor | float |
| 928 | BurnOutState | int32_t |
| 932 | BurnOutTime | float |
| 936 | BurnOutTraction | float |
| 940 | BurnOutAllow | float |
| 944 | RelCoordMatrix | bMatrix4 |
| 1008 | MatrixValid | int32_t |
| 1012 | *(tail)* | 12 bytes |

The hole at 8 and the tail at 1012 are carried as named padding so the
cross-checker can show that nothing writes them.

The two pointers are real and dereferenced, so unlike TrackRoute's list
links they cannot be narrowed to `uint32_t` on a 64-bit host. The static
assert in `carstate.h` instead carries the widening as a term:

```c
#define CARSTATE_SLACK ((size_t)(2 * (sizeof(void *) - 4)))
```

which is 0 on the 3DS and 8 on the host, so the assert keeps its teeth on
both. The harness prints `sizeof(CarState) - CARSTATE_SLACK` for the same
reason.

From `CarTypeInfo` this object reads only a prefix: `CenterOfGravity` at
272 and four 32-byte `WheelInfo` at 288 (PositionX/Y/Z as three bare
floats, `Radius` at 12, `Width` at 16, `WheelNumber` at 20). The rest of
`CarTypeInfo` belongs to the parts of task 25 that are not yet ported.

## Constants

Four floats at 0x003219e8, and they are not all the ones you would guess:

| Address | Bits | Value |
|---------|------|-------|
| 0x003219e8 | 0x38c90fdb | 2pi/65536, BAM to radians |
| 0x003219ec | 0x40490fd0 | "pi" |
| 0x003219f0 | 0x40c90fd0 | "2pi" |
| 0x003219f4 | 0x4622f983 | 65536/2pi, radians to BAM |

The two scales are bit-identical to bMath's and are taken from `bmath.h`.
**The pi pair is not.** bMath holds 0x40490fdb and 0x40c90fdb, and
`float(pi)` is 0x40490fdb too -- this object's copies are 11 ulps low.

That is not a curiosity, it changes behaviour. `GetYawAlways` folds on
`pi < rad`, and over all 65536 BAM differences the products step straight
past 0x40490fd0, which sits in a 402-ulp gap. With bMath's value the
half-turn (delta == 32768) lands *exactly* on the boundary and the fold
stops happening. So the object's constants are reproduced bit-for-bit, and
the checker carries a mutation (`pi-from-library`) that substitutes the
library value and is caught.

## Behaviour

**Init** (0x001b6170) zeroes Odometer, Position, GeometryPosition and
DriverMode, stores the two pointers and calls ResetCar. The three empty
countdown loops it opens with are an inlined do-nothing constructor.

**ResetCar** (0x001b6570) zeroes the motion vectors, sets BodyMatrix to
identity, clears both angles, runs the wheel loop (seven floats, slip,
touching = 1, terrain = crossed = `TERRAIN_DEFAULT` = 1), sets
nWheelsTouchingGround = 4, rebuilds the wheel matrices, and then sets
RPM = 1000, RedLineSyncRPM = -1, ClutchEngaged = 1, BurnOutTraction = 1,
CurrentGear = 1, BoostFactor = 1. Finally it zeroes RelCoordMatrix and
clears MatrixValid. It reuses a just-zeroed float as its 0.0f constant.

**ResetCarForSound** (0x001b6718) is the wheel loop again **minus
WheelRoadNoise**, plus RPM = 1000, both skid values, nWheelsTouchingGround,
VelocityMagnitude and TractionUsage. It does not touch the body, the
matrices, the gear, the clutch, the boost or the burnout. Road noise
surviving a sound reset is the point of the function.

**BeginTimestep** (0x001b67e8) sets CrossedWheelTerrain to 1 for all four
wheels, counting down from wheel 3.

**GetYaw** (0x001b6820) returns 0 below a ForwardSpeed of 5, otherwise
GetYawAlways.

**GetYawAlways** (0x001b6868): `bATan(Velocity.x, Velocity.y)` gives a BAM
heading; the difference from Angle is taken and masked in BAM, and only
then scaled to radians. The fold is one-sided because the mask has already
guaranteed [0, 2pi).

**GetTransformMatrix** (0x001b68d0) is the cached car-to-world basis.
On a hit it returns RelCoordMatrix. Otherwise: if ForwardSpeed is negative
the velocity is reversed -- as a quadword subtract from VU0's constant
register (0,0,0,1), *not* a negation, so a zero component comes out +0.0
where `neg.s` would give -0.0, and the w lane becomes 1-w. Then
`lensq = ((x*x + y*y) + z*z)` in that association. Above 1 the basis comes
from the direction of travel (row0 = (v.y, -v.x, 0, 0), row1 = (v.x, v.y,
0, 0)); at or below it, from Angle (row0 = (sin, -cos, 0, 0), row1 = (cos,
sin, 0, 0)). Rows 2 and 3 are written but `eOrthonormalizeMatrix` does not
read them. Two dead stores at 16(sp) and 20(sp) in the else branch are
never read.

**WorldToCar2/3, CarToWorldUnadjusted, CarToWorld** (0x001b6ab0,
0x001b6b40, 0x001b6bb0, 0x001b6c18) are the space changes.
`eMulVector3` forces w to 1, so WorldToCar3's whole-quadword subtract of
the pad is dead -- the pad that comes back is the w of the product. The
originals run WorldToCar2/3 in place (a0 == a2). CarToWorld returns a
bVector2 by value through a hidden first argument.

**SetWheelTouchingGround** (0x001b6c90) stores unconditionally -- the store
is in the branch's delay slot -- and moves the count only on a transition
between zero and non-zero. It is not a boolean: any non-zero counts.

**SetWheelTerrain** (0x001b6ce0) stores WheelTerrain and raises
CrossedWheelTerrain only if the new value is greater, on a *signed*
compare. Crossed is the high-water mark since the last BeginTimestep.

**CalculateWheelMatrices** (0x001b6d10, 0x001b6e58) builds two matrices per
wheel. The spin is `(uint16_t)((int32_t)(WheelAngle * RAD_TO_BAM) &
0xffff)` -- `cvt.w.s` truncates toward zero, the same conversion `bSinF`
uses. The wheel matrix gets the spin about Y; wheels 0 and 1 additionally
get SteeringAngle about Z, on both matrices. The wheel position is loaded
as a quadword, so the fourth lane picks up `Radius` and is then overwritten
with 1.0. The brake matrix sits at the unlifted hub; only the wheel matrix
adds WheelSuspensionHeight to z.

**CalculateGeometryPosition** (0x001b6ea8) is
`Position - (CenterOfGravity * BodyMatrix)` on all four lanes, with w
forced to 1 by `bMulMatrixVec3` so the translation row applies.

**PrintState** (0x001b6f10) is empty -- the retail build is NDEBUG.

**DoSnapshot** (0x001b6230) is deliberately **not** ported: it needs
`ReplaySnapshot`, which belongs to a later task.

## Cross-check

```
python tools/carstate_check.py            # 10 scenarios, 653 lines, 0 differ
python tools/carstate_check.py --mutate   # 63 mutations, 56 caught, 7 equivalent
```

The model is written from the disassembly, not from the port. Its float
layer comes from `bvector_check`, its trig from `bmath_check` and its
matrices from `emath_check` -- each a model of its own object -- so every
number traces back to an address rather than to another port.

The harness dirties every field **by name** rather than with a byte
pattern, because the host's wider pointers would shift an absolute offset
and make the transcript mean different things on the two machines.

The seven surviving mutants are argued in `EQUIVALENT` in the checker. In
short: the BAM mask makes the second yaw fold unreachable and the `<=`
boundary unhittable; orthonormalize rebuilds row 2; `eMulVector3`'s forced
w kills both the WorldToCar3 pad subtract and the CarToWorldUnadjusted z
lane; the terrain compare writes the same value at equality; and the four
per-wheel calls are independent.
