# The physics components as objects

The part of task 25 between the component classes and PhysicsCar. The
five components -- [RigidBody](rigid-body.md), [Wheel](car-wheel.md),
[Suspension](car-suspension.md), [Engine](car-engine.md) and
[DriveTrain](car-drivetrain.md) -- plus [Steering](car-steering.md) were
each ported and checked for their arithmetic. Every caller called them
directly. [PhysicsSystem](physics-system.md) is the first caller that goes
through a vptr, so each class now needs what the image gives it as an
object:

* its vtable;
* its destructor;
* its operator new and delete;
* the slot pool those draw on.

Ported to `3DS Files/source/physcomp.{c,h}`. Cross-checked by
`tools/physcomp_check.py` against `tools/src/physcomp_test.c`.

The per-class `.c` files are untouched. The one exception is Engine, whose
init now stores `_vt$6Engine` where it used to store the PhysicsComponent
table. Each class's own checker still holds its arithmetic.

## The tables

| Table | Address | Entries |
|-------|---------|--------:|
| `_vt$9RigidBody` | 0x002987e8 | 9 |
| `_vt$5Wheel` | 0x00298f20 | 9 |
| `_vt$10Suspension` | 0x00298fb0 | 9 |
| `_vt$6Engine` | 0x00297a78 | 9 |
| `_vt$10DriveTrain` | 0x00297a30 | 9 |
| `_vt$24TwoWheelAckermanSteering` | 0x00298ff8 | 4 |
| `_vt$8Steering` | 0x00299018 | 4 |

The five component tables have the same slot layout as
`_vt$16PhysicsComponent`:

| Slot | Method |
|-----:|--------|
| 8 | destructor |
| 16 | GetSize |
| 24 | `float *GetState()` |
| 32 | `GetState(float *)` |
| 40 | `SetState(float *)` |
| 48 | ResolveForces |
| 56 | `float *GetDerivative(float *)` |
| 64 | ComputeAuxiliaries |

**RigidBody is the only class with its own ResolveForces.** The other four
tables keep the base's slot 48, which is `jr ra`. Every delta and index is
0, because none of these classes has a second base.

The Steering tables use slot 8 for the destructor, 16 for
`SetSteering(unsigned short)` and 24 for `DoSnapshot(ReplaySnapshot *)`.
In `_vt$8Steering`, slots 16 and 24 are `__pure_virtual`. In the port they
are NULL, and `vt_slot` aborts on NULL as the image's handler does.

**One entry is pending.** Ackerman's DoSnapshot waits on ReplaySnapshot,
which is not ported, and no class's DoSnapshot is ported yet. The port
leaves that entry NULL, and the checker's `PENDING` records why.

### The simple slots

Each of these is a few instructions:

| Class | GetSize | `GetState()` | `GetState(float *)` / `SetState(float *)` |
|-------|--------:|-------------|--------------------------------------------|
| RigidBody | 32 | this+16 | 29 floats: seven `lqc2`/`sqc2` quads and one `lwc1`/`swc1` |
| Wheel | 2 | this+28 | 2 floats: an `ldl`/`ldr` pair and an `sdl`/`sdr` pair |
| Suspension | 2 | this+20 | 2 floats, the same way |
| Engine | 1 | this+12 | 1 float, `lwc1`/`swc1` |
| DriveTrain | 1 | this+12 | 1 float, the same way |

**RigidBody says 32 but copies 29.** The three floats past the state are
never read or written by the array copies. PhysicsSystem still allots 32
floats to the body, so the body's derivative has three slots that nothing
fills. The body's own checker covers what GetDerivative writes there.

Every `GetState()` offset is the record's `State` field, which the checker
confirms from the mdebug record.

## The destructors

g++ 2.9x destructors take a flags word. Bit 0 means free the object
afterwards. Bit 1 asks for virtual bases to be destroyed, and none of
these classes has any. A base or member destructor is called with bit 0
clear, so only the outermost call frees.

| Destructor | Address | What it does |
|------------|---------|--------------|
| `~RigidBody` | 0x00193fc0 | `~PhysicsComponent(this, 0)` |
| `~Wheel` | 0x0019b9e0 | `~SkidMaker(this+384, 2)` first, then `~PhysicsComponent` |
| `~Suspension` | 0x0019c418 | `~PhysicsComponent(this, 0)` |
| `~Engine` | 0x00182478 | stores `_vt$6Engine`, then `~PhysicsComponent` |
| `~DriveTrain` | 0x00183dc0 | `~PhysicsComponent(this, 0)` |
| `~TwoWheelAckermanSteering` | 0x0019c4a0 | stores 0x00298ff8, then `~Steering(this, 0)` |
| `~Steering` | 0x0019ba98 | stores 0x00299018, then `__builtin_delete` if bit 0 |
| `~PhysicsComponent` | 0x00192438 | stores 0x00298728, then `~bTNode` |

After destruction, a component carries **PhysicsComponent's vptr** and an
Ackerman carries **Steering's**. The harness reads that vptr back after
each destructor, because a freed slot keeps everything except its first
word (the free list's link). The vptr is at +8.

Each class's operator delete is the last step and runs only when
`flags & 1`. `~PhysicsSystem` destroys its components with flags 3
(0x001924b4), so each one goes back to its own pool.

**~SkidMaker is MakeNoSkid** (0x001a0c20):

```
lw   a0, 0(a0)            ; pSkidSet
beq  a0, zero, done
j    FinishedAddingSkids__7SkidSet
```

It tells the set it is finished and stores nothing, so the SkidMaker still
points at the set afterwards. SkidSet is not ported yet, so the call goes
through a seam, `gSkidSetFinishedAddingFn`. A wheel that has a set but no
seam installed aborts. A wheel whose SkidMaker never got a set -- every
wheel until skids are ported -- never reaches the seam.

**Engine's own vptr store is dead.** `~Engine` stores `_vt$6Engine`, and
`~PhysicsComponent` overwrites it with no virtual call in between. The port
keeps the store anyway, and the mutation pass lists removing it as
equivalent.

## Operator new and delete

Every class has a pool, and the new and delete for each class are the same
two sequences:

```
__nw__X:  lw a0, POOL(gp) ; jal bOMalloc
__dl__X:  move a1, a0 ; j bFree__FP8SlotPoolPv ; lw a0, POOL(gp)
```

`bOMalloc` is `SlotPool::Malloc`, the full path. That path clears a slot
when the pool's flags ask for it, and every pool here starts with flags 15,
so **a new component is zeroed**. The port's `X_new` is `bSlotOMalloc`,
which is the same call. The harness dirties each pool's first slot before
the news to prove the clear happens.

Aerodynamics has an operator delete but no operator new. The
constructors of PhysicsCar and MellowMover inline the `bOMalloc`
themselves, and the port provides `aerodynamics_new` for them to call.

## The pools

`InitPhysics` (0x00135068) makes ten pools, all in memory pool 16. n is
`TheRaceParameters.NumDriverInfo` (+756, at 0x00312814):

| Pool | gp | Slot | Count |
|------|---:|-----:|------:|
| RigidBody | -23408 | 384 | n + 32 |
| TwoWheelAckermanSteering | -23404 | 144 | n |
| Wheel | -23400 | 400 | 4n |
| Engine | -23396 | 92 | n |
| DriveTrain | -23392 | 148 | n |
| Aerodynamics | -23388 | 24 | n |
| Suspension | -23384 | 176 | 4n |
| Mellovator | -23380 | 448 | n |
| MellowMover | -23376 | 64 | n |
| NullMover | -23372 | 12 | n |

Three constructors load the RigidBody pool: PhysicsCar's, MellowMover's
and Smokeable's. A car is one or the other, so n covers the cars, and
**the 32 spare bodies are the Smokeables'**. **The port takes n as a
parameter** rather than reading the race parameters, which are not ported
yet. The port also sizes each pool with `sizeof`, which gives the image's
slot on the 3DS and a wider record on the 64-bit host. That includes
the last three pools: Mellovator and MellowMover came with the
MellowMover slice, and NullMover (`carmodes.h`) with Car's fourth, so
none of the ten is a constant any more.

`ClosePhysics` (0x001351b0) deletes all ten pools in the same order and
then zeroes all ten slots. None of the stores comes before a delete.

## Cross-check

```
python tools/physcomp_check.py            # 8 scenarios, 239 lines, 0 differ
python tools/physcomp_check.py --mutate   # 47 mutations, 46 caught, 1 equivalent
```

The model reads everything from the ELF:

* every table, entry by entry, out of .data;
* each simple slot, decoded from its instructions;
* InitPhysics, decoded call by call;
* each operator new and delete, decoded for its pool;
* each destructor, walked for the vptr it leaves behind and the bit it
  tests.

The port meets the model only in the transcript. The harness names each
table entry by the image method it stands for, from one registry. It runs
the simple slots on patterned objects. It runs the arithmetic slots of
RigidBody, Engine and Ackerman both through the table and by direct call,
and compares the results. Wheel's, Suspension's and DriveTrain's arithmetic
slots need a whole car, so they are checked only by table identity here,
and by PhysicsCar's checker through the system walk.
