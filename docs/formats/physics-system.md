# PhysicsSystem, and the ticker it times itself with

`PhysicsSystem.obj` (0x00192438 .. 0x00192c28) and the ticker object
(0x00238d08 .. 0x00238d9c). Part of task 25, after
[RigidBody](rigid-body.md), [Suspension](car-suspension.md),
[Wheel](car-wheel.md), [Engine](car-engine.md) and
[DriveTrain](car-drivetrain.md) -- the five component classes this
integrator steps.

Ported to `3DS Files/source/physicssystem.{c,h}`, `bticker.{c,h}` and
`p32.{c,h}`. Cross-checked by `tools/physicssystem_check.py` against
`tools/src/physicssystem_test.c`.

## The shape of it

A PhysicsSystem is a list of PhysicsComponents and a running total of their
state sizes. It knows nothing about cars. A component is anything that can
say how many floats of state it has, copy them out and in, and write their
derivative; the system concatenates those into one vector and steps it.

| System | Components |
|--------|------------|
| PhysicsCar | a RigidBody, four Suspensions, four Wheels, an Engine, a DriveTrain -- 50 floats |
| MellowMover | two |
| Smokeable, Rocket, SmokeBomb, the dropped weapons | their own |

There are two integrators. **IntegrateEuler is the one the game runs.**
PhysicsCar::Move, MellowMover::Move and Smokeable::Move all call it.
IntegrateRungeKutta, a textbook RK4, has no caller anywhere in the image.
Both are ported.

## Layout

| Record | Size | Fields |
|--------|-----:|--------|
| PhysicsComponent | 12 | `pNext` 0, `pPrev` 4, vptr 8 |
| PhysicsSystem | 16 | `pNext` 0, `pPrev` 4, `Size` 8, vptr 12 |

The vptr goes after the data, as g++ 2.9x places it. The mdebug record
names only `ComponentList`; `Size` is a field the dump prints among the
methods (`Size:/01,64,32`).

The list is a `bTList<PhysicsComponent>`. Its head node is the system's
first eight bytes, so **the list's sentinel is the system itself**, and each
component's first eight bytes are its `bNode`. RigidBody, Wheel, Suspension,
Engine and DriveTrain each declare those three words as their own first
fields, so every one of them can be walked through the 12-byte view.

### Two vtables

| Slot | `_vt$16PhysicsComponent` (0x00298728) | `_vt$13PhysicsSystem` (0x00298708) |
|-----:|---------------------------------------|------------------------------------|
| 8 | destructor | destructor |
| 16 | GetSize (pure) | ComputeAuxiliaries |
| 24 | `float *GetState()` (pure) | ResolveForces |
| 32 | `GetState(float *)` (pure) | |
| 40 | `SetState(float *)` (pure) | |
| 48 | ResolveForces (`jr ra`) | |
| 56 | `float *GetDerivative(float *)` (pure) | |
| 64 | ComputeAuxiliaries (`jr ra`) | |

The pure entries point at `__pure_virtual` (0x00283c80). The port's
`vt_slot` aborts on them, which is what the image's handler does.

Derived systems -- PhysicsVehicle, then PhysicsCar, Smokeable, Rocket and
the weapons -- replace the system vptr with their own, and PhysicsCar's
table overrides the two methods. That is why the integrators finish with a
*virtual* ComputeAuxiliaries on the system: it is how PhysicsCar's override
gets run.

## The walk

GetDerivative, `GetState(float *)` and `SetState(float *)` are one loop with
a different slot (0x0019299c, 0x00192a24, 0x00192aac). The listing fixes
three details the shape of the code does not:

1. **The slot is called first and GetSize second.** Each component is asked
   its size again, *after* the slot call, rather than trusting `Size`. A
   component whose size changes inside GetDerivative moves every component
   after it.
2. **The next link is read after the calls** (`lw s0,0(s0)` at
   0x001929c0). A component that splices a node in after itself during the
   call gets that node walked.
3. **A size that is not positive still moves the offset.** Nothing guards
   `addu s2,s2,v0`.

## IntegrateEuler

0x00192580. The whole system's derivative goes into a 140-float stack
array. Then, for each component in turn:

* GetSize;
* `GetState()`, which returns a pointer to the component's live state;
* the next link is read (0x001925fc), *before* the state is written;
* `state[j] += dt * d[offset + j]`, in place;
* the offset moves by the size.

The update loop sits inside a `blez`, but the offset add (`addu v1,s2,s1`)
is on both arms. It finishes with the virtual ComputeAuxiliaries on the
system.

**140 is not checked.** Nothing compares a system's Size with the stack
array: GetDerivative writes as far as the components say. PhysicsCar's 50
floats fit. The constant comes from the frame layout (560 / 4).

**Nor is it cleared, and one component leaves a hole.** RigidBody's
GetSize is 32 and its GetDerivative writes 29, so the loop adds `dt` times
three uninitialised words to the body's tail padding every step. Nothing
reads the padding, so this reaches memory and never behaviour. The port
`memset`s the array before GetDerivative, a line the image does not
have, so the value is defined; physicscar_check's
model zeroes the image's array at the same point.

## IntegrateRungeKutta

0x00192728. Classical RK4, written with h = dt/2 computed as `dt * 0.5f`:

```
y0 = state;              d = f(y0)
k1 = h  * d;  SetState(y0 + k1); aux; d = f
k2 = h  * d;  SetState(y0 + k2); aux; d = f
k3 = dt * d;  SetState(y0 + k3); aux; d = f
k4 = dt * d
y  = y0 + k1/3;  y += k2 * 2/3;  y += k3/3;  y += k4/6
SetState(y); aux
```

k1 and k2 are taken over a half step, so the weights that make it RK4 are
1/3, 2/3, 1/3 and 1/6 (gp-30008, -30004, -30000). The usual 1/6, 1/3, 1/3
and 1/6 do not apply here. Every array call re-reads `Size` from the object
(`lw a2,8(s0)`, eleven times).

The three helpers it uses -- `ArrayMultiply`, `ArrayAdd` and
`ArrayMultiplyAndAdd` -- are free functions. Each counts `n` down and does
nothing when `n <= 0`, and each reads an element before writing it, so the
output may be the first operand.

## AddComponent, and who owns what

0x00192528 appends at the tail and adds the component's GetSize to `Size`.
It loads the component's vptr before writing any link, and **it reads
`Size` after GetSize returns** (0x00192560). A GetSize that moves `Size`
itself therefore is not overwritten.

The destructor (0x00192480) stores the PhysicsSystem vptr first. It then
takes the first component off the list and calls *its* destructor with
flags 3, meaning destroy and free, rereading the head each time until the
list is empty. After that, `~bTList` makes the same walk over the empty
list and returns through `~bList` and `~bNode`. The system frees itself
last if `flags & 1`.

So **a PhysicsSystem owns its components.** Destroying one destroys every
object that was added to it.

## ComputeAuxiliaries, and AuxTime

0x00192af8 calls every component's ComputeAuxiliaries in list order, times
the walk with the ticker, and stores the milliseconds in `AuxTime`
(gp-23232). **Nothing reads AuxTime**; the one reference in the image is
the store.

## The ticker

| | |
|---|---|
| `bInitTicker` 0x00238d08 | `jr ra` |
| `bGetTicker` 0x00238d10 | `mfc0 v0, Count`: the EE clock, 294.912 MHz, wrapping every 14.56 s |
| `bGetTickerDifference` 0x00238d20 | milliseconds between two ticks |
| `bGetFixTickerDifference` 0x00238d78 | `((to - from) << 6) / 293`, unsigned |

**bGetTickerDifference divides by 300 MHz** (gp-26980, `0x4d8f0d18`) rather
than 294.912 MHz, so every millisecond the game measures is 1.7% short.
That comes from the image and is kept. The difference is unsigned, so it
survives a wrap. It is converted in two steps because `cvt.s.w` is signed:
when the top bit is set, it converts `(d >> 1) | (d & 1)` and doubles the
result. Keeping the low bit as a sticky bit makes that exactly the
correctly rounded unsigned conversion.

On the 3DS, `bGetTicker` scales the ARM11 system tick (268.111856 MHz) to
294.912 MHz and truncates to 32 bits. A difference therefore means the same
number of EE cycles it did on the console, and wraps at the same period. A
harness installs a scripted source with `bSetTickerSource`. On the host,
the platform counter is always 0.

## p32

The image keeps every list link in a 32-bit slot, and so do the port's
component records, which is what lets their checkers hold each offset to
the image. On the 3DS a pointer is 32 bits and `p32_of` / `p32_ptr` are
casts. On the 64-bit host that runs the checkers, a slot holds a handle
instead: an index into a registry of every pointer stored so far, plus one,
so 0 stays NULL. The list walk is the same code on both targets, so the
harness exercises the walk the handheld runs. `p32_reset()` forgets every
handle between scenarios.

## Cross-check

```
python tools/physicssystem_check.py            # 12 scenarios, 739 lines, 0 differ
python tools/physicssystem_check.py --mutate   # 62 mutations, 61 caught, 1 equivalent
```

The model is written from the listing. Every slot, offset, size and
constant is read from the ELF: decoded from the instruction at a listed
address, loaded from gp or from a vtable in .data, or taken from the mdebug
record. None comes from the port's headers. The components in the
transcript are fakes with their own tables. They record every call, and on
request they misbehave: they splice a node in during a call, change their
size, drop out of the list, or unlink the next node. Those misbehaviours
make the order of reads visible.

The one survivor, `tk-unsigned-direct`, replaces the two-step conversion
with a direct unsigned one. The two are equal on every input. Checked,
not just argued: 723,967 values, covering every low byte under ~8000 high
parts plus 200,000 random values with the top bit set, and none
disagreed.
