# CarDriver, and DriveTarget's record

`CarDriver.obj` (0x00134ce0 .. 0x00134ea0), plus the layout and assignment
operator of `DriveTarget`. The fourth slice of task 25, after
[CarState](car-state.md), [Engine](car-engine.md) and
[CarTypeInfo](car-type-info.md).

Ported to `3DS Files/source/cardriver.{c,h}` and `drivetarget.h`.
Cross-checked by `tools/cardriver_check.py` against
`tools/src/cardriver_test.c`.

## CarDriver

560 bytes. The base of the driver hierarchy -- `RealDriver` (the human),
[`PsychoDriver`](psycho-driver.md) (the AI) and `NullDriver` all derive from it -- and on its
own it is an input record and nothing else.

| Off | Field | Type |
|----:|-------|------|
| 0 | MyDriveTarget | DriveTarget, 528 bytes |
| 528 | Steering | uint16_t, a BAM |
| 532 | Throttle | float |
| 536 | Brake | float |
| 540 | EBrake | float |
| 544 | DesiredGear | Gear (int32_t) |
| 548 | SportGear | Gear (int32_t) |
| 552 | NitroFlag | int32_t |
| 556 | *(vtable)* | pointer |

### The vtable is at the end

**Byte 556, after the data.** This image is built with the old g++ ABI,
which appends the vptr rather than prefixing it. Every class still to come
in task 25 has the same shape and the instinct is to look for it at offset
0, so it is worth saying once, loudly, here.

`MyDriveTarget` being at offset 0 is what makes two of the methods work at
all: `SetTarget` is a bare `j __as__11DriveTargetR11DriveTarget` with `a0`
untouched, and `GetDriveTarget` is `move v0,a0`. Both are only correct
because the two addresses are the same.

### Twenty of the thirty-two functions are stubs

That is the object, not a gap in the port. `SetPhysicsMode`,
`ClearSteeringMemory`, `ZeroSteeringMemory`, `SetSteerToPoint`,
`StartHonkHorn`, `StopHonkHorn`, `AddJoyHandlers` and `RemoveJoyHandlers`
are `jr ra` with a nop behind them. Four more answer a fixed value:

| Function | Delay slot | Answer |
|----------|-----------|--------|
| GetSteerToPoint | `move v0,zero` | NULL |
| IsHonking | `move v0,zero` | false |
| GetDesiredTimeToSpeed | `mtc1 zero,$f0` | 0.0f |
| GetDesiredSpeed | `mtc1 zero,$f0` | 0.0f |
| MaxSpeedToTarget | `mtc1 zero,$f0` | 0.0f, target not even loaded |

They are ported as empty functions rather than left out, because the
physics dispatches through the vtable and an absent one would be a silent
no-op instead of a deliberate one. The transcript calls every one of them
on a driver whose fields are all non-zero and checks that nothing moved.

### SportGear is never initialised

The constructor (0x00134e40) writes the vtable, runs the `DriveTarget`
constructor -- whose first act is `bMemSet(this, 0, 528)`, stopping exactly
at `Steering` -- then clears Throttle, Steering, Brake, EBrake and
NitroFlag and sets `DesiredGear` to 1.

**Nothing writes byte 548.** A fresh `CarDriver` inherits whatever was in
the allocation. The transcript constructs over two different byte patterns
and shows SportGear keeping each one, so this is pinned rather than
assumed.

Two more details the listing gives away:

* `DesiredGear = 1` is written in the **delay slot** of the call to
  `DriveTarget::Clear`, four instructions after the `addiu v0,zero,1` that
  loads it. Easy to read straight past.
* The `0.0f` handed to `Clear` is `lwc1 $f12,532(s0)` -- the Throttle field
  that was zeroed two instructions earlier. The compiler reused a
  known-zero memory location instead of materialising a constant.

The destructor (0x00134de0) rewrites the same vtable pointer -- the usual
C++ arrangement so a virtual call made while unwinding dispatches here and
not to a derived class that is already gone -- runs
`_$_11DriveTarget(this, 2)`, which with flag 2 does nothing, and then
applies its own flags the same way. Nothing here owns memory.

`CarDriver::DoSnapshot` (0x0012f150) is **not** ported: it needs
`ReplaySnapshot`, the same dependency that stopped `CarState::DoSnapshot`
and `Engine::DoSnapshot`.

### The two tables, and NullDriver

Car's fourth slice ([car-modes](car-modes.md)) installed the tables. It
also added NullDriver, the driver a car with nothing to steer it gets.

**`_vt$9CarDriver` (0x002924a8)** has twenty-one entries.

- **Four are `__pure_virtual`:** Drive (16), SetLowGear (48),
  SetDesiredSpeed (56) and GetDriverNumber (80).
- **DoSnapshot (24) is left NULL**, for the reason above.

`vt_slot` aborts on either kind.

**`_vt$10NullDriver` (0x00292400)** is the same table with six entries of
its own (0x00134c98 .. 0x00134cd0):

- **Drive, SetLowGear and SetDesiredSpeed** are `jr ra`.
- **GetDriverNumber** answers -99999.
- **SetTarget drops the target.** CarDriver's copies it.
- **The destructor** stores NullDriver's vptr and then runs CarDriver's.

NullDriver has no fields of its own; the type is 560 bytes. The only code
that builds one is inline, in Car's constructor and in `SetControlMode`'s
null arm, and it runs the CarDriver constructor. So SportGear is
unwritten there too.

`tools/carmode_check.py` calls both tables entry by entry. It uses the
car's NullDriver and a CarDriver built by the image's out-of-line
constructor over the heap's 0xa5 pattern.

## DriveTarget -- layout only

528 bytes: the short list of points the AI is steering through, and the
speed it wants at each. **None of its 28 methods are ported here.** They
are ~8.6 KB reaching into `Car`, `CarState`, `TrackRoute` and the
collision predictor, and they are their own slice. What is here is the
record, because `CarDriver` embeds one and copies it wholesale.

| Off | Field | Type |
|----:|-------|------|
| 0 | NumPoints | int8_t |
| 16 | Points | bVector3[20] |
| 336 | CalculatedSpeed | float[20] |
| 416 | Route | int8_t[20] |
| 436 | RoutePointNumber | int16_t[20] |
| 476 | DrivingLine | int8_t[20] |
| 496 | TType | int32_t, an enum |
| 500 | WhichPointIPicked | int8_t |
| 504 | WhichPointIPickedCalculationTime | int32_t |
| 508 | AccelerationBlendingTime | int32_t |
| 512 | Length | float |

The offsets are in the `.mdebug` entry; **the element types are not**, and
each came from an instruction:

```
Points[i]            sll v0,i,4 ; addiu v0,v0,16     0x00208a0c
Route[i]             lb  a2,416(base + i)            0x00208af0
RoutePointNumber[i]  lh  a3,436(base + i*2)          0x00208af8
DrivingLine[i]       lb  t0,476(base + i)            0x00208ae8
NumPoints            lb  v1,0(s0)                    0x002089a4
Length               lwc1 $f0,512(s0)                0x002091bc
WhichPointIPicked... lw  v0,504(s1)                  0x00209218
```

The count is 20 everywhere, and the constructor agrees in an unexpected
way: it opens with a loop counted from 19 down to -1 whose body the
compiler optimised away to four nops. The trip count is the only trace
left of twenty default-constructed members.

Bytes 516..527 are tail padding, and that is not a guess either: `Points`
is an array of 16-byte vectors, so the record is 16-aligned and 516 rounds
up to 528 = 33 x 16. Nothing writes a vtable pointer into a DriveTarget --
the constructor only memsets and calls `Clear` -- so unlike CarDriver
there is none hiding in that tail.

`DriveTarget::operator=` (0x00208788) is `bMemCpy(dst, src, 528)` and a
`move v0,s0`. No per-field work, no deep copy, and the size is an
immediate, so the whole record goes across regardless of how many points
are in use.

## Cross-check

```
python tools/cardriver_check.py            # 5 scenarios, 118 lines, 0 differ
python tools/cardriver_check.py --mutate   # 46 mutations, 45 caught, 1 equivalent
```

**Forty-six, with one equivalent.** Car's fourth slice made the
constructor run the real DriveTarget constructor, `drivetarget_init`, where
the port had inlined its memset. The two memset mutations became
`ctor-no-drivetarget-ctor` and `ctor-memset-whole-object`, and one was
added: `ctor-no-second-clear`, which drops the constructor body's own
`DriveTarget::Clear`. That one cannot be seen. The member's constructor
has just run `Clear` on the same zeroed record, so the second call takes
the same `NumPoints == 0` early-out and stores the same three zeros over
themselves. The image makes both calls, so the port does too.

**Forty-five, where this said forty-eight.** `drivetarget_assign` was
defined at the top of `cardriver.c` while DriveTarget had no `.c` of its
own; the DriveTarget slice moved it, and its three mutations went with it
rather than being aimed across a file boundary -- `drivetarget_check`
already carries `as-copies-half` and `as-returns-src`. The harness still
*calls* `drivetarget_assign`, so the behaviour is still covered here; what
moved is which checker is allowed to break the line.

Seven mutations survived the first pass, in three groups, and each group
needed a different answer:

* **Five real coverage gaps.** A 32-bit `Steering`, a signed one, a
  one-byte `NitroFlag`, an unsigned `NumPoints`, and a
  `ClearSteeringMemory` that quietly wrote a zero. Every one of them was
  invisible because the transcript happened not to reach the value that
  separates them -- the nitro values all fitted in a byte, the stubs ran
  on an object that was already zero. Fixed by widening the transcript:
  field widths and signedness probes, nitro values past 255, and a stub
  scenario whose fields are all non-zero first.
* **One that only compiles one way.** `bVector3` and `bVector4` have
  identical layouts, so no printed value can separate them. The
  transcript reads `Points[0].pad` by name, which a `bVector4` has no
  member for -- the port's claim is about the name as well as the bytes.
* **One badly-written mutation of mine.** `(uint16_t)(int16_t)x` on a
  `uint16_t` field is a no-op by C's own rules, so it could never have
  been caught. It was replaced with the transcription error it was
  standing in for: reading one byte where the image reads two.
