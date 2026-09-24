# CONTINUE

Where the next session picks up. Updated in Session 29's
continuation (2026-09-23). `HANDOFF.md` is the running narrative; this file is the short
list of what to do next and what not to trust.

## State

**Phases 0-3 are closed.** Cars draw on the top screen out of
`CARS\*\GEOMETRY.BIN` (task 21), the frontend makes the disc's own menu
sounds through a ported `bSnd` over ndsp, and the geometry viewer is now
framed by the shipped `CM_ORBIT_CAR` boom on the ported `Camera` rather than
by a camera of its own -- all three heard or seen on Azahar, not just diffed.

Task 24 closed Phase 3: `TrackRoute.obj` is ported and the track's
centreline, its driving lines and its signposts all load. It is diffed, not
run -- see "Next" below for why, and for what task 27 owes it.

Forty-one cross-checkers pass, plus the table generators:

```bash
python tools/bvector_check.py && python tools/bmath_check.py && python tools/banim_check.py && python tools/bscreens_check.py && python tools/bootflow_check.py && python tools/bslotpool_check.py && python tools/geometry_check.py && python tools/texsrc_check.py && python tools/bui_check.py extracted/FRONTEND/FRONTB.BUN && python tools/sndbank_check.py out/SOUND && python tools/bsnd_check.py out/SOUND && python tools/emath_check.py && python tools/camera_check.py && python tools/trackroute_check.py && python tools/carstate_check.py && python tools/engine_check.py && python tools/cartypeinfo_check.py && python tools/cardriver_check.py && python tools/steering_check.py && python tools/rigidbody_check.py && python tools/suspension_check.py && python tools/wheel_check.py && python tools/drivetrain_check.py && python tools/drivetarget_check.py && python tools/graph_check.py && python tools/car_check.py && python tools/physicssystem_check.py && python tools/aerodynamics_check.py && python tools/physcomp_check.py && python tools/sinit_check.py && python tools/physicscar_check.py && python tools/mellowmover_check.py && python tools/carmode_check.py && python tools/joystick_check.py && python tools/joyhid_check.py && python tools/realdriver_check.py && python tools/quickspline_check.py && python tools/trackpath_check.py && python tools/average_check.py && python tools/airoute_check.py && python tools/realcontroller_check.py && python tools/gen_bmath_tables.py --check && python tools/gen_bsnd_tables.py --check && python tools/gen_scanner_tables.py --check
```

```
bvector_check      27 scenarios,  5721 lines, 0 differ   (23/23 mutations caught)
bmath_check        19 scenarios,  6424 lines, 0 differ   (9/9 mutations caught)
banim_check        23 scenarios,  2219 lines, 0 differ
bscreens_check     17 scenarios,  1246 lines, 0 differ
bootflow_check     12 scenarios,  3659 lines, 0 differ
bslotpool_check    17 scenarios,   990 lines, 0 differ   (37/37 mutations caught)
geometry_check     30 files,     42047 lines, 0 differ   (53/53 mutations caught)
texsrc_check       6 packs, 2 levels, 2958 textures, 0 differ
bui_check          FRONTB.BUN    1395 lines, 0 differ
sndbank_check      30 banks,       908 lines, 0 differ   (20000 mutations, 0 disagree)
bsnd_check         12 scenarios,  5157 lines, 0 differ   (25/25 mutations caught)
emath_check         9 scenarios,  2416 lines, 0 differ   (39/39 mutations caught)
camera_check        7 scenarios,  1200 lines, 0 differ   (40 caught, 7 equivalent)
trackroute_check   10 scenarios,   671 lines, 0 differ   (52 caught, 1 equivalent)
carstate_check     10 scenarios,   653 lines, 0 differ   (56 caught, 7 equivalent)
engine_check        8 scenarios,   414 lines, 0 differ   (56 caught, 2 equivalent)
cartypeinfo_check   4 scenarios,   177 lines, 0 differ   (40/40 mutations caught)
cardriver_check     5 scenarios,   118 lines, 0 differ   (45 caught, 1 equivalent)
steering_check      5 scenarios,   873 lines, 0 differ   (43 caught, 1 equivalent)
rigidbody_check    10 scenarios,   935 lines, 0 differ   (76 caught, 2 equivalent)
suspension_check   10 scenarios,  1108 lines, 0 differ   (66 caught, 2 equivalent)
wheel_check        19 scenarios, 10693 lines, 0 differ   (144 caught, 10 equivalent)
drivetrain_check   18 scenarios,   498 lines, 0 differ   (173 caught, 3 equivalent)
drivetarget_check  22 scenarios,   894 lines, 0 differ   (241 caught, 19 equivalent)
graph_check        16 scenarios,   151 lines, 0 differ   (21 caught, 4 equivalent)
car_check          58 scenarios,  4238 lines, 0 differ   (238 caught, 16 equivalent)
physicssystem_check 12 scenarios,  739 lines, 0 differ   (61 caught, 1 equivalent)
aerodynamics_check  7 scenarios,   107 lines, 0 differ   (74/74 mutations caught)
physcomp_check      8 scenarios,   239 lines, 0 differ   (46 caught, 1 equivalent)
sinit_check        10 calls,        0 problems           (6/6 mutations caught)
physicscar_check  106 scenarios, 102908 lines, 0 differ (257 caught, 6 equivalent)
mellowmover_check  39 scenarios, 56080 lines, 0 differ  (341 caught, 5 equivalent)
carmode_check      74 transitions, 27324 lines, 0 differ (114/114 mutations caught)
joystick_check     64240 ops,    75891 lines, 0 differ  (250 caught, 3 equivalent)
joyhid_check       every key and stick reaches its event
realdriver_check  152455 ops,    41163 lines, 0 differ  (118 caught, 4 equivalent)
quickspline_check   6640 ops,     6898 lines, 0 differ  (133/133 mutations caught)
trackpath_check     4771 ops,     4707 lines, 0 differ  (185 caught, 3 equivalent)
average_check        482 ops,      843 lines, 0 differ  (64/64 mutations caught)
airoute_check      14738 ops,     7224 lines, 0 differ  (86 caught, 5 equivalent)
realcontroller_check 14096 ops,  25318 lines, 0 differ  (129 caught, 11 equivalent)
gen_bmath_tables --check           bmathtab.c is up to date
gen_bsnd_tables  --check           bsndtab.c is up to date
gen_scanner_tables --check         joyeventid.h, scannertab.c are up to date
```

`texpack_check.py` takes a file and is run per pack; it now also diffs the UV
scroll, offsets and all: `FRONTB.BUN` 2 scrolling textures, `INGAMEB.BUN` 1,
`TEX12LOCATION.BIN` 21, 0 differ.

Two mutation runners are kept rather than thrown away:
`python tools/bslotpool_mutate.py` (~20 minutes) and
`python tools/geometry_mutate.py` (~2 minutes; `--full` for all 30 files).

Both sound checkers want a directory of `.SBK`. Build it first:

```bash
python tools/audio_pack.py extracted/SOUND out/SOUND
```

The emulator's copy lives at `%APPDATA%\Azahar\sdmc\NFSHP2\SOUND` -- that is
the data root `gamedata.c` resolves to on this machine, and the
`.SBK` files go beside the other converted assets. `bsnd_check.py --mutate`
takes about ten minutes; `sndbank_check.py --mutate 20000` takes a couple of
hours.

`camera_check.py --mutate` reports "7 equivalent, 0 unexplained" rather than
"7 survived": the seven are named in the script with an argument each, and
three of them are uncatchable because the disc's velocity record is
structurally zero. See `docs/formats/camera.md`. `trackroute_check.py
--mutate` reads the same way and takes about four minutes.

Open tasks: **6** (26-31). All four the user asked for mid-session are
done and looked at on Azahar: 32 (stretch the frontend to the 3DS's 5:3 top
screen), 33 (the ten unregistered screen names), 34 (the menu description on
the bottom screen, wrapped) and 35 (no console sharing that screen).

The bottom screen is a citro2d target now, not a console. Everything the
console used to show is in `sdmc:/nfshp2_debug.txt`, which is opened `"w"`
and so replaced every boot.

## Next, in order

1. **Task 26's second slice is closed: `TrackedController` and
   `RealController`**, which is what builds a RealDriver, with
   `DriveTargetRenderer`'s flag-off path. `gRealControllerCtorFn` is set at
   boot and `REALCONTROLLER_SIZE` is `sizeof`. See
   `docs/formats/real-controller.md`. `realcontroller_check` runs the
   image in mipsemu as the oracle: 14,096 ops, 25,318 lines, 0 differ,
   and 129 of 140 mutations caught with 11 equivalent.
   The first slice (Session 29) was `Joystick.obj`, the generated
   `ScannerConfigTable`, the 3DS HID backend and `RealDriver`; the
   prerequisites were `QuickSpline.obj`, `TrackPath`'s manager and
   coordinate, `Average` and the AI's four route helpers.

   - **The image check found a DriveTarget bug that its own checker had
     passed.** FillWithCurrentAcceleration integrates while the
     acceleration is *under* three quarters of the speed, and falls back to
     a straight line past it. The port and `drivetarget_check.py`'s model
     both had it the other way round, so they agreed with each other. Both
     are fixed, and the `fi` fixtures were re-derived. See "What not to
     trust" and `car-drive-target.md`.
   - **A predicted point's pad is garbage on the console**:
     `GetPosition(bVector3)` stores a VU0 lane it never set. It is not
     compared (STACK-W).
   - Think's wrong-way test is `pPlayer->bWrongWay` (Car+24, then
     Player+736). An earlier note here said pRideInfo; that was wrong.
   - Then the rest of task 26: the other seven classes behind Car's
     constructor seams (`carmodes.h`), Player, the race and cop AI, the
     pursuit, and Car's reset and damage methods listed in TASKS.md.
   - The menus still take their input from `kBinds` in `main.c`. It moves
     onto the joystick path when the frontend's
     `AddNormalMenuJoyHandlers` is ported with the screens that use it.

   **Task 25**, the car simulation -- **closed**; the notes below are
   kept for what they teach. It was **much bigger than the task list
   said**. Nineteen slices are closed: `CarState`, `Engine`
   + `Table`, `CarTypeInfo`, `CarDriver` + `DriveTarget`'s layout,
   `Steering` + `TwoWheelAckermanSteering`, `RigidBody`, `Suspension`,
   `Wheel`, `DriveTrain`, `DriveTarget`'s methods, `Graph`, **`Car`'s
   record plus three code slices**, `PhysicsSystem` and `Aerodynamics`,
   the component vtables, **`PhysicsCar`**, and **`MellowMover` with its
   `Mellovator`**. Each has a checker and a doc under `docs/formats/`.
   Most are `car-*.md`; `RigidBody`'s is `rigid-body.md`, `Car`'s is
   `car.md`, and the rest are `physics-system.md`, `aerodynamics.md`,
   `physics-components.md`, `physics-car.md` and `mellow-mover.md`.

   The old "178 functions, 16680 bytes" note was wrong by an order of
   magnitude -- it matched a narrow symbol pattern and missed most
   methods. Remeasured by demangling every symbol to its owning class,
   task 25 was ~39.9 KB across 140 functions. Thirty-nine Car methods,
   `PhysicsCar`, the `Mellovator` and `MellowMover` are ported, so
   **18.8 KB across 41 functions** is still to go, all of it `Car`'s:

   ```
   Car 41 funcs 19256 B   (done: PhysicsCar 16 / 8496,
                           Mellovator 31 / 5420, MellowMover 13 / 3096)
   ```

   Three `DoSnapshot`s are counted as done but are not: PhysicsCar's,
   MellowMover's and the Mellovator's wait on `ReplaySnapshot`.

   `PhysicsSystem` (`0x00192460`, ~1.2 KB) and `Aerodynamics`
   (`0x001a4b58`, ~0.65 KB), which `PhysicsCar`'s constructor needs and
   the count never had, are ported now -- see below.

   The thirty-nine are 3620 B of the 22876 -- the cheap ones went
   first, and the expensive half of Car is the constructor, the reset
   and damage groups and the render path.

   **Car's third code slice is closed** -- `IsCarToLeft`,
   `IsCarToRight`, `GetRelativeCarPosition`, `IsCarInFront`,
   `GetPostCollisionYawControlBoost`, `IsDrifting` and `ComputeFakeRPM`
   with `smooth<float>`, and `bToPolar`, which `bmath.c` had never had
   although `bmath.md` said all nineteen were ported. 58 scenarios,
   4238 lines, 0 differing; 254 mutations, 238 caught, 16 equivalent, 0
   unexplained. Poke an aliased array to make a shipped-invisible
   branch visible: the yaw profile and `RPMTable`'s neighbours are both
   fixtures now.

   **Car's second code slice is closed** -- the vtable seam
   (`vtable.{c,h}`), the nine dispatchers, the three borrowed fields,
   both `CalculateDraftFactor`s and `_GLOBAL_$I$fDraftFalloff`. 42
   scenarios, 3864 lines, 0 differing; 178 mutations, 169 caught, 9 equivalent, 0 unexplained. Read the second half of
   `docs/formats/car.md` before the next slice, and in particular:

   - **Virtual calls go through `vt_slot` / `vt_this`**, keyed by the
     image's own vtable address. A class that installs a real table
     computes its deltas with `offsetof`: the host's slack moves bases.
   - **Static initialisers run from `sinit_run()`**, which `main.c`
     calls first thing, in `__CTOR_LIST__` order. A new `*_static_init`
     that is not added there fails `sinit_check`. Four had been ported
     and never run before this.
   - **A boundary fixture is not a boundary test until the boundary can
     be reached from it.** The draft's reach at 60 is visible only
     through `dot / dist` rounding above 1, which no single-axis fixture
     can produce.

   **`PhysicsSystem` and `Aerodynamics` are closed**, with two pieces
   the system needed: the EE ticker (`bticker.{c,h}`) that times
   `ComputeAuxiliaries`, and `p32.{c,h}`, which lets a 32-bit link slot
   hold a pointer on the 64-bit host, so the list walk the checker runs
   is the code the handheld runs. `physicssystem_check`: 12 scenarios,
   739 lines, 0 differ; 62 mutations, 61 caught, 1 equivalent -- and the
   equivalent was checked over 723,967 inputs, not just argued.
   `aerodynamics_check`: 7 scenarios, 107 lines, 0 differ; 74 mutations,
   74 caught. What matters for `PhysicsCar`:

   - **IntegrateEuler is the only integrator the game runs.** RK4 is
     ported and has no caller anywhere in the image.
   - **A PhysicsSystem owns its components.** Its destructor destroys
     every one with flags 3, so nothing else may free them.
   - **The walk asks each component its size after the slot call**, and
     reads the next link after it too. `Size` is only trusted by RK4.
   - **Aerodynamics' downforce is linear in speed**, and its "direction"
     is not a unit vector unless Boost is 1.
   - **`ApplyForceInFrame` had no checker before this one.** It has now:
     two `bMulMatrixVector`s, the first a `j` thunk, then `ApplyForce`.
   - `SetGroundEffect` was missing from the port and is in it now.

   **The component vtables are closed** -- `physcomp.{c,h}`: all seven
   tables at the image's addresses, the eight destructors, every
   operator new and delete, and `InitPhysics` / `ClosePhysics` with the
   ten slot pools. `physcomp_check`: 8 scenarios, 239 lines, 0 differ;
   47 mutations, 46 caught, 1 equivalent. `main.c` installs the tables
   right after PhysicsSystem's. Read `docs/formats/physics-components.md`
   first; what matters for `PhysicsCar`:

   - **A new component is zeroed.** Every pool starts with flags 15, and
     `bOMalloc` clears the slot, so the constructors lean on it.
   - **After destruction a component carries PhysicsComponent's vptr**
     and an Ackerman carries Steering's; a freed slot keeps everything
     but its first word.
   - **Engine's own vptr store in `~Engine` is dead** -- the base
     overwrites it -- and is the one equivalent mutant.
   - **`~SkidMaker` is `MakeNoSkid`**, which goes through a seam,
     `gSkidSetFinishedAddingFn`; a wheel with no set never reaches it.
   - **The pools take n as a parameter**, since the race parameters
     are not ported. The RigidBody pool's 32 spare slots are the
     Smokeables'. NullMover's slot size is an image constant in
     `physcomp.h` until that class exists; the Mellovator's and
     MellowMover's are `sizeof` now.
   - Ackerman's `DoSnapshot` is the one NULL entry, pending
     `ReplaySnapshot`, and the checker says so on every run.

   **`PhysicsCar` is closed** but for `DoSnapshot`, and three small
   modules `Move` reads came with it: `race.{c,h}`, `cardamage.{c,h}`
   and `joystick.{c,h}`. `physicscar_check` is the first checker whose
   oracle is the image itself. `mipsemu` runs the shipped constructor,
   both integrators, UpdateCar and Move, with every component method
   they reach, and the harness runs the port on the same records. 106
   scenarios, 102908 lines, 0 differ; 263 mutations, 257 caught, 6
   equivalent, 0 unexplained. Read `docs/formats/physics-car.md`. What
   matters next:

   - **Two older ports were wrong, and their models agreed with them.**
     GetLateralForce's curve scale is 12 (`lui at,0x4140`), not 11, and
     CheckTerrain's fifth argument is the terrain it refreshes. A model
     written from the same reading as the port is not an oracle.
   - **A car sitting in gear divides zero by zero**, in DriveTrain's
     clutch split. The EE gives FLT_MAX and IEEE gives NaN. A divide that
     can see 0/0 uses `ee_div` (`eefpu.h`), and mipsemu's `eediv_pcs`
     lists every one a run reaches.
   - **The image reads uninitialised stack words** in six places. The
     port writes zero, and the model hooks the image to zero them too.
   - **`hostbuild` caches objects**, so a mutant rebuilds one file, and
     `diff_count` replaced difflib. A PhysicsCar mutant takes about 2 s,
     down from minutes.

   **`MellowMover` and its `Mellovator` are closed** but for their two
   `DoSnapshot`s. `mellowmover_check` runs the image the same way: 39
   scenarios, 56080 lines, 0 differ; 346 mutations, 341 caught, 5
   equivalent, 0 unexplained. Read `docs/formats/mellow-mover.md`.
   What matters next:

   - **`.lit4` is not always the nearest float.** The half-pi is
     `0x3fc90fdc`, one ulp high, and it feeds `bSin`'s truncation to a
     BAM. The checker reads all eighteen pool constants back out.
   - **An airborne, level car divides 0/0 in `bNormalize3To`**, which
     now uses `ee_div`.
   - **Three synthetic records**: car 0 with CoG.y 0.0625, car 0 with
     the droop stops at -2, and car 34 for its two final drives. The
     shipped data hides those branches.

   **Car's fourth code slice is closed** -- `SetMovementMode`,
   `SetControlMode`, `SetToPhysicsMode`, `SetFrictionBoost`, with
   `NullMover`, `NullController`, `NullDriver`, the `CarController` base
   and `CarCollisionBody`'s two methods. `carmode_check`: 74
   transitions, 27324 lines, 0 differ; 114 mutations, 114 caught.
   `wheel_install_seams()` runs at boot. Read `docs/formats/car-modes.md`;
   what matters next:

   - **Task 26's eight classes are behind constructor seams** in
     `carmodes.h` (`gTrafficCarCtorFn` .. `gCopDriverCtorFn`). A NULL seam
     aborts and names the class. Porting one means setting its seam at
     boot and changing its `_SIZE` constant to `sizeof`.
   - **Both methods store the mode before the arm runs**, so a
     constructor that reads the car sees the new mode.
   - **A store through the wrong type lands in the neighbour.** Check the
     bytes past an object, not only its fields.

   **`Car`'s record is whole and its first code slice is closed.** The
   2016-byte layout is in `3DS Files/source/car.h` -- 72 offsets, each
   re-derived from a load or a store -- and it has been through the ARM
   build, where every `CAR_SLACK` term is zero and `CAR_AT(f, n, k)`
   reduces to the console's raw offset. `TopologyCoordinate` came with it,
   layout only, in `topology.h`, because Car embeds one by value and its
   128-pointer table would have made a blob agree with the wrong number on
   the host.

   The first slice's eighteen are the three retail stubs, the blinking,
   the debug checksum, the two wheel aggregates, the two effect gates,
   the forward acceleration, the horn request, the wiper window, the
   borrowed steering angle and the eight-byte `WorldToCar` forwarder.

   Read `docs/formats/car.md` before the next slice. Three things in it
   cost time to find: `GetWheelTraction` pairs the **diagonals**, not the
   axles; `IsBlinking` has **two** sentinels, 0 and `0x7fffffff`; and
   `cvt.w.s` saturates by the sign of the source, which x86 does not do
   and ARM does, so the conversion is written out rather than cast.

   **That order used to read "PhysicsCar, Car" and it was wrong.**
   `PhysicsCar::Move` (`0x00135c78`) calls three `Car` methods and reads
   seven `Car` offsets outside the embedded `CarState`, so the
   `CarState`-only stand-in that carried `DriveTarget` does not carry
   `PhysicsCar`. `Car` comes first. Checked in the disassembly, the same
   way `DriveTarget`'s independence from `Car` was.

   **This said two small things came before `Car`. It was one.**
   `Graph` (`0x00187440`, `0x00187450`) is ported. The second --
   `CarState::WorldToCar` at `0x001b6ab0` -- turned out to have been
   ported already, by the `CarState` slice: both overloads, three
   mutations, and a paragraph in `docs/formats/car-state.md` about the
   quadword subtract in the 3D one. The plan was written off a symbol
   search rather than off `carstate.c`, and a search for the PS2 name
   does not find `carstate_world_to_car2`. **Before porting anything a
   plan calls a prerequisite, grep the ported sources for it under the
   name the port would have given it, not the name the ELF has.**

   ```
   Graph  0x00187440, 0x00187450   8 bytes, 2 methods; four Car methods
                                   want it. Ported -- 16 scenarios,
                                   25 mutations, docs/formats/car-graph.md
   ```

   **And the same mistake was underneath it twice.** That paragraph used
   to end by saying `DriveTarget::Dump` was still blocked on
   `Car::WorldToCar`. It was not: `drivetarget_dump` has been in
   `drivetarget.c` since the DriveTarget slice, and it reaches the
   transform the way the forwarder would have -- `carstate_world_to_car2(
   &car->State, ...)`, which is the `+64` written out. `docs/formats/
   car-drive-target.md` said so at the time ("It is ported anyway, for two
   reasons") and the planning note was never corrected to match.

   So the lesson above is not about one symbol. **A plan's "blocked on"
   list decays; the ported sources do not. Check the source before
   believing the plan, every time, including when the plan is this file.**

   `Car::WorldToCar` (`0x00138e90`) is ported now regardless -- it is a
   real method of the eighty and it is eight bytes, `j
   CarState::WorldToCar; addiu a0,a0,64` -- so the forwarder exists under
   its own name for the next caller that wants it.

   **`Car` is the hub, not the physics -- measured, not assumed.**
   Eighty methods, 22876 bytes, `Car.obj` at `0x0012f150` (`0x5e1c`).
   Six are emitted outside that object, including the eight-byte
   `Car::WorldToCar` at `0x00138e90`. The record is 2016 bytes with one
   non-virtual base at offset 0, `bTNode<Car>` (8 bytes) -- **`Car` has
   no vtable**; the `__pure_virtual` the map shows against `Car.obj`
   belongs to the `CarDriver` / `CarMover` / `CarController` abstract
   bases that share the object.

   **Thirty-four of the eighty make no call outside the class, and thirty
   of them are ported.** The other four are `SetToPhysicsMode` and
   `SetFrictionBoost` (both PhysicsCar's), `DoWheelForces` (force
   feedback) and `PutFlatOnTrack` (a real `TopologyCoordinate`, task 27).
   The split is over all eighty, and seventy-four of those are in
   `Car.obj`; `WorldToCar` is one of the six emitted elsewhere, and it is
   in the forty-six because its `j` leaves the class. Two of the forty-six
   are ported. The partition is spelled out at the bottom of `car.c`.

   The other forty-six reach about a dozen subsystems belonging to tasks
   26, 27 and 29: replay, cop manager, the effect system, force feedback,
   sound, topology, collision, render info, damage, `Player` and `Race`,
   and eleven driver/mover classes that `SetControlMode` and
   `SetMovementMode` construct between them. The next slice is named
   above; `HANDOFF.md`'s Session 25 entry has the scan behind it.

   Two `DriveTarget` methods are blocked, and always were two rather than
   the three this file used to list: `DoSnapshot` on `ReplaySnapshot`, and
   the `DrivingLocation` overload of `AddPointToTarget` on
   `DrivingLocation::IsClear`, which is `lw v0,0(a0); sltiu v0,v0,1` and
   has a one-word stand-in until task 26 brings the class.

   `drivetarget.h`'s stand-in `Car` is **gone**; it includes `car.h` now.
   Two consequences, both already handled. The include-ordering rule
   car.h's header describes is retired -- either order gives the real
   record. And `drivetarget_check`'s `[layout]` scenario changed, because
   the stand-in's padding was written to cancel the host's pointer slack
   and the real record does not: the three offsets read 18, 48 and 112 on
   this host, which is `CAR_AT(DriverNumber, 10, 2)`,
   `CAR_AT(pPlayer, 24, 6)` and `CAR_AT(State, 64, 12)`. On ARM they are
   10, 24 and 64 again. The two mutations that used to aim at the stand-in
   now aim at `car.h`.

   `car.h` names `CarTypeInfo` and `CarDriver` rather than including
   their headers, because `cardriver.h` -> `drivetarget.h` -> `car.h` is
   a cycle: with the include in place, compiling `cardriver.c` reaches
   `struct Car` before `CarDriver` is defined. `car.c` includes
   `cardriver.h` itself for `pCarDriver->Steering`.

   **Mutation passes are crash-safe now.** A stopped `drivetarget_check
   --mutate` had left `sr-count-signed` in `drivetarget.c` -- equivalent,
   so plain runs stayed clean -- and `camera_check`/`trackroute_check`
   had been restoring with a translating write, which put CR CR LF on
   every line of `camera.c`, `cammover.c` and `trackroute.c`. All four
   repaired (the three are byte-identical to HEAD again), and every
   checker's `write_source` is `hostbuild.write_source` now: it parks the
   original as `<name>.<pid>.mutate-backup`, and `hostbuild.build()`
   restores any whose process has died. **Still: never edit a source a
   live pass compiles, and never run two passes that mutate one file
   -- the second now stops at its first write to that file rather than
   restore the first one's mutant for it.** A pass that must run beside
   another that mutates a file it links can run from a copy of the tree:
   every checker finds its sources from its own path, so `tools/`,
   `3DS Files/source/`, the ELF, `docs/mdebug_structs.txt` and the two
   extracted bundles are enough (Session 30).

   **`Wheel`'s two seams are wired but nothing installs them, and their
   home is now known.** `wheel_install_seams()` points
   `gWheelFindDrivingSurfaceFn` and `gWheelExchangeZForcesFn` at the
   real methods, and no code in `3DS Files/source/` calls it, so they
   are still `NULL` on hardware. That is correct today -- nothing
   constructs a `Suspension` or a `Wheel` yet -- but the call belongs in
   **`Car::SetMovementMode`'s `PHYSICS_MOVEMENT` arm**, which is what
   constructs the `PhysicsCar` that owns the `Suspension` and the four
   `Wheel`s, and it has to happen before that car's first
   `ResolveForces` or every corner reports airborne. The seams are a
   port artifact: at `0x0019bdd4` and `0x0019c104` the PS2 build makes
   two ordinary `jal`s.

   The HUD split is settled, below.
2. Then in order: 26 race/cop AI, 27 track render/stream/collision,
   28 New3DS perf, 29 save/options/sound mix, 30 split-screen scope,
   31 final CIA + Old3DS/New3DS pass.
3. **`QuickSpline.obj` (`0x00227e98`) is owed to task 24 and belongs to
   task 27.** `trackroute.c` is diffed but cannot be run for real without
   it: `TrackPathCoordinate::UpdatePosition` (`0x1f5dd0`) is the stub that
   turns a world position into a distance around the track, and
   `SetFirstAndLastPoints`, `Signpost::SetDistances` and
   `TestSignpostConsistency` all go through it. `gTrackPathDistanceFn` is
   the seam -- `NULL` on hardware, a closed-form ramp in the harness. Port
   `QuickSpline`, point the seam at it, and those three become live.
   The CM_TRACK_* movers `cammover.c` left out want the same thing.
4. Whenever a screen class gets ported, take its row in `kScreens[]` off
   `bgf_plain_screen_callback`. Ten of the eighteen are on it -- they draw
   and answer the D-pad and nothing else -- and
   `python tools/screen_registry.py --check-port` lists them, along with
   anything new the port can reach and has not registered. Run it after any
   change to `kScreens[]`: a hash typed by hand is not checked by anything
   else, and a name with no row is a black top screen, not a no-op.

**Phase 4 constraint, from the user:** the gameplay HUD is to be designed for
**two screens from the start** -- readouts on the bottom screen rather than
all stacked on the top one, to keep the view of the road clear.

The split is **decided** (2026-09-21, asked and answered): **bottom screen
takes the minimap, lap/position and objective text; the top keeps the
speedo/tach and the pursuit meter**, because those two are monitored
continuously rather than glanced at and belong in the same eyeline as the
road. Build tasks 25-27's HUD to that from the start rather than making a
top-screen HUD and splitting it later. `uirender.c` (citro2d) is the home
for the bottom-screen widgets; `georender.c` (citro3d) owns the top. Also
at the head of Phase 4 in `TASKS.md`.

## What not to trust

Ordered roughly by how much time it costs to rediscover.

* **A checker whose model was written from the disassembly can share a
  misreading with the port.** `drivetarget_check`'s model and
  `drivetarget.c` both had FillWithCurrentAcceleration's first test
  negated. The two agreed, and the checker's own `fi-dominates-flipped`
  mutant was "caught" against the wrong answer. Only running the image
  (`realcontroller_check`) showed it. The image-backed checkers are
  airoute, average, car, carmode, joystick, mellowmover, physicscar,
  quickspline, realcontroller, realdriver and trackpath. Every other
  `*_check.py` compares against a Python model, which includes most of
  task 25: carstate, engine, cartypeinfo, cardriver, steering, rigidbody,
  suspension, wheel, drivetrain, drivetarget, graph, physicssystem,
  aerodynamics and physcomp. car_check, physicscar_check and
  mellowmover_check do run the image's copies of some of those beneath
  them, but only as far as their scenarios reach. A model-only pass is
  evidence that two readings agree, not that either matches the console.
* **A scenario that hands a mover the Car's own CarState cannot tell
  `State` from `pCar->State`.** MellowMover reads each in different
  places. In the game they are the same object, so a port that mixed
  them up would pass every such scenario. `mellowmover_check`'s
  `c0-apart` passes a copy with a different ForwardSpeed, and task 26's
  movers want the same.
* **A NULL seam that the image calls unconditionally needs its NULL case
  checked too.** `realdriver_check`'s seam mask does this: a clear bit
  leaves the harness's pointer NULL and makes the model's stub silent,
  answering what the port assumes. Without it, the port's "skip when
  NULL" branches are code no checker has run.
* **Two calls that share no state have an order only their logs can
  show.** RealDriver's Drive could run DoSteering before
  DoThrottleBrakeReverse and every dumped field would agree. A mutant
  that swaps them needs a frame on which both of them log something.
* **A decimal constant is not the pool's bits.** The `.lit4` half-pi is
  one ulp above the float nearest pi/2, and the port's first BAM-to-radian
  constant was a digit short. Write the bits beside the literal
  (`// gp-27752  38d1b717`) and have the checker read the pool.
* **Shipped data hides branches.** CoG.y is 0 in all 66 car records, 61
  have equal final drives, and 21 have CoG.x 0. A survivor on shipped
  records may want a copy of a real record with one field changed, not a
  new scenario.
* **The Microsoft Store Python virtualises writes under `AppData`.** A
  file it writes there is not where the shell or a harness looks for it.
  Debug output goes under the repo's `out/`.
* **A format loaded by casting has no parse step to get wrong -- the struct
  layout *is* the format.** `TrackRoutesLoader` casts the chunk's bytes to
  `TrackRoute *` and registers the pointer; nothing is copied and nothing is
  read field by field. So a field at the wrong offset is not a compile error
  and not a decode failure, it is a route that loads and then reads
  nonsense. Two things follow, and both bit this session: the record's
  `pNext`/`pPrev` are **32-bit slots holding disc garbage**, not host
  pointers, and `sizeof` has to be asserted -- it came out 115760 instead of
  115752 on the 64-bit host and only the harness noticed. Any future
  cast-loaded chunk wants the same assert and the same byte-image model in
  its checker.
* **A `bChunk` header of all zeroes is padding, not a terminator.**
  `bchunk_dump.py` stopped at the first one and so reported 8 chunks in
  TRACKB12.BUN's 9 MB, having given up at the alignment run at `0x7048`
  after five top-level chunks. The real counts are 472 top-level (25
  zero-pad headers among them) and 7076 recursively. `bchunk.c` had always
  skipped them, so the C and the tool disagreed silently. Fixed this session
  -- but the lesson is that the dumper is not the authority, the loader is.
* **The task list can be wrong about what a format even is.** Task 24 asked
  for an "`espEmptyLayer` spline/track-layer format". No such format exists:
  Espresso is bware's live editor RPC protocol and Caffeine is the PC end of
  it, evidenced by `EspressoServer`, the `Caffeine = %d, Espresso = %d`
  version handshake and an `EspressoFunctions` enum of `EF_LoadWorld`-style
  members. Half a day can go into looking for a file format that was never
  a file format. Check the strings and the mdebug enum before believing a
  name in `TASKS.md`.
* **A PARTIAL from `run_azahar_test.ps1` is worth re-running before it is
  worth debugging.** The harness drives Azahar with synthesised keystrokes
  and it can drop one; a dropped A at the main menu walks the rest of the
  script down the wrong branch and the verdict blames the wrong thing. The
  same build went PARTIAL then PASS with nothing changed in between.
* **The Bash tool eats one level of backslash inside a heredoc.** A patch
  script whose replacement string contains a C escape gets a real newline
  instead, the pattern stops matching, and the script cheerfully prints
  "done" having changed nothing -- or worse, having applied half its edits.
  Build the backslash from `chr(92)`, or use the file-editing tool. This cost
  two broken source files this session.

  **Apostrophes go the same way**, which is why `tools/trackroute_check.py`
  was written out with the file-editing tool rather than a heredoc. A
  heredoc with quotes nested inside quotes can also fail outright
  ("unexpected EOF while looking for matching"). If a
  script's content has either character in it, do not pipe it through a
  shell.
* **`C3D_FVec` is declared `w, z, y, x`.** `r[i].c[j]` is element
  `(i, 3 - j)`, so a loop that fills `c[0..3]` as though they were columns
  0..3 writes every row backwards. It cost a build this session: the camera's
  view matrix came out transposed *and* mirrored, the eye never left the
  world origin, and the car drew as a black fan of triangles seen from
  inside the bodyshell. Nothing in the cross-check could see it. Use the
  named `.x/.y/.z/.w` fields, or subtract.
* **Azahar shows an "Update Available" dialog on launch** and it swallows
  every `PostMessage` keypress aimed at the emulator window. All three
  `run_azahar_*.ps1` scripts now close any visible top-level window of the
  process that is not titled "Azahar" before they start pressing keys. A run
  that does not is indistinguishable from a dead key binding: the app boots,
  the log looks healthy, and nothing responds.
* **A libctru console and citro2d cannot share a screen.**
  `consoleInit(GFX_BOTTOM, NULL)` switches that screen to RGB565 while
  citro3d goes on presenting BGR8 into the same framebuffer, and the result
  is not a flicker -- it is two half-width copies of the frame under a
  coloured dither, which looks like a render bug in your own code. There is
  no console in the port any more except on the top screen on the way out.
* **`tools/hostbuild.py` is a library, not a CLI.** Running it as a script
  exits 0 and produces nothing. Call `hostbuild.build(tmp, sources, name=...)`.
* **A survivor in a mutation run is not automatically a coverage hole.** Two
  of `bsnd_check.py`'s survived because they were equivalent mutants -- a
  quadrant boundary where both arms compute the same number, and a float that
  rounds identically in double. Work out which before adding scenarios.

  There is a third answer besides "hole" and "equivalent": **the mutation
  itself was badly written.** `(uint16_t)(int16_t)x` on a `uint16_t` field
  is a no-op by C's own rules and could never be caught; a mutation that
  fails to compile because it used `memset` without `<string.h>` was
  rejected by the compiler rather than by the transcript. Both were
  rewritten into the transcription errors they were standing in for.

  Two more shapes of the same mistake turned up in `Wheel`. A mutation
  whose body writes only to **its own parameters** (`lo = hi = value;` in
  an empty function) is three dead stores and cannot be caught by
  anything. And a mutation that writes **the value the target already
  held** -- `gMaxStaticSlip = value` where the call passed 0.5 and
  `gMaxStaticSlip` is 0.5 -- leaves no trace either; the call site had to
  pass 0.375 before the mutation meant anything.
* **A comment claiming a case is covered is not coverage, and it is worse
  than no comment.** `wheel_check.py` and `wheel_test.c` both said vx 0.4
  with a spin of 1.25 put the slip at exactly zero and so reached
  `GuessGroundForce`'s zero-magnitude early-out. `1.25 * 0.32f` is
  0.399999976, so the slip was -2.98e-08 and the guard was never reached
  at all. The mutation that deletes it survived a full pass, and the
  comment was read twice as the reason it could not be a hole. Where a
  case depends on an exact float, compute it rather than asserting it --
  `37.5 * 0.32f` is 12 with nothing left over, and that is the pair that
  works.
* **A mutation can survive because the fixture agrees with itself.**
  Three of `DriveTrain`'s eighteen survivors were that shape: a swap of
  `gShiftUpDetune` for `gShiftDownDetune` where the image ships both at
  0.95, a dropped store of a pedal the constructor had already left at
  the value the store writes, and a clamp to `FIRST_GEAR` of a
  `DesiredGear` the constructor had already set to `FIRST_GEAR`. Nothing
  is wrong with the mutation or with the code -- the input cannot tell
  them apart. Drive the fixture from a value the object would have to go
  out of its way to produce (detunes of 0.8 and 0.6, a pedal at 0.25, a
  gear of fifth) and all three die.
* **A `<` against `<=` needs the two sides equal bit for bit, and
  picking a likely number is not good enough.** `DriveTrain`'s inclusive
  mutants are killed by writing the shift point back as the very RPM the
  object computes, from the same product on both sides, so the compare
  is against itself. Where the fixture cannot be fed back like that the
  value has to be searched for: `94.2477036f` is the only float whose
  product with the rads-to-RPM constant is exactly 900.0f, and both
  neighbours land an ulp away.
* **A mutation nothing reaches is not covered by the scenario next to
  it.** Two of `DriveTrain`'s survivors were in the crossover search,
  which only does work when the torque curve falls hard past its peak --
  every fixture engine crossed over on the first probe or not at all, so
  the search's own branches never ran. Two extra engines, a steep curve
  and an all-zero one for the single case where two sides can be equal,
  killed both. Check that the *shape* of the fixture data exercises the
  loop before concluding the loop is equivalent.
* **Reaching the branch is not enough -- the difference has to land
  somewhere the dump prints.** Every survivor up to `DriveTarget` meant
  the fixture never got to the code. Two of `DriveTarget`'s got to it
  exactly, took different paths, and printed the same numbers.
  `bl-window-inclusive` gives `BlendWithCurrentAcceleration` one extra
  pass, but that pass blends at a weight which clamps to 1 and so moves
  x and y not at all, and z, the pad and `CalculatedSpeed` were zero on
  both sides -- until the fixture's points are given a z of 3, which
  `SetPoint3` zeroes whatever the blend is. `rs-inner-test-strict` needs
  `travelled == len[k]` exactly *and* `fadd(P[k], fsub(P[k+1], P[k])) !=
  P[k+1]` at the same k, because the two arms otherwise emit the same
  point; the separation goes in the pad, where `16777218 - 1` and
  `1 + 16777216` are both round-half-to-even ties landing on 16777216.
  So a survivor has two causes, not one, and the second is harder to
  see: the fixture's comment says it is on the boundary and the comment
  is right.
* **Check which float of a fixture helper you are writing.**
  `dt_point(t, i, x, y, z, speed, route, rpn, dl)`'s fourth float is the
  `CalculatedSpeed`, and the helper writes 0.0 into every pad by design.
  A kill built entirely around a pad value went into the speed column
  instead and the mutation survived a fixture aimed straight at it. The
  dump said so -- the number was sitting in `s`, with `0` in the pad --
  which is the argument for a dump that prints **every** field rather
  than the interesting ones.
* **An explicit alignment pad cannot be checked by deleting it.** A
  `uint8_t _pad[2]` in front of a pointer is reinstated by the ABI the
  moment it is removed: every following offset, and `sizeof`, come out
  unchanged and the layout assert passes. What pins the field after it is
  the `offsetof` in the assert. Do not read "the pad mutation survived" as
  a coverage hole.
* **A guard can be protecting the read rather than the number.**
  `Table::GetValue` returns `pTable[i]` outright when `i == last`. Delete
  that and the interpolation computes
  `pTable[last] + (pTable[last + 1] - pTable[last]) * 0.0`, because the
  weight is exactly zero there -- the same number, off the back of a load
  one element past the end of the array. A transcript cannot see it and a
  sanitiser build would.
* **An array's extent is part of the layout claim, and offsets do not pin
  it.** Shrink an array, pad behind it, and every following offset *and*
  the total size are unchanged -- the static assert passes. Nine
  CarTypeInfo mutations and one Steering mutation exploited exactly that.
  Print `sizeof` of each array, the element stride, and a width and
  signedness probe per field.
* **A layout is not checked until the ARM build compiles it.** The host
  harness cross-checks *arithmetic*; it is not the target and its structs
  are not the target's. `wheel.h`'s assert was wrapped in
  `#if __SIZEOF_POINTER__ == 4`, so neither toolchain ever compiled it, and
  when `tools/build_cia.ps1` finally did it failed. This port's `bVector4`
  is four-byte aligned where the PS2's was a sixteen-byte quadword, so a
  four-byte gap the PS2 record has before `Wheel::WorldGroundForce` did not
  appear and the handheld's record came out 396 bytes instead of 400. On the
  64-bit host the pointer widening cancelled the gap exactly, so the model
  and the harness agreed on the wrong record. Never guard a layout assert
  with a host test that makes it vanish on the host, and run the ARM build
  before calling a slice with a record in it done.
* **The vtable pointer is at the END of the object in this image.** Old
  g++ ABI. `CarState` has none, `CarDriver`'s is at 556, `Steering`'s at
  8, and every class still to come in task 25 is the same. Looking for it
  at offset 0 will shift every field by four.

* **The emulator harnesses are slow and flaky for a reason that is ours.**
  Once the boot flow's idle timer expires, `bgf_consider_start_demo_mode()`
  traces every frame, because the port's `startDemoMode` hook is a stub that
  never changes state. Two SD writes a frame slows the emulated app enough
  that most `PostMessage` key presses fall inside a single frame and are
  never scanned -- which looks exactly like a dead key binding.
  `run_azahar_scroll.ps1` presses SELECT up to 40 times to get past it. The
  fix belongs in `gameflow.c`, whose transcript `bootflow_check.py` diffs, so
  the Python reference has to move with it.

  It also makes `run_azahar_test.ps1` flaky: two PARTIALs in a row, with
  *different* failure modes, then three PASSes in a row once the machine was
  quiet -- including one at `0a58704` to rule out a regression. Re-run a
  PARTIAL once before believing it; the same failure mode twice is real.
* **A scroll offset is in the *padded* texture's space.** The original
  divides its UVs by the power-of-two allocation and only then adds the
  offset, so a citro3d caller adds it after converting pixels to UVs -- and
  T's sign flips, because `subtex_from_pixels` has already flipped the axis.
* **A passing cross-check does not mean the decoder is right.** Session 15
  found two decoder bugs `geometry_check.py` had been passing for four
  sessions, one of them in a field the digest explicitly covers. Both
  implementations were wrong the same way, because the C was written from a
  document that was written from the Python. Independence has to reach back
  to the disc or the ELF -- and look at the output on the emulator too.
* **ST is mirrored two vertices to a quad**, `(S_even, T_even, T_odd,
  S_odd)`, not transposed like XYZ. The cheap check is the S==T rate: 44.43%
  if you have it wrong, 1.68% if you have it right.
* **Skip `0x11` chunk filler a whole entry at a time on `0x00034006` and
  `0x0003401d`.** A byte scan eats the first byte of a table whose first hash
  ends in `0x11` (`TS50_C`: `0x4342fd11`) and shifts every hash in that solid
  by 8 bits, silently. The byte scan is still correct for the header, the
  entry table and the packet blob, checked against their sizes on all 1,461
  solids.
* **The game's T counts down from the image's top row.** A citro3d renderer
  over `texpack_upload` needs `v = 1 - T * scale`; `uirender.c`'s
  `subtex_from_pixels` is the hardware-verified precedent.
* **58 of the 132 texture hashes car geometry refers to are in no pack on the
  disc** -- 9.0% of strips. That is the data, not a bug to chase. Draw those
  strips untextured, the same path the `TextureNumber >= NumTextures`
  sentinel takes.
* **`eSolid.NumTextureTableEntries` (0xAC) is zero on all solids.** Count the
  `0x00034006` chunk instead; `geometry.c` does. `NumLightMaterials` at 0xAE
  is fine.
* **`eSolid.NumPolys` is stale** for 19 of the 1,465 solids. The per-strip
  counts are the truth.
* **`eStripEntry.TextureNumber` can be one past the end** -- 25 strips do
  that, and it means untextured. Range-check it.
* **Normals are 125..127, not 126..127**, and 53 across the car set are
  exactly zero. A zero normal is not the same as "this strip has no normal
  field" (about 17% of strips); check `hasNormals`.
* **`TRACKS\TRACKA12.BUN` has no solid list.** All 1,135 track solids are in
  B12.
* **The GS had no hardware backface culling** -- the VU did it in software,
  and nothing in the data forces a consistent winding. `georender_draw` uses
  `GPU_CULL_NONE` deliberately. Do not "fix" that without evidence from the
  normals.
* **`C2D_CreateScreenTarget` gives no depth buffer**, and `C3D_DepthTest`
  against no depth buffer silently does nothing. `main.c` builds the top
  target with `C3D_RenderTargetCreate(240, 400, GPU_RB_RGBA8,
  GPU_RB_DEPTH24_STENCIL8)` instead.
* **Azahar's X button is `Z` (0x5A) and its Y is `X` (0x58).**
  `%APPDATA%\Azahar\config\qt-config.ini` is the authority; guessing from the
  letter costs a wasted run that looks like a code bug.
* **A screenshot harness must not sleep.** A *faster* boot moves the
  keypresses earlier, not later, and the shot lands on the wrong screen.
  `main.c` logs its mode on every SELECT and `tools/run_azahar_geo.ps1`
  presses-and-confirms against the log.
* **`.gitattributes` / `core.autocrlf=true`**: there is no `.gitattributes`,
  and **every blob in the repo is LF** -- git normalises on commit, so line
  endings never show up in a diff and never need fixing for git's sake. What
  differs is the *working tree*, and the previous note here had it backwards.
  Measured: `TASKS.md`, `HANDOFF.md`, `CONTINUE.md`, every `.c`/`.h` under
  `3DS Files/source/` and `tools/geometry_convert.py` are **CRLF**;
  `tools/*.py` (all the others), `tools/src/*.c`, `README.md` and everything
  under `docs/` are **LF**. Match the neighbour when adding a file, and read
  and write with an explicit newline rather than letting a tool normalise
  one -- not because git minds, but because a whole-file rewrite buries the
  change you actually made when someone reads the working tree.
* **A multi-line mutation pattern written with bare newlines misses a
  CRLF source silently, and "not found" is not "survived".** `core.autocrlf`
  is `true` with no `.gitattributes`, so a checked-out ported source is CRLF
  while one a patch script wrote in place is LF -- the tree is a real mix,
  51 files under `3DS Files/source/` are LF today. A pattern that misses
  prints `PATTERN NOT FOUND` and is then dropped from the denominator, so
  the tally line still reads clean. It is not even stable: `cardriver` was
  honestly measured at 48/48 when its two files happened to be LF, and
  reported 32/32 later with the checker unchanged. **Every runner now
  detects the file's own newline and translates the pattern**; where a
  runner instead read with universal newlines (`camera`, `trackroute`) it
  was rewriting each file it touched from CRLF to LF and leaving it that
  way, so those read with `newline=""` now too. Check the `NOT FOUND` count,
  not just the last line.
* **A checker mutates the file it owns.** When `drivetarget_assign` moved
  out of `cardriver.c`, its three mutations went with it rather than being
  retargeted across the file boundary -- `drivetarget_check` already had
  them. `cardriver_check` is 45 mutations now, not 48, and 45 is the honest
  number.
* **A forward-ported helper in a neighbour's file is a link edge that
  breaks when its real file arrives.** `drivetarget_assign` sat at the top
  of `cardriver.c` for two slices because `SetDriveTarget` tail-calls it
  and DriveTarget had no `.c` yet. Moving it home broke
  `cardriver_check.py`'s link, and the checker that broke was not the one
  being worked on. **Run the whole checker list before calling a slice
  done, not just the new one.** The second failure was `WorldTimer`, which
  `engine.c` owns: harnesses define their own tick rather than linking
  Engine, Table, CarTypeInfo and Wheel behind it.
* **A mutation runner's restore is the one write that must not fail
  quietly.** These sources sit under OneDrive, and a write to a file the
  sync client has open comes back `OSError: [Errno 22] Invalid argument`.
  It is transient, but when the failing write is the **restore** in the
  `finally`, the pass dies with the tree still holding the mutation, and
  the traceback says only that a write failed. The next clean run then
  disagrees with the model for a reason nothing in the diff explains.
  All twelve mutation runners now retry the write five times and, if the
  original truly cannot go back, `sys.exit` naming the file and the
  mutation rather than letting the numbers that follow describe a source
  nobody meant to write. That is the second repo-wide hole in the
  runners found by a mutation happening to trigger it; the first was the
  missing `timeout=`. **When a checker disagrees for no visible reason,
  check `git diff` on the ported source before debugging the model.**
* **Checkers must not pipe harness stdout.** `subprocess.run` with
  `capture_output=True` deadlocks against a runaway child, and `timeout=`
  cannot rescue it because killing a cygwin-built exe from Windows does not
  reliably close its handles. `geometry_check.py` writes to a file and caps
  the line count; the older checkers still use a pipe and have the same
  latent problem.

## PICA200 notes

* At most **one uniform per instruction**, and only in the **first** source
  slot. `dp3 r3, r2, lightVec` is rejected; `dp3 r3, lightVec, r2` is fine.
* `mad` cannot take a uniform in either slot it leaves over. Spell
  ambient-plus-diffuse as `mul` then `add`.
* A `GPU_BYTE`/`GPU_UNSIGNED_BYTE` attribute is **not** normalised on its way
  in -- it arrives as the plain integer, so scaling is the shader's job.
  Leave an RGBA8 colour unscaled and the whole model saturates to white.
* It is `Mtx_Identity`, not `C3D_Mtx_Identity`.
* `.v.pica` files are already handled by the Makefile -- they compile
  straight to `.shbin.o` plus a `_shbin.h`, no extra target needed.

## Carried over, still open

* **The half-texel UV inset.** `RenderSingleFlailerBitmap` insets every
  corner by half a texel of the padded size before adding the scroll offset;
  the port does not. It touches all 397 textures in `FRONTB.BUN` rather than
  the two that scroll, so it wants its own verification pass.
* **`bui.c`'s eight setters are not cross-checked.** `bui_check.py` covers
  the parse path only.
* **No alpha blending on geometry.** Glass draws opaque. It is not vertex
  alpha -- all 212,408 car vertex colours have the alpha bit set -- so it is
  texture alpha plus a GS blend mode, and the blend state has not been
  recovered from the ELF. Strip `Flags` high bytes seen: `0x4100` on body,
  `0xc100` on the unresolved textures, `0x5000`, `0x0c00`, `0x0000`.
* **Car part transforms** are not decoded, so wheels, mirrors and wipers all
  sit at the origin. `geoview` steps solids one at a time rather than imply
  otherwise. Needed before a car can be driven.
* Light materials (`0x0003401d`) decoded and carried on every strip, read by
  nothing.
* 58 unresolved texture hashes; only `0xece04847` = `WIPER01` named so far.
