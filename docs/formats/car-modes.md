# Car's modes

Car's fourth slice: who steers the car and what moves it.

| Method | Address | Bytes |
|--------|---------|------:|
| `Car::SetControlMode` | 0x0012fb50 | 484 |
| `Car::SetFrictionBoost` | 0x0012fd38 | 32 |
| `Car::SetMovementMode` | 0x0012fd58 | 484 |
| `Car::SetToPhysicsMode` | 0x0012ff68 | 92 |

These four methods come with the small classes they build or reach:

- **NullMover**, which `Car.obj` emits (0x00134ba0 .. 0x00134c50, plus
  Move at 0x0012f1f0).
- **NullController**, which `Car.obj` also emits (0x00134a60 ..
  0x00134b00).
- **NullDriver**'s five methods (0x00134c98 .. 0x00134cd0).
- **CarController**'s base (0x001b6068 .. 0x001b6168).
- **CarCollisionBody**'s `SetupPhysicsPointers` (0x001cda20) and
  `SetToPhysicsMode` (0x001cda80).

Part of task 25, after [Car](car.md)'s first three slices,
[PhysicsCar](physics-car.md) and [MellowMover](mellow-mover.md). This
slice is the first code that builds either of those two movers.

Ported to:

- `3DS Files/source/carmodes.{c,h}`
- `carcontroller.{c,h}`
- `carcollisionbody.c`, with the layouts in `collisionbody.h`
- `cardriver.{c,h}`

Cross-checked by `tools/carmode_check.py` against
`tools/src/carmode_test.c`, with the shipped image as the oracle.

## The shape of it

A car has one controller and one mover:

- **The controller** decides what to do: the pad, the race AI, traffic,
  a cop, or nothing.
- **The mover** makes it happen: the full simulation, the cheap one, one
  of four scripted ones, or nothing.

The controller owns a **driver**, the input record the mover reads, and
the car keeps a copy of that pointer at +44. So there are three pointers
to keep in step:

| Car | Field | Offset |
|-----|-------|-------:|
| `pCarController` | the controller | 40 |
| `pCarDriver` | the controller's `Driver` | 44 |
| `pCarMover` | the mover, whose `Driver` (+0) is the same driver | 48 |

`SetControlMode` and `SetMovementMode` are the only code that changes the
controller or the mover. Both have the same four steps:

1. Destroy the old one through its vptr, with flags 3.
2. Store the new mode.
3. Build the new one in one arm of a jump table.
4. In the tail, make the three pointers agree again.

## The two jump tables

### SetControlMode, a five-way table at 0x00292180

| Mode | Class | Built by | bMalloc |
|-----:|-------|----------|--------:|
| 0 `eNO_CONTROL` | NullController + NullDriver | inline | 12 + 560 |
| 1 `REAL_CONTROL` | RealController | `__14RealControllerP3Car` | 84 |
| 2 `AI_CONTROL` | AIDriver | `__8AIDriverP3Car` | 720 |
| 3 `TRAFFIC_CONTROL` | TrafficDriver | `__13TrafficDriverP3Car` | 720 |
| 4 `COP_CONTROL` | CopDriver | `__9CopDriverP3Car` | 76 |

Every allocation is `bMalloc(size, name, 0, 16)`, with the class name as
the name, and then the constructor on `(memory, car)`.

The tail is two stores: `pCarDriver = ctrl->Driver`, then
`pCarMover->Driver = pCarDriver`. **There must already be a mover.**

Car's constructor does not come through this method. It does these steps
itself (0x0012f494 .. 0x0012f4b8):

1. Builds the NullController and NullDriver.
2. Stores them at +40 and +44.
3. Builds a NullMover with only its `pState` and vptr, and stores it at
   +48.

**That first NullMover's `Driver` stays zero** from the cleared slot until
the first mode switch. When the constructor is ported, it should keep
that.

**The destroyed controller stays in `pCarController`** until the arm
overwrites it. A mode of 5 or more fails `sltiu v0,s0,5`, which skips the
table and runs the tail on that dead controller. The port aborts instead.

### SetMovementMode, a seven-way table at 0x00292200

| Mode | Class | Built by | Memory | PhysicsMode |
|-----:|-------|----------|--------|:-----------:|
| 0 `eNO_MOVEMENT` | NullMover | inline | NullMoverSlotPool | 0 |
| 1 `PHYSICS_MOVEMENT` | PhysicsCar | `__10PhysicsCar...` | bMalloc 116 | 1 |
| 2 `TRAFFIC_MOVEMENT` | TrafficCar | `__10TrafficCarP3Car` | bMalloc 36 | 0 |
| 3 `DELIVERY_MOVEMENT` | DeliveryMover | `__13DeliveryMoverP3Car` | bMalloc 192 | 0 |
| 4 `MELLOW_MOVEMENT` | MellowMover | its own | MellowMoverSlotPool | 1 |
| 5 `COP_MOVEMENT` | CopMover | `__8CopMoverP3Car` | bMalloc 112 | 0 |
| 6 `BELT_MOVEMENT` | BeltMover | `__9BeltMoverP3Car` | bMalloc 72 | 0 |

**PhysicsMode** is the collision body's field at +84. It is set to 1 for
the two movers that run a PhysicsSystem and 0 for the other five.

**The PhysicsCar arm** is `bMalloc` and the constructor, then three stores:

1. `pc->FrictionBoost = car->FrictionBoost` (PhysicsCar +108). The
   constructor sets its own FrictionBoost; the car's value replaces it.
2. PhysicsMode.
3. `pCarMover`.

**The NullMover arm** inlines both the pool's `new` and the constructor.
The slot comes back cleared, so the mover's `Driver` is zero until the
tail.

The tail is:

1. `CarCollisionBody::SetupPhysicsPointers`.
2. `pCarMover->Driver = pCarDriver`.

Mode 7 or more fails `sltiu v0,s1,7`, which skips the table. The tail
would then store into the mover just destroyed, so the port aborts.

### The mode is stored before the arm

Both methods store `TheControlMode` or `TheMovementMode` before they
dispatch. So a constructor that reads the car sees the new mode, and
`SetupPhysicsPointers`, in the tail, tests it.

A port that stored the mode at the end would pass every check that looks
only at the car afterwards. That is why the checker's stand-in
constructors print the two modes they find.

## Task 26's classes behind seams

Eight of the classes these two tables build belong to task 26:

- **Movers:** TrafficCar, DeliveryMover, CopMover, BeltMover.
- **Controllers:** RealController, AIDriver, TrafficDriver, CopDriver.

Three are ported: RealController ([real-controller.md](real-controller.md)),
BeltMover ([belt-mover.md](belt-mover.md), step 11e-6) and AIDriver
([ai-driver.md](ai-driver.md), step 11f-2). main.c sets their seams at
boot, and their `_SIZE` constants are `sizeof`. **Retail's SetControlMode
(0x00131410) asks 736 for AIDriver and TrafficDriver**, where the demo's
table above has 720; carmode_check runs the demo's and maps AIDriver's
size back.

Car allocates each one itself and hands the memory to the constructor, so
the port does the same. It calls the constructor through a pointer:

```c
typedef CarMover      *(*CarMoverCtorFn)(void *mem, Car *car);
typedef CarController *(*CarControllerCtorFn)(void *mem, Car *car);

extern CarMoverCtorFn gTrafficCarCtorFn;       // 0x00163018
...
extern CarControllerCtorFn gCopDriverCtorFn;   // 0x00197d48
```

**A NULL seam aborts.** It names the class it could not build, the way
`vt_slot` does on an entry nobody installed. When task 26 ports a class,
it sets that class's seam at boot and changes its `_SIZE` constant to
`sizeof`. The constants in `carmodes.h` are the image's mdebug sizes,
which a 64-bit host's records will not match.

## SetToPhysicsMode and SetFrictionBoost

**`Car::SetToPhysicsMode(other)`** hands the call to the controller, if
there is one, through its slot 88, and returns. With no controller, it
switches to `MELLOW_MOVEMENT` unless the mover is already one of the two
physics movers.

**CarController's own slot 88** does the same test and switch. **It does
not read its argument**: the test and the call are both on `this->pCar`.
NullController inherits it. So a car with no controller and a car with the
null one end up in the same place.

**`SetFrictionBoost(f)`** stores `f` in the car, and also in the
PhysicsCar at +108 when the mode is `PHYSICS_MOVEMENT`. MellowMover has no
such field.

## NullMover, 12 bytes

| Offset | Field | |
|-------:|-------|--|
| 0 | CarMover | `Driver` at 0, vptr at 4 |
| 8 | `pState` | the CarState it keeps the wheel matrices of |

Its table is CarMover's layout (`_vt$9NullMover`, 0x002923c0):

| Slot | Method | Address | What it does |
|-----:|--------|---------|--------------|
| 8 | destructor | 0x00134bd8 | its own vptr, then `~CarMover` with flags 0 (which puts CarMover's vptr back), then the pool's delete if bit 0 is set |
| 16 | Move | 0x0012f1f0 | `CarState::CalculateWheelMatrices`; returns `dt` unchanged |
| 24 | DoSnapshot | 0x0012f1e8 | CarMover's own, `jr ra` |

The pool is `NullMoverSlotPool` (gp-23372), made by `InitPhysics` with the
other nine (see [physics-components](physics-components.md)). **The port
sizes it with `sizeof(NullMover)`.**

**The constructor (0x00134c38) is ported but has no caller.** The only
code that makes a NullMover is SetMovementMode, and it inlines the
constructor.

## NullController and NullDriver

**Built in two places, the same way both times:** Car's constructor
(0x0012f400 .. 0x0012f490) and SetControlMode's arm 0. The steps are:

1. `bMalloc(12, "NullController")`, the CarController constructor, and
   NullController's vptr.
2. `bMalloc(560, "NullDriver")` and the CarDriver constructor, inline.
   The CarDriver vptr at 556 is stored in the delay slot before
   `__11DriveTarget`. The field stores follow, then `DriveTarget::Clear`
   with `$f12` loaded from the Throttle it has just zeroed.
3. The driver into the controller, then NullDriver's vptr.

`car_new_null_controller` does all of this. Car's constructor, when it is
ported, should call it.

**NullController** has no fields of its own; the type is 12 bytes, just
the base.

- **Its destructor** (0x00134aa0) stores its own vptr. It then destroys
  the driver through the driver's vptr with flags 3, so the driver frees
  itself, skipping this if the driver is NULL. Last, it runs
  `~CarController` with the caller's flags.
- **Its seven overrides** are `jr ra`. Three of them clear a return
  register in the delay slot:
  - GetCurrentRoute returns NULL.
  - GetCurrentRoutePoint returns NULL.
  - GetAmountOutOfBounds returns 0.0f.
- **Its table** also keeps five of the base's methods: DebugDisplay,
  DoSnapshot, SetToPhysicsMode, ForceBoost and ReleaseBoost.

**NullDriver** (`_vt$10NullDriver`, 0x00292400) is CarDriver's table with
six entries of its own:

- **The four that are pure in CarDriver:** Drive, SetLowGear,
  SetDesiredSpeed, and GetDriverNumber, which answers **-99999**
  (`lui v0,0xfffe ; ori v0,v0,0x7961`).
- **SetTarget.** CarDriver's copies all 528 bytes of the target;
  NullDriver's drops it.
- **Its destructor.**

DoSnapshot (slot 24) is CarDriver's in both tables. It waits on
ReplaySnapshot, so the port leaves it NULL.

## CarController's base, 12 bytes

| Offset | Field |
|-------:|-------|
| 0 | `pCar` |
| 4 | `Driver` |
| 8 | vptr |

- **The constructor** writes `pCar` and the vptr. **It does not write
  `Driver`.** Every subclass constructor sets that field.
- **The destructor** puts the vptr back and, if bit 0 is set, deletes.
  The driver is not the base's to destroy.
- **ForceBoost and ReleaseBoost** set `pCar->State.BoostFactor` to `f` or
  to 1.0. Both skip the store when `pCar` is NULL. The image also tests
  the CarState's own address (`addiu a0,a0,64 ; bnel a0,zero`), which can
  never be zero.
- **DoSnapshot** calls the driver's slot 24 and passes the snapshot on.
- **GetDriver** is `jr ra ; lw v0,4(a0)`.
- **Slots 32 .. 80** are `__pure_virtual`, and the port leaves them NULL.

## CarCollisionBody's two methods

**`SetupPhysicsPointers`** first clears the body's `pSystem` (+92) and
`pBody` (+96). Both stores come before any test, one of them in a delay
slot.

It then sets them only if PhysicsMode is non-zero and the car is under
`PHYSICS_MOVEMENT` or `MELLOW_MOVEMENT`:

- `pSystem` = the mover + 8, the PhysicsSystem base.
- `pBody` = the word at mover + 24, the RigidBody.

The image does not check which of the two movers it has, because both
keep those two things at the same offsets. Its `movz` guards a NULL mover
in the first store and then reads through the mover in the second.
SetMovementMode never leaves the mover NULL, and the port aborts if it
is.

**`SetToPhysicsMode(other)`** works out the car on the other side:

- `other`'s `pCar`, if `other` is a car's body. That means Type (+12,
  read with `lb`) is 0.
- NULL otherwise, or when there is no `other`.

It passes that car to `Car::SetToPhysicsMode`, then runs
`SetupPhysicsPointers` again. It is the only caller of
`Car::SetToPhysicsMode`.

The whole of `CollisionBody`, `DynamicCollisionBody` and
`CarCollisionBody` is laid out in `collisionbody.h`, field by field from
the stabs. The classes themselves belong to task 27. Its first slice of
them, the [bodies that do not move](collision-body.md), is
`collisionbody.c`. The two methods here are in `carcollisionbody.c`,
because they need `car.h` and the movers.

## The cross-check

```
python tools/carmode_check.py            # 74 transitions, 27324 lines, 0 differ
python tools/carmode_check.py --mutate   # 114 mutations, 114 caught, 0 equivalent
```

Those are this slice's figures. Car's reset group, the sixth slice, runs
in the same checker after the transitions and brings it to 74
transitions, 19 resets, 32797 lines, 0 differ, and 188 mutations, 185
caught, 3 equivalent ([car](car.md)).

The model borrows its machinery from `mellowmover_check` and
`physicscar_check`: the header parse checked against mdebug, the
generated dumps, and the emulator's stubs for the slot pools, the
terrain and the ticker. What belongs to this slice is below.

**The general heap is hooked on both sides.** On every `bMalloc`, the
model's stub and the harness's `bSetMemoryHooks` hook log four things:

- the name;
- the image's size;
- the flags;
- the pool.

The harness maps the host sizes of the three records the port allocates
back to the image's sizes, so the log shows the image's. A new block is
filled with 0xa5, a freed one with 0xdd, and neither is reused. So a
field a constructor forgets shows as 0xa5 on both sides.

That is how the transcript shows CarDriver's unwritten SportGear, and
the two bytes of padding after Steering.

**The eight stand-ins** are stubbed by symbol in the model. In the
harness they sit behind the seams. Each one logs what it is given and
the two modes it finds on the car:

- **A mover's constructor** writes its vptr.
- **A controller's** writes `pCar`, a new stand-in driver and its vptr.

Their tables live at fixed addresses above the image, and both sides
install them there.

**Labels during a call** name only the fixed objects and the heap's
blocks. While a call runs, the mover being torn down is half freed. The
port's slot pools also reuse slots the model's never do. So a
component's name could mean different memory on each side. After each
call, the dump names the new mover's components as well.

**Scenarios:**

- **The five tables,** slot by slot, against the port's function map.
- **Every ordered pair of movement modes,** as one Eulerian circuit of
  49 transitions. Then every pair of control modes, 25 more.
- **Control switches under the two physics movers.** The tail stores the
  new driver into whichever mover is there.
- **SetToPhysicsMode in each of the seven movement modes,** once with no
  controller, once with the null one and once with a stand-in.
- **The collision body's SetToPhysicsMode** with each kind of `other`: none,
  a car's body, and Type 1 and 0x80, which `lb` reads as negative. Each
  starts from stale pointers, so the set-up after the call shows even
  where the mode switch inside it already did one.
- **SetupPhysicsPointers** directly, for PhysicsMode 0, 1, 2 and -1.
- **SetFrictionBoost in each mode,** comparing the 128 bytes after the
  mover before and after the call.
- **NullMover, NullController and NullDriver** called through their own
  tables. A bare CarDriver from the image's out-of-line constructor, over
  the 0xa5 pattern, called through CarDriver's table.
- **The destructors without the delete bit,** then again with it. Then
  NullController's once more over a stand-in driver, which logs the
  flags it is handed.

### What the mutation pass said

**The first pass left two of the 114 alive.** Neither was equivalent, and
neither was a gap in the transcript's reach. Each was a place the dump had
no way to look:

- **`friction-mellow-too`:** SetFrictionBoost also storing into a
  MellowMover, through the PhysicsCar type. A MellowMover is 64 bytes and
  PhysicsCar's FrictionBoost is at 108, so the store lands 44 bytes into
  the *next* MellowMoverSlotPool slot (68 on the host, whose slots are
  112). No dump reaches a slot the car does not own. The friction
  scenario now compares the 128 bytes after the mover, before and after
  each call, in all seven modes.
- **`nc-dtor-driver-flags-1`:** NullController's destructor deleting its
  driver with flags 1 instead of 3. On a NullDriver the two do the same
  thing: CarDriver's destructor tests bit 0 alone (`andi s0,s0,0x0001`)
  and hands DriveTarget's a fixed 2, so bit 1 is read nowhere below. But
  3 is what the image passes, and a driver task 26 installs may read the
  other bit. The destructor scenario now runs NullController's once more
  over a stand-in driver, which logs the flags it is handed.

Both are caught now, and nothing is listed as equivalent.

**A store through the wrong type does not show up where it was aimed.**
Writing at an offset past the end of the real object lands in memory that
belongs to a neighbour, or to nobody, and a checker that dumps objects by
their fields will not look there. For each method that writes through a
cast, work out where the write lands in the other types it could hit, and
check that byte range.
