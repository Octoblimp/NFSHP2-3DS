# CarTypeInfo, the car type's data record

`CarTypeInfo.obj` (0x0017ff38 .. 0x00180500). The third slice of task 25,
after [CarState](car-state.md) and [Engine](car-engine.md).

Ported to `3DS Files/source/cartypeinfo.{c,h}`.
Cross-checked by `tools/cartypeinfo_check.py` against
`tools/src/cartypeinfo_test.c`.

1376 bytes of tuning and presentation, one record per car in the game,
shared by every instance of that car. Nothing here simulates anything, and
the seven functions are all one-liners.

**The layout is the deliverable.** Wheel, Suspension, DriveTrain, Engine,
the tyre model, PhysicsCar and Car all index into this record, so a field
in the wrong place is wrong in every one of them, silently. That is why
the transcript spends most of its 177 lines on offsets, extents and
poked-in values rather than on behaviour.

## Two independent witnesses for the size

The field list comes from the `.mdebug` STABS entry. The size has a
separate witness: `GetCarTypeInfo(CarType)` at 0x001801c0 is

```
addiu v1,zero,1376 ; lw v0,-21184(gp) ; mult a0,a0,v1 ; addu v0,v0,a0
```

— the compiler emitting `sizeof(CarTypeInfo)` as a literal, in a different
compilation unit from the debug entry. The two agree at 1376, which is a
stronger claim than either alone.

## Layout

| Off | Field | Type |
|----:|-------|------|
| 0 | CarTypeName | char[32] |
| 32 | BaseModelName | char[32] |
| 64 | GeometryFilename | char[32] |
| 96 | CompressedGeometryFilename | char[32] |
| 128 | DashGeometryFilename | char[32] |
| 160 | CompressedDashGeometryFilename | char[32] |
| 192 | ManufacturerName | char[16] |
| 208 | HeadlightPosition | bVector3 |
| 224 | HeadlightFOV | float |
| 228 | HighPerformance | int8_t, read with `lb` |
| 229 | NumAvailableSkins | int8_t, `lb` |
| 230 | CarClass | int8_t, `lb` |
| 231 | OpenTop | int8_t, `lb`; the port's name, which Render reads (0x00120ef8) |
| 232 | Pad232 | int32_t[2], 0 on the disc |
| 240 | DriverRenderingOffset | bVector3 |
| 256 | InCarSteeringWheelRenderingOffset | bVector3 |
| 272 | CenterOfGravity | bVector3 |
| 288 | Wheels | WheelInfo[4] |
| 416 | Tires | TireInfo[2] |
| 480 | Body | RigidBodyInfo |
| 560 | Suspension | SuspensionInfo[2] |
| 624 | DriveTrain | DriveTrainInfo |
| 688 | Engine | EngineInfo |
| 752 | Aero | AeroInfo |
| 768 | Control | ControlInfo |
| 816 | Sound | 144 bytes, task 29 |
| 960 | Camera | 272 bytes, task 27 |
| 1232 | HudInfo | 80 bytes, task 21 |
| 1312 | LocationProb | 20 bytes |
| 1332 | Type | int32_t |
| 1336 | UsageType | int32_t |
| 1340 | InitialLockStatus | int32_t |
| 1344 | BeACopLockStatus | int32_t |
| 1348 | AvailableSkins | int8_t[10] |
| 1358 | Dummy | 6 bytes |
| 1364 | DefaultSkinNumber | int32_t |
| 1368 | pCarSpecs | const CarSpecs * |
| 1372 | Pad1 | int32_t |

`CenterOfGravity` at 272 and `Wheels` at 288 agree with `carstate.h` to the
byte, which is the first time two independently recovered layouts in this
task have had to line up.

### The field that is not in the debug dump

`pCarSpecs` at 1368 is **absent from the `.mdebug` entry**. It was
recovered from `lw v0,1368(a0)` in all six string accessors, and it points
at a record of translated-string ids:

| Off | Field |
|----:|-------|
| 0 | *(not read by any accessor)* |
| 4 | ZeroTo60 |
| 8 | TopSpeed |
| 12 | BHP |
| 16 | FullName |
| 20 | ShortName |

The slot at 0 has no name here because nothing in the object touches it.
The transcript sets it to a live id anyway, so an accessor that drifted one
slot down would answer a real string rather than nothing.

### The nested records

Three groups. The ones the physics reads are spelled out; the ones that
belong to later tasks are carried as sized opaque blocks so the offsets
after them stay right. Nothing is guessed -- every block's size comes from
the dump.

* **WheelInfo** (32): PositionX 0, PositionY 4, PositionZ 8, Radius 12,
  Width 16, WheelNumber 20, Padding[2] 24. The position is three bare
  floats and *not* a `bVector3` -- there is no pad, which is why Radius
  lands at 12 rather than 16.
* **TireInfo** (32): MaxSlipAngle 0, MaxLoad 4, ForceScale 8,
  StaticFrictionCoefficient 12, DynamicFrictionCoefficient 16.
* **SuspensionInfo** (32): Progression 0, Stiffness 4, Damping[2] 8,
  SwayBarStiffness 16, BumpStop[2] 20, MaxRenderingCompression 28.
* **DriveTrainInfo** (64): ShiftUpPoint 0, ShiftDownRPM 4, FinalDrive[2] 8,
  TorqueSplit 16, ClutchStiffness 20, NumGears 24, ShiftSpeed 28,
  GearRatios[8] 32.
* **RigidBodyInfo** (80): Mass 0, Xdim 4, Ydim 8, Zdim 12,
  InertiaTensor 16.
* **AeroInfo** (16): Drag 0, FrontDownforce 4, RearDownforce 8,
  AutoBalanceDownforce 12.
* **ControlInfo** (48): Steering 0, Brake 4, EBrake 8, BrakeBias 12,
  YawControl 16, YawControlNFS 20, MaxZMomentAcc 24,
  MaxZMomentAccExtreme 28, SpeedLimiter 32.
* **EngineInfo** (64) lives in `engine.h`.

### Recording the layout on a 64-bit host

Unlike Engine, this one does fit the single-slack shape.
`DefaultSkinNumber` ends at 1368, which is already 8-aligned, so the one
pointer pushes nothing ahead of it: **every offset above is also the host
offset.** What changes is the tail -- the pointer is four bytes wider and
the record then aligns to it, so `sizeof` is 1384 on a 64-bit host and
1376 on the 3DS.

## Behaviour

**The six string accessors** (0x0017ff38 .. 0x0017fff8) are each four
instructions. Five read an id out of `pCarSpecs` and hand it to
`GetTranslatedString(int)` at 0x0020b0e0, which is `langtab_get`.

`GetManufacturerName` is the odd one out, and the difference is easy to
miss: `addiu a0,a0,192` is the *address* of the field, not a load through
it. It passes the string at byte 192 to the by-name overload at
0x0020b090, which hashes it with `bStringHash` and searches the English
table -- so it is the only accessor that never touches `pCarSpecs`, and
the only one that still works when `pCarSpecs` is null.

Two rough edges the port inherits rather than fixes, because the image has
them: the field is 16 bytes with no guaranteed terminator, so a
full-width manufacturer name runs on into `HeadlightPosition`; and
`langtab_get_english` is the overload whose own doc warns that English
hashes are not unique in a translated file.

**GetRandomSkin** (0x001804c0) has one detail worth stating plainly:
`move v0,zero` sits in the *delay slot* of the branch that tests
`NumAvailableSkins`, so the no-skins answer is a cleared return register
and **not `AvailableSkins[0]`**. The transcript puts a 3 in
`AvailableSkins[0]` so the two are distinguishable. Otherwise it is
`AvailableSkins[bRandom(NumAvailableSkins, &seed)]` read with `lb`, so the
skin id is sign-extended from a byte. The seed is the image's global at
gp-15456; `bRandom` hands back the *old* seed reduced mod range and moves
the state afterwards, so a draw taken straight after a reseed is the seed
itself.

That is the demo's. Retail's GetRandomSkin (0x00188460) is not the port's
yet, and differs twice. A type of `UsageType` 1 does not draw: it calls
0x001884d8 with 0, which answers 2, or 1 when the word at 0x0031c1c8 is 0.
Any other draws with bRandom(int) (0x0025a488), whose seed is the default
one at gp-14472, not a seed of the car types' own. Porting it is a
follow-up in CONTINUE.md.

**GetCarTypeInfo** (0x001801c0) is `CarTypeInfoArray[type]` with no bounds
check.

`CarTypeInfoIterator::Reset` (0x001810c8) is `sw zero,8(a0)` and nothing
else. The rest of that class is header-inline and was folded into its
callers, so there is no layout to recover and one field to zero -- not
ported, because it would be a guess wearing a function's name.

## Cross-check

```
python tools/cartypeinfo_check.py            # 4 scenarios, 177 lines, 0 differ
python tools/cartypeinfo_check.py --mutate   # 40 mutations, 40 caught
```

**Forty, where this said forty-one.** `rigidbodyinfo-tensor-at-12` moved
to `rigidbody_check` when `RigidBodyInfo` moved out of `cartypeinfo.h`
into `rigidbody.h` -- a checker mutates the file it owns. The offsets are
still claimed here: the harness prints `Body.InertiaTensor`'s absolute
offset, so a field moving inside `RigidBodyInfo` still shows up in this
transcript.

The model re-derives `bStringHash`, langtab's binary search and `bRandom`
from the disassembly rather than importing the ported versions, so an
accessor reaching for the wrong `CarSpecs` slot cannot hide behind a
shared helper.

Seven mutations survived the first pass, all of the same shape: shorten an
array and add padding after it, so that every following offset stays
exactly where it was. They were **not** equivalent -- the transcript
simply had no line that could see an array's length. The fix was to print
each array's extent, not to argue the mutations away. An array's extent is
part of the layout claim just as much as its offset.

Four more are caught by the static assert in `cartypeinfo.h` rather than
by a transcript line. That assert is part of the port rather than part of
the test, so a build failure there is the port rejecting the change; but
it only checks the offsets it names, and the transcript is what covers
the rest.
