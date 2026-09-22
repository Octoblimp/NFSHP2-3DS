# Steering, and TwoWheelAckermanSteering

There is no `Steering.obj` and no `TwoWheelAckermanSteering.obj`. Both
classes live in `Suspension.obj`, whose `.text` the linker map puts at
0x0019ba98, 0xb08 long, and neither class is a contiguous run inside it
— the three are interleaved:

```
0x0019ba98  Steering::~Steering
0x0019bac0  TwoWheelAckermanSteering::DoSnapshot
0x0019bb18  TwoWheelAckermanSteering::SetSteering
0x0019bc58  Suspension::Suspension          <- 29 Suspension methods
   ...                                         and GetPointVelocity
0x0019c418  Suspension::~Suspension
0x0019c468  TwoWheelAckermanSteering::operator delete
0x0019c478  TwoWheelAckermanSteering::operator new
0x0019c498  TwoWheelAckermanSteering::ComputeAuxiliaries
0x0019c4a0  TwoWheelAckermanSteering::~TwoWheelAckermanSteering
0x0019c500  TwoWheelAckermanSteering::TwoWheelAckermanSteering
0x0019c548  Steering::GetMatrix
0x0019c558  Steering::BaseDoSnapshot
0x0019c580  Steering::Steering
```

Steering is four symbols and TwoWheelAckermanSteering is seven, and
`Steering::~Steering` is the first symbol of the whole object, a long
way below the other three. `steering.h` lists the addresses one at a
time for that reason; an earlier draft of this file gave each class a
range and an object file of its own, and both were invented.

The fifth slice of task 25, after [CarState](car-state.md), [Engine](car-engine.md),
[CarTypeInfo](car-type-info.md) and [CarDriver](car-driver.md).

Ported to `3DS Files/source/steering.{c,h}`. Cross-checked by
`tools/steering_check.py` against `tools/src/steering_test.c`.

## Steering

Twelve bytes, and it computes nothing.

| Off | Field | Type |
|----:|-------|------|
| 0 | CTI | `const CarTypeInfo *` |
| 4 | SteeringMatrix | `bMatrix4 *`, not owned |
| 8 | *(vtable)* | pointer |

The vptr is at the end again — the old g++ ABI appends it rather than
prefixing it, the same shape [CarDriver](car-driver.md) has, and the same
shape every remaining class in task 25 has.

The constructor (0x0019c580) is two stores: `sw a1,0(v0)` for the car type
and `sw v1,8(v0)` for the vtable. **`SteeringMatrix` is never written.** The
base class has nothing to point it at; every subclass is expected to aim it
at storage of its own, and the one subclass in the image does exactly that.
Between construction and that store the field holds whatever the allocation
left behind, and the transcript constructs over two different starting
values to show both surviving.

`GetMatrix` (0x0019c548) is three instructions:

```
lw   v0,4(a0)
sll  a1,a1,6
addu v0,v0,a1
```

A shift by six, which is `sizeof(bMatrix4)`, and **no bounds check**. The
transcript asks for indices −1, 2, 3 and 7 on a two-matrix object and
records the addresses it gets, because walking off the end is the
behaviour, not a bug to be fixed in the port.

The destructor (0x0019ba98) rewrites the vtable word and returns.

## TwoWheelAckermanSteering

144 bytes: the twelve-byte base, four bytes of padding to get `bMatrix4`
onto a quadword, and two matrices.

| Off | Field |
|----:|-------|
| 0 | base (`Steering`) |
| 16 | AckermanMatrix[2] |

### Ackerman geometry, with tan(x) replaced by x

In a turn the inside wheel has to steer further than the outside one,
because it is tracing a tighter circle about the same centre. The exact
relation is

```
cot(outer) = cot(inner) + Track / Wheelbase
```

Substitute `tan(x) ~ x` on both sides and it collapses to one divide:

```
outer = (Wheelbase * inner) / (Wheelbase + Track * inner)
```

which is what `SetSteering` (0x0019bb18) computes, and it is why the
function has a `div.s` and no `atan` call anywhere. `Wheelbase` is
`CTI->Wheels[0].PositionX - CTI->Wheels[3].PositionX` and `Track` is
`CTI->Wheels[0].PositionY - CTI->Wheels[1].PositionY`. Which axis is which
is inferred from the shape of the formula rather than from the field names:
the term that multiplies `inner` in the denominator has to be the track for
this to be Ackerman at all.

The approximation is only good for small angles, and the port keeps it
rather than fixing it. At a steer angle near `Wheelbase / Track` the
denominator approaches zero and `outer` blows up — the transcript includes
a geometry and an angle that land there on purpose, because a "corrected"
port would quietly diverge from the original exactly where the original
misbehaves.

The whole function:

```
rad   = (float)(bam & 0xffff) * 2pi/65536     -- so rad is in [0, 2pi)
if (IMAGE_PI < rad) rad -= IMAGE_TWO_PI       -- fold to (-pi, pi]
inner = |rad|
outer = (Wheelbase * inner) / (Wheelbase + Track * inner)
```

Both subtractions that produce Wheelbase and Track are computed *before*
the fold's branch — the second one sits in the delay slot of a plain
`bc1f`, not a branch-likely, so it happens whichever way the branch goes.

The fold is one-sided. There is no `rad < -pi` arm, and there does not need
to be: the BAM is zero-extended with `andi a1,a1,0xffff`, so `rad` is never
negative on the way in.

### The two angles are handed out by sign

```
rad < 0:  AckermanMatrix[0] = -outer,  AckermanMatrix[1] = -inner
rad >= 0: AckermanMatrix[0] =  inner,  AckermanMatrix[1] =  outer
```

The inside wheel is whichever one gets the full angle, and which one that
is depends on the direction of the turn. Matrix 0 is not "the left wheel"
in any fixed sense.

### Each matrix is a rotation about Z built from two sine calls

`bIdentity`, then four stores: `m[0]` and `m[5]` to the cosine, `m[1]` to
the sine, `m[4]` to its negative. **The cosine is `bSinF(angle + pi/2)`** —
there is no `bCos` call here — so whatever error the pi/2 constant carries
goes into every steer matrix the game builds.

### The object's own trigonometry constants

Read out of the pool at 0x00321804:

| Bits | Value | True float | Gap |
|------|-------|-----------|-----|
| `0x38c90fdb` | 2pi/65536 | `0x38c90fdb` | exact |
| `0x40490fd0` | pi | `0x40490fdb` | 11 ulps **low** |
| `0x40c90fd0` | 2pi | `0x40c90fdb` | 11 ulps **low** |
| `0x3fc90fdc` | pi/2 | `0x3fc90fdb` | 1 ulp **high** |

The two low ones are the same variant [CarState](car-state.md) carries. The
pi/2 is the odd one out, a single ulp the other way, and it is the one that
reaches every cosine.

These are not cosmetic, and there is a concrete demonstration of that in
the mutation results below.

### What is not ported

`operator new` (0x0019c478) is `bOMalloc` on the slot pool at gp−23404 and
**ignores its size argument** — a slot pool only ever hands out one size.
`operator delete` (0x0019c468) is the matching `bFree`. Neither is ported:
the 3DS build does not use the PS2 slot allocator, and pretending to would
be a lie about where the memory comes from. The ignored size is recorded
here because it is the kind of thing that matters if the class ever grows.

`Steering::BaseDoSnapshot` (0x0019c558) and
`TwoWheelAckermanSteering::DoSnapshot` (0x0019bac0) need `ReplaySnapshot`,
the same dependency that has stopped `CarState::DoSnapshot`,
`Engine::DoSnapshot` and `CarDriver::DoSnapshot`.

`ComputeAuxiliaries` (0x0019c498) *is* ported, as an empty function, because
it is `jr ra ; nop` in the image and the physics dispatches through the
vtable — an absent one would be a silent no-op instead of a deliberate one.

### The destructor leaves the wrong vtable behind

`~TwoWheelAckermanSteering` (0x0019c4a0) stores `ACKERMAN_VTABLE`, then
calls `~Steering` with flags 0, which stores `STEERING_VTABLE` over the top,
and only then applies its own flags. A destroyed object is left carrying the
**base class's** vtable, not its own. The port keeps both writes in that
order rather than collapsing them, and the transcript checks which one
survives.

## Cross-check

```
python tools/steering_check.py            # 5 scenarios, 873 lines, 0 differ
python tools/steering_check.py --mutate   # 44 mutations, 43 caught, 1 equivalent
```

Two mutations from the first pass needed fixing rather than accepting:

* **`st-ack-clears-matrices` was caught for the wrong reason** — it used
  `memset`, which `steering.c` does not include a declaration for, so the
  compiler rejected it before the transcript got a look. Rewritten to zero
  the matrices with `bIdentity`, which compiles, and is then caught by the
  transcript on 64 lines.
* **`st-matrices-1` only tripped the static assert.** Shrinking the array
  *and padding behind it* leaves every offset and the total size exactly
  where they were, so the assert lets it through — the same trap
  [CarTypeInfo](car-type-info.md) turned up. `st-matrices-1-padded` does
  that, and is caught only by the printed extent.

### The one survivor, and why the constant makes it one

`st-fold-inclusive` changes `if (IMAGE_PI < rad)` to `<=`. It survives, and
it is genuinely equivalent **through this entry point**.

`rad` is `f32(bam * 2pi/65536)` for an unsigned 16-bit `bam`, so it takes
exactly 65536 values. None of them is the image's pi: across
`bam 32767 -> 32768` the products step `0x40490e49 -> 0x40490fdb`, straddling
`0x40490fd0` without landing on it. `rad == IMAGE_PI` never happens, so the
two comparisons agree everywhere.

Now notice what that argument rests on. Had the image used the *true* float
pi, `0x40490fdb`, then `bam 32768` would hit it exactly and the strict and
non-strict comparisons would disagree at that one steering value. The
eleven-ulp-low constant is the only reason this is a safe equivalence — which
is a fairly direct answer to the question of whether these constants are
worth carrying around.
