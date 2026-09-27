# CONTINUE

Where the next session picks up. Updated in Session 30's
continuation (2026-09-27), after task 27's twenty-seventh slice, the
sun's draw. `HANDOFF.md` is the running narrative; this file is the short
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

Fifty-seven cross-checkers pass, plus the table generators:

```bash
python tools/bvector_check.py && python tools/bmath_check.py && python tools/banim_check.py && python tools/bscreens_check.py && python tools/bootflow_check.py && python tools/bslotpool_check.py && python tools/geometry_check.py && python tools/texsrc_check.py && python tools/bui_check.py extracted/FRONTEND/FRONTB.BUN && python tools/sndbank_check.py out/SOUND && python tools/bsnd_check.py out/SOUND && python tools/emath_check.py && python tools/camera_check.py && python tools/trackroute_check.py && python tools/carstate_check.py && python tools/engine_check.py && python tools/cartypeinfo_check.py && python tools/cardriver_check.py && python tools/steering_check.py && python tools/rigidbody_check.py && python tools/suspension_check.py && python tools/wheel_check.py && python tools/drivetrain_check.py && python tools/drivetarget_check.py && python tools/drivetarget_image_check.py && python tools/graph_check.py && python tools/car_check.py && python tools/physicssystem_check.py && python tools/aerodynamics_check.py && python tools/physcomp_check.py && python tools/sinit_check.py && python tools/physicscar_check.py && python tools/mellowmover_check.py && python tools/carmode_check.py && python tools/joystick_check.py && python tools/joyhid_check.py && python tools/realtime_check.py && python tools/realdriver_check.py && python tools/quickspline_check.py && python tools/trackpath_check.py && python tools/average_check.py && python tools/airoute_check.py && python tools/realcontroller_check.py && python tools/track_check.py && python tools/vclip_check.py && python tools/polyhedra_check.py && python tools/collisionbody_check.py && python tools/collision_check.py && python tools/world_check.py && python tools/scenery_check.py && python tools/scenerycull_check.py && python tools/eview_check.py && python tools/loadertable_check.py && python tools/texturepack_check.py && python tools/trackflow_check.py && python tools/sky_check.py && python tools/sun_check.py && python tools/gen_bmath_tables.py --check && python tools/gen_bsnd_tables.py --check && python tools/gen_scanner_tables.py --check && python tools/gen_terrain_table.py --check
```

```
bvector_check      27 scenarios,  5721 lines, 0 differ   (23/23 mutations caught)
bmath_check        19 scenarios,  6424 lines, 0 differ   (9/9 mutations caught)
banim_check        23 scenarios,  2219 lines, 0 differ
bscreens_check     17 scenarios,  1246 lines, 0 differ
bootflow_check     12 scenarios,  3659 lines, 0 differ
bslotpool_check    18 scenarios,  1025 lines, 0 differ   (47/47 mutations caught)
geometry_check     30 files,     42047 lines, 0 differ   (53/53 mutations caught)
texsrc_check       6 packs, 2 levels, 2958 textures, 0 differ
bui_check          FRONTB.BUN    1395 lines, 0 differ
sndbank_check      30 banks,       908 lines, 0 differ   (20000 mutations, 0 disagree)
bsnd_check         12 scenarios,  5157 lines, 0 differ   (25/25 mutations caught)
emath_check         9 scenarios,  2416 lines, 0 differ   (39/39 mutations caught)
camera_check        7 scenarios,  1201 lines, 0 differ   (46 caught, 7 equivalent)
trackroute_check   10 scenarios,   671 lines, 0 differ   (52 caught, 1 equivalent)
carstate_check     10 scenarios,   653 lines, 0 differ   (56 caught, 7 equivalent)
engine_check        8 scenarios,   414 lines, 0 differ   (56 caught, 2 equivalent)
cartypeinfo_check   4 scenarios,   177 lines, 0 differ   (40/40 mutations caught)
cardriver_check     5 scenarios,   118 lines, 0 differ   (45 caught, 1 equivalent)
steering_check      5 scenarios,   873 lines, 0 differ   (43 caught, 1 equivalent)
rigidbody_check    10 scenarios,   935 lines, 0 differ   (76 caught, 2 equivalent)
suspension_check   10 scenarios,  1108 lines, 0 differ   (66 caught, 2 equivalent)
wheel_check        19 scenarios, 10695 lines, 0 differ   (145 caught, 10 equivalent)
drivetrain_check   18 scenarios,   498 lines, 0 differ   (173 caught, 3 equivalent)
drivetarget_check  22 scenarios,   897 lines, 0 differ   (243 caught, 19 equivalent)
drivetarget_image_check 22 scenarios, 897 lines, 160 masked, 0 differ (243 caught, 19 equivalent)
graph_check        16 scenarios,   151 lines, 0 differ   (21 caught, 4 equivalent)
car_check          58 scenarios,  4238 lines, 0 differ   (238 caught, 16 equivalent)
physicssystem_check 12 scenarios,  739 lines, 0 differ   (61 caught, 1 equivalent)
aerodynamics_check  7 scenarios,   107 lines, 0 differ   (74/74 mutations caught)
physcomp_check      8 scenarios,   239 lines, 0 differ   (46 caught, 1 equivalent)
sinit_check        15 calls,        0 problems           (6/6 mutations caught)
physicscar_check  106 scenarios, 102908 lines, 0 differ (257 caught, 6 equivalent)
mellowmover_check  39 scenarios, 56080 lines, 0 differ  (341 caught, 5 equivalent)
carmode_check      74 transitions, 19 resets, 36396 lines, 0 differ (491 caught, 14 equivalent)
joystick_check     64240 ops,    75891 lines, 0 differ  (250 caught, 3 equivalent)
joyhid_check       every key and stick reaches its event
realtime_check     20 scenarios, 1044 ops, 3470 lines, 0 differ (91 caught, 2 equivalent)
realdriver_check  152455 ops,    41163 lines, 0 differ  (118 caught, 4 equivalent)
quickspline_check   6640 ops,     6898 lines, 0 differ  (133/133 mutations caught)
trackpath_check     4771 ops,     4707 lines, 0 differ  (185 caught, 3 equivalent)
average_check        482 ops,      843 lines, 0 differ  (64/64 mutations caught)
airoute_check      14738 ops,     7224 lines, 0 differ  (86 caught, 5 equivalent)
realcontroller_check 14096 ops,  25318 lines, 0 differ  (129 caught, 11 equivalent)
track_check        16212 ops,    11821 lines, 0 differ  (273 caught, 5 equivalent)
vclip_check        11890 ops,    22389 lines, 0 differ  (280 caught, 1 equivalent)
polyhedra_check    15907 ops,    64560 lines, 0 differ  (172 caught, 12 equivalent)
collisionbody_check 1572 ops,    35426 lines, 0 differ  (622 caught, 24 equivalent)
collision_check     3587 ops,     6859 lines, 0 differ  (121 caught, 10 equivalent)
world_check         2742 ops,    15110 lines, 0 differ  (328/328 mutations caught)
scenery_check       3450 ops,    16724 lines, 0 differ  (77 caught, 2 equivalent)
scenerycull_check   7273 ops,    46687 lines, 0 differ  (147 caught, 1 equivalent)
eview_check         2103 ops,    15454 lines, 0 differ  (152 caught, 1 equivalent)
loadertable_check  27897 ops,    41988 lines, 0 differ  (100 caught, 2 equivalent)
texturepack_check   5452 ops,    11201 lines, 0 differ  (95 caught, 2 equivalent)
trackflow_check       16 scenarios,  702 lines, 0 differ  (73 caught, 1 equivalent)
sky_check             45 scenarios, 1159 lines, 0 differ  (76 caught, 2 equivalent)
sun_check             91 scenarios, 2680 lines, 0 differ  (114 caught, 1 equivalent)
gen_bmath_tables --check           bmathtab.c is up to date
gen_bsnd_tables  --check           bsndtab.c is up to date
gen_scanner_tables --check         joyeventid.h, scannertab.c are up to date
gen_terrain_table --check          terraintypetab.c is up to date
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

1. **Task 27's first slice is closed: `Track.obj` and `TerrainType.obj`**,
   the track's collision surface. It is written up in
   `docs/formats/topology.md`.
   - `track.c`, `topology.h` and `track.h` carry the TopologyTree, the
     pooled TrackPolygons, and TopologyCoordinate: the SetInterestBBox,
     GetElevation and Constrain a car stands on. They also carry the
     position markers, the track info table and the road noise.
   - `terraintype.c` and the generated `terraintypetab.c` carry the 33
     terrains.
   - `track_check` runs the image in mipsemu as the oracle, over a
     synthetic world and over TRACKB12 itself: 14,753 ops, 11,231 lines,
     0 differ. Of 209 mutations, 206 are caught and 3 are equivalent,
     with 0 unexplained.
   - **The second slice is Car's first callers of it**, in `cartrack.c`:
     `FindFlatOnTrackPosition` (`0x00130c58`) and `PutFlatOnTrack`
     (`0x00130e90`), with the `SetInterestBBox(bVector3)` wrapper
     (`0x00134f28`) in `track.c`. `track_check` checks them, and they are
     written up in `car.md`. The slope's constant is 65536 / 6.28, not
     65536 / 2 pi, and that is kept. They are apart from `car.c` because
     `car.c` links into six checkers that have no topology.
   - **The third slice is Car's reset group**, in `carreset.c`:
     `ResetCore` (`0x001312c0`), `ResetToPosition`, `ResetToRoutePoint`
     and `DebugSetPosition`, with `ReplayManager`'s
     `RegisterInterestingEvent` and `InvalidateInterestingEvents` in
     `replay.c`. `carmode_check` runs them after the transitions, over a
     real looping track path loaded through `LoaderTrackPath`: 19 resets,
     32,797 lines, 0 differ. Its whole pass is 188 mutations, 185 caught
     and 3 equivalent, with 0 unexplained. Two words reach the state from
     the stack. The checker poisons the stack two ways and masks only
     those words' fourth lanes. The port tests `pReplayManager` for NULL
     where the image does not, because the replay is not ported yet.
     Written up in `car.md`.
   - **The fourth slice is `AverageAir` and `BeginMovement`**, in
     `cartrack.c`, checked by `track_check`: 16,149 ops, 11,790 lines,
     0 differ. Of the slice's 62 mutations, 60 are caught and 2 are
     equivalent. The first 209, rerun after its scenario went in, are
     still 206 caught and 3 equivalent. Every wheel goes through `WheelMatrix[0]`, as shipped.
   - **The fifth slice is the step**, in `carmove.c`: `Car::Move`
     (`0x00130200`), `ChangeGear`, `CalculateNewCatchupMultipliers` and
     `UpdatePosition`. `carmode_check` runs seventy steps after the
     resets: 35,405 lines, 0 differ. Of the slice's 79 mutations, 77 are
     caught and 2 are equivalent. Car is 55 of 80 methods. New files:
     - `timer.{c,h}`: Timer, moved out of `collisionbody.h`, and
       `Timer::SetTime`.
     - `player.c`: `NumPlayers` and `pPlayersByNumber`.
     - `difficultyinfo.{c,h}`: the table and chunk 0x34b00's loader. No
       LoaderTable registers the loader yet.
     `RacingCar` is whole in `race.h`.
   - **The sixth slice is Car's calls out**, in `carrace.c`:
     `GetDistanceAndSpeed`, `FixBlownTires`, `TriggerTireBlowOut`,
     `PleaseResetMeLater`, `GetDrivingLineSpeed` and `DeliverMeFromEvil`,
     with `DynamicCollisionBody::GetDistanceAndSpeed` in
     `carcollisionbody.c`. `carmode_check` runs them after the steps: 35,602
     lines, 0 differ, and all 43 of the slice's mutations are caught. Car
     is 61 of 80 methods. Five calls are seams in `car.h`:
     - the cop manager, the AI's controller and the DeliveryMover, which
       abort if reached unset (task 26);
     - `TriggerEffect` and `BaseCarSound::TriggerTireBlowOut`, which are
       skipped (tasks 27 and 29).
   - **The seventh slice is Car's terrain effects**, in `careffects.c`:
     `TriggerCarTerrainEffects` (`0x00131db8`, 1872 bytes), the skid
     smoke, tire spew, drive-over, bottom-out, splash, damage smoke, nitro
     and flat-tire effects. `carmode_check` runs 54 cases after the sixth
     slice's: 35,875 lines, 0 differ. Of its 107 mutations, 104 are caught
     and 3 are equivalent. Car is 62 of 80 methods, 10448 of 22876 bytes.
     `BaseCarSound::TriggerSplash` is a new seam, skipped when NULL (task
     29).
   - **One finding, fixed:** Car's `NumTimesSkidding` is `unsigned
     char[4]` (stab `ar1;0;3;11`), a count a wheel, and not one
     `int32_t`. The offset did not move, and every checker still gives 0
     differ.
   - Apart from that, the checks found no disagreement between the image
     and the port.
   - **The eighth slice is the clock object**, in `realtime.c`: the video
     mode, the real clock and the world clock (`0x001992a0` ..
     `0x001995d8`), and all eighteen globals at `0x00323cc8` ..
     `0x00323d0c` with the image's initial values. `WorldTimer`,
     `WorldTimeElapsed`, `WorldLoopCounter` and `RealTimeElapsed` moved
     there from `engine.c`, `drivetrain.c`, `world.c` and `cammover.c`.
     Harnesses that do not link `realtime.c` define the ones they read.
     `main.c` drives both clocks the way MainLoop does with no race.
     `realtime_check` is new: 20 scenarios, 1,044 ops, 3,470 lines, 0
     differ. Of its 86 mutations, 84 are caught and 2 are equivalent.
     NTSC's ceiling is `0x3d4cccce`, one ulp above 0.05f. Written up in
     `docs/formats/realtime.md`. `WorldTimeDoSnapshot` waits on
     ReplaySnapshot.
   - **The ninth slice is VClip**, in `vclip.{c,h}`: all of `VClip.obj`
     (`0x001c5d90` .. `0x001ca008`, 54 functions) but `DoSnapshot`, which
     waits on ReplaySnapshot. That is the polyhedron and its Voronoi
     planes, the feature codes and memory images, the transform, the
     three clips, the five checks and the walk. The Caffeine plots go
     through the new `espresso.{c,h}` seams, which abort if reached
     unset. `gEspSetObjectPositionFn` is defined there now, so
     `carmode_check` links `espresso.c`. `vclip_check` is new: 47
     scenarios, 11,890 ops, 22,389 lines, 0 differ, over 2,001 VClips
     and 938 single checks. Of its 281 mutations, 280 are caught and 1 is
     equivalent, with 0 unexplained. Written up in
     `docs/formats/vclip.md`.
   - **The tenth slice is `polyhedra.cpp`**, in `polyhedra.{c,h}`: all of
     `0x00205058` .. `0x00206440`, the polyhedra the collision bodies hand
     to VClip. That is the Rect and Cube boxes, `WaferPolyhedron::Init`
     for a track polygon, the loader and unloader for chunk `0x80034020`'s
     collision volumes, `FindPipelinePolyhedron`, `MoveCenterOfGravity`,
     the list's globals, and the four debug tests nothing calls.
     `polyhedra_check` is new: 55 scenarios, 15,907 ops, 64,560 lines, 0
     differ, over all 15,708 of TRACKB12's polygons and all 43 volumes on
     the disc. Of its 184 mutations, 172 are caught and 12 are equivalent,
     with 0 unexplained. No disagreement between the image and the port
     was found. Written up in `docs/formats/polyhedra.md`.
   - **The eleventh slice is the bodies that do not move**, the first part
     of `CollisionBody.obj`, in `collisionbody.{c,h}`. That is the
     NumberAllocator, `Init/CloseCollisionBody`, the stats, the base
     class with its list sorted on BBoxMax.x, StaticCollisionBody and its
     twenty-two methods, TrackPolygonCollisionBody, the witness's
     constructor, destructor and bookkeeping, the three tables, and the
     static initialiser and destructor. Car's two CarCollisionBody
     methods moved to `carcollisionbody.c`, because they need car.h and
     the movers. `collisionbody_check` is new: 21 scenarios, 743 ops,
     2,945 lines, 39 dumps, 0 differ, with track-polygon bodies on seven
     TRACKB12 polygons. Of its 184 mutations, 175 are caught and 9 are
     equivalent, with 0 unexplained. No disagreement between the image and
     the port was found. Written up in `docs/formats/collision-body.md`.
   - **The twelfth slice is DynamicCollisionBody**, the second part of
     `CollisionBody.obj`, in `collisionbody.{c,h}`: the constructor and
     destructor, the bounding volumes, UpdatePosition, BeginMove, the two
     interpolations and Backup, the RigidBody and PhysicsSystem
     pass-throughs, GetLocalCollisionBodies, MaybeCreateWitnesses,
     CreateTrackPolygonCollisionBodies, TrackPolygonCheck, the inline
     methods and its table. `collisionbody_check` runs it on bodies whose
     four pure slots are logging stubs: 39 scenarios, 1,039 ops, 8,733
     lines, 60 dumps, 0 differ. Of its 329 mutations, 318 are caught
     and 11 are equivalent, with 0 unexplained. No disagreement between
     the image and the port was found. Written up in `collision-body.md`.
   - **The thirteenth slice is CarCollisionBody**, the third part of
     `CollisionBody.obj`, in `carcollisionbody.c`. That is its
     constructor and destructor, the getters, Move, ApplyImpulse,
     AddDamage, AnimateCollisionReaction, AreCollisionsEnabled, the mass
     and inertia, IsBlinking, the constants, the inline accessors and
     its table. RaceCoordinator's pointer, state and IsReplayDemoMode
     are in `race.c`. The damage, the pursuit, the driver's animation,
     the rumble and the force feedback are five seams, and `main.c` sets
     none of them. `collisionbody_check` runs it on stand-in Cars: 55
     scenarios, 1,211 ops, 30,218 lines, 73 dumps, 0 differ. Of its 483
     mutations, 462 are caught and 21 are equivalent, with 0
     unexplained. No disagreement between the image and the port was
     found. The port's AI demo test overflowed an int32 at INT_MIN, and
     it subtracts unsigned now, as the image does. Written up in
     `collision-body.md`.
   - **The fourteenth and fifteenth slices are the contacts**, the rest
     of `CollisionBody.obj`, in `contact.c`: InitContact and CloseContact,
     RemoveContacts, the sort and `bList::AddSorted`, all of Contact
     (FindContactTime, Crowbar, Resolve, the contact point and normal,
     CollisionImpulse and the rest), and the witness's FindWaferNormal,
     GetCollision, BeginCollision and TestForContact. They were done
     together because TestForContact builds a Contact. `Collision`'s
     constructor and AddImpulse are the seams `gCollisionNewFn` and
     `gCollisionAddImpulseFn`, which abort if reached unset. The
     sixteenth slice fills them. `collisionbody_check` runs the contacts on E0..E3,
     bodies whose nineteen contact slots are logging stubs: 81 scenarios,
     1,572 ops, 35,426 lines, 89 dumps, 0 differ. Of its 646 mutations,
     622 are caught and 24 are equivalent, with 0 unexplained. No
     disagreement between the image and the port was found. Written up in
     `collision-body.md`.
   - **The sixteenth slice is `Collision.obj`**, in `collision.{c,h}`,
     with World's two GetDistanceToClosestPlayer overloads in `world.c`.
     That is the pool, the constructor and destructor, AddImpulse, Update,
     End, GetTerrainType and the four questions. DoSnapshot waits on
     ReplaySnapshot. The sound's CreateSample, ReleaseSample and
     PlayScrape and the particles' TriggerEffect are seams that a NULL
     skips; tasks 29 and 30 fill them. `main.c` points the witness's
     `gCollisionNewFn`, `gCollisionAddImpulseFn` and `gCollisionDestroyFn`
     at it. `collision_check` is new: the image's own InitCollision,
     bNewSlotPool, bOMalloc and bFree run against `bslotpool.c`, and two
     more collisions are built on 0xa5 memory: 15 scenarios, 3,587 ops,
     6,859 lines, 0 differ. Of its 131 mutations, 121 are caught and 10
     are equivalent, with 0 unexplained. No disagreement between the image
     and the port was found. The scrape's "faster body" test compares
     body 1's length with itself, so the particles always get body 1's
     velocity. Written up in `docs/formats/collision.md`.
   - **The seventeenth slice is World's timestep**, in `worldstep.c`, with
     bList::Sort in `blist.c`. That is the clock, the pause and the time
     scale, GetTimestep, the car table, the Randoms,
     GetDATToClosestPlayer, the checksums, DoTimestepMove,
     DoTimestepCollisions and DoTimestep. The step's twenty calls out are
     seams in `world.h`, skipped when NULL, apart from FinishMovement and
     PlaceNewCar, which abort. `smokeable.h` names Smokeable up to
     pSmokeableSpawner and has Break and DeleteFarAway as seams.
     `world_check` is new: the image's World.obj, bRandom, bList::Sort and
     the replay's clock helpers run against the port, with the Car
     methods, the collision system, the replay's data and the seams as
     logging stubs on both sides: 24 scenarios, 2,173 ops, 12,963 lines,
     0 differ. Of its 200 mutations, all 200 are caught. The first pass
     left seven, each a hole the script now covers (a NaN clock, the
     ticker either side of exactly 0.3 s, a replay byte with high bits,
     a loop count that is a multiple of 64 but not of 128, and cars at
     exactly 100 and 150 from a player). No disagreement between the
     image and the port was found. Written up in `docs/formats/world.md`.
   - **The eighteenth slice is World's constructor and destructor**, in
     `worldinit.c`, with the record's tail in `world.h`: the constructor,
     the destructor, DebugDisplay, the four recorders and
     UpdateAIDebugRendering. Only DoSnapshot and DoPointerSnapshot of
     World.obj are left, for ReplaySnapshot. OBB's methods are `obb.c`,
     with the front of WorldObject in `worldobject.h`. The bPNode pool is
     `bplist.c`, and GetVectorOnTrack is in `track.c`. The constructor's
     eleven Init calls and the destructor's eleven Close calls are seams,
     skipped when NULL. The teleporter's constructor and destructor and
     Car's destructor are seams that abort when they are needed and
     unset. `world_check` runs it all against the image: 32 scenarios,
     2,742 ops, 15,110 lines, 0 differ. Of its 328 mutations, all 328
     are caught. The first pass left one, `render mul order`, which the
     new box covers (see below).
     `bslotpool_check` has a bPList scenario (18 scenarios, 47/47
     mutations caught), and `bslotpool_mutate.py` can now mutate a second
     file. `track_check` puts 31 points on the ground with
     GetVectorOnTrack (273 caught, 5 equivalent). The port departs from
     the listing in one place: for a driver number that no car has,
     UpdateAIDebugRendering reads the word at 44 in low memory. The port
     passes NULL; the one renderer the game runs never reads its target.
     Written up in `docs/formats/world.md`.
   - **The nineteenth slice is `Car::FinishMovement`** (`0x00130480`, 2008
     bytes), in `carfinish.c`: the accelerations, the odometer, the track
     path's update, the lost-car and search tests, the headlights, the
     zone clear, the air, the jump cam and its zone, and the replay's
     CarInAir, CloseCars, CarSlidingSideways, CarCollision and
     SmokeableCollision. Car is 63 of 80 methods, 12456 of 22876 bytes.
     `main.c` sets `gCarFinishMovementFn`, so World's step no longer
     aborts there. The Player's ClearZone, RequestZone, IsJumpCamAvailable
     and CleanUpJumpCam are seams that abort when unset (task 26), and
     `player.h` names `nZoneCurrent`, `bWrongWay` and `EyeVerts`.
     `g_DisableAutoReplay` is in `car.c`, and
     TrackPathCoordinate::ResetPosition in `trackpath.c`. `carmode_check`
     runs 105 cases after the terrain effects, with a player, a five-car
     world table, a Collision and the topology's answers scripted one per
     question: 36,396 lines, 0 differ, no line of it masked. Of its 88
     mutations, 82 are caught and 6 are equivalent, with 0 unexplained.
     No disagreement between the image and the port was found. Written
     up in `car.md`.
   - **The twentieth slice is `Scenery.obj`'s data half**, in `scenery.c`:
     LoaderScenery and UnloaderScenery, the three finds, IsPointInPoly,
     FindVisibleZone, the zone's two index helpers, Init- and
     CloseVisibleZones, the debug tables, CreateFacadeMatrix,
     FlipObjectsOnBackwardsTrack and the statics, which are
     `__CTOR_LIST__[21]` in `sinit_run`. eModel::Init and its deleting
     destructor are the seams `gEModelInitFn` and `gEModelDestroyFn`,
     which abort when unset; `eModelSlotPool` is NULL until the renderer
     makes it. `scenery_check` loads all 122 of TRACKB12's sections and
     its 23 zones, forward and backwards, with made-up sections beside
     them: 17 scenarios, 3,450 ops, 16,724 lines, 0 differ. Of its 79
     mutations, 77 are caught and 2 are equivalent. One port bug was
     found by the pass and fixed: indexed through the array, GCC took
     FindIndexTo's 64 as a bound on the count. No disagreement between
     the image and the port was found. Written up in
     `docs/formats/scenery.md`.
   - **The twenty-first slice is the scenery cull**, in `scenerycull.c`,
     `eframe.c` and `eview.c`: ClassifyAABB (`0x0010b940`, VU0's
     `vclipw`, which `mipsemu` now models with the clip register),
     IsBoundingBoxVisible, IsVisible, the tree and brute-force culls,
     DrawAScenery, WhatSectionsShouldWeDraw, CullView, BatchCullViews,
     DoCulling, StuffScenery, SetupSceneryCullInfo, eDisplayFrame's loop
     over the views, Ecstasy.obj's frame malloc and the table of ten
     eViews: 17 functions, 4,608 bytes. eModel::Render is the seam
     `gEModelRenderFn`, which aborts when unset. `scenerycull_check` runs
     the image over made-up sections and over all of TRACKB12's, from
     every zone and twelve random points: 9 scenarios, 7,273 ops, 46,687
     lines, 0 differ. Of its 148 mutations, 147 are caught and 1 is
     equivalent. Six reassociations survived the first pass and each now
     has a case, found by search, where the other order rounds across a
     plane, the 2 or a far clip. No disagreement between the image and
     the port was found. Written up in `docs/formats/scenerycull.md`.
   - **The twenty-second slice is `eView.obj`**, in `eview.c` and
     `eviewmatrix.c`. It covers:
     - `CalculateViewMatricies` (`0x00106700`), `CreateViewMatricies`
       (`0x0010d268`), `CalculateH` and `SetupMatrixPacks`;
     - the two local-to-clip products and `BiasMatrixForZSorting`;
     - the three `GetPixelSize`s, `GetScreenPosition`, `GetScreenWidth`
       and `GetScreenHeight`, and `SetupWorldLightContext`;
     - the view names and lookups, the camera movers' attach and detach,
       `eUpdateViewMode` and `MaybeChangeViewMode`;
     - the static constructor's four cameras and ten views, which are
       `__CTOR_LIST__[2]` in `sinit_run`.

     `eWaitUntilRenderingDone` and `elSetupLightContext` are seams that do
     nothing when NULL. `eview_check` runs the image against the port: 12
     scenarios, 2,103 ops, 15,454 lines, 0 differ. Of its 153 mutations,
     152 are caught and 1 is equivalent. The check found one bug outside
     the slice, in `camera.c`. The eye is a subtraction from VU0's (0, 0,
     0, 1), and the port negated it instead, so the default eye was -0 in
     x and y. That is fixed, and `camera_check` has a mutation for it (46
     caught, 7 equivalent). Written up in `docs/formats/eview.md`.
   - **The twenty-third slice is the track on the screen**, roadmap step
     1, in `trackview.c`, `emodel.c` and `main.c`'s `MODE_TRACK` (SELECT
     past the geometry viewer). It:
     - reads TRACKB12.BUN whole and links its 1,135 eSolids onto
       `SolidList` in place;
     - hands the 122 sections and 23 zones to `scenery_loader`, with
       eModel::Init and its destructor in `emodel.c` (2,494 models, 7
       without a solid);
     - bakes the 915 named solids (125,498 triangles, 342 textures, none
       missing) and runs eDisplayFrame's order on view 1 every frame;
     - draws what the ported cull picks through `georender`, in the
       engine's order: opaque order-0 textures at once, everything else
       after StuffScenery, by the attach loops' RenderingOrder, first use
       and alpha-sort rules, with the GS's blend equations and TEST_1
       (depth GEQUAL, alpha GREATER 0x30).

     A free camera flies it, and the D-pad steps along 24 stops of route
     1. `tools/run_azahar_track.ps1` shoots stops 1 to 7 in Azahar, and
     all seven show the road, the trees, the signs and the shadows.
     Written up in `docs/formats/track-render.md`, which lists where the
     port departs: the sort is per batch, not per strip; there is no
     `pStackedActiveTexture`, no shadow matrix pack, no light materials;
     and the sky domes draw in the main view until step 3 (the
     twenty-sixth slice moved them to StuffSky).

   - **The twenty-fourth slice is the LoaderTable**, the first half of
     roadmap step 2, in `bchunkload.c`, `esolid.c` and `emodel.c`. It
     covers:
     - ResourceFile's load half (`0x0018f6c8` .. `0x0018f918`):
       LoaderNull, both walks, LoadChunks and UnloadChunks, PostLoadFixup
       and HotChunksPostLoadFixup;
     - the two tables of 31 slots. Slot 0 is LoaderNull, and the seven
       slots whose object is ported call it. Every other slot is its guard
       alone, handing what it takes to `gUnportedLoaderFn`;
     - LoaderSolidList and its unloader, FixStripEntryTable,
       FixTextureTable, FixLightMaterialTable and eFixUpTables, with the
       eVertexAnimator pool;
     - the rest of eModel.obj's list half: UnInit, ReconnectSolid,
       ReconnectTextureTable, ApplyReplacementTextureTable,
       ReconnectAllModels and the deleting destructor.

     `trackview.c` loads TRACKB12 through `load_chunks` and
     `post_load_fixup` now, and unloads it through `unload_chunks`. It no
     longer links the solids itself. Seen on Azahar: 1,135 solids linked
     by LoaderSolidList, 2,494 models, 342 textures, 0 missing, and the
     track draws as before. `loadertable_check` runs the image against
     the port: 27,856 ops, 41,730 lines, 0 differ, over every solid list
     on the disc and all 497 of TRACKB12's top-level chunks. Of its 102
     mutations, 100 are caught and 2 are equivalent. The first pass left
     five, and all five were holes in the script: the ported unloaders
     were never called on a bare chunk, and there was no case for a tree
     whose pad changes its count of nodes, for labelled frames apart from
     their animation, or for UnInit on a model with a solid. Written up in
     `docs/formats/loader-table.md`.

   - **The twenty-fifth slice closes step 2.** It has three parts.
     - **TexturePack.obj** is ported in `texturepack.c`. Its loader and
       unloader are slot 2. Its in-memory half has the constructor and
       destructor, AttachTextureTable, Assign and UnAssignTextureData, the
       three lookups, GetTextureInfo and GetNthTextureInfo, the flipbook
       pack, InitAnims, UpdateTextureAnimations and GetTextureAnim.
     - **The track flow** is ported in `trackflow.c`:
       EndGameFlowLoadingTrackSpecific (`0x001645e8`) and
       BeginGameFlowUnloadingTrackSpecific (`0x001646e0`). The End clears
       `eDisableFixUpTables` and runs the one eFixUpTables. Then it calls
       the collision pools, InitTree, InitPhysics, the visible zones, the
       paths and the routes. Every callee the port lacks is a seam.
     - **The viewer** loads in the game's order: the shared packs;
       `eDisableFixUpTables` set; TRACKB12, TEX12TRACK and TEX12LOCATION;
       then the End. It unloads through the Begin, whose
       FindResourceFile loop hands the three files back newest first.

     Seen on Azahar:
     - The track draws textured by the game's own GetTextureInfo, and 49
       names get the default, as the disc predicts.
     - All 46 flipbook frames upload, and none fails.
     - `InGameFlag` is 1 after the load and 0 after the free, and the
       free leaves no solids, models or packs.

     `texturepack_check`: 5,452 ops, 11,201 lines, 0 differ; 95 of 97
     mutations caught, 2 equivalent. `trackflow_check`: 16 scenarios, 694
     lines, 0 differ; 73 of 74 caught, 1 port-only. Written up in
     `docs/formats/texture-pack.md` and `docs/formats/track-flow.md`.

   - **The twenty-sixth slice starts step 3** with the sky dome and the
     sun's data.
     - **Sky.obj** is ported whole in `sky.c`: SkyInitModel, SkyLoader,
       SkyUnloader, StuffSky, and the static constructor and destructor.
       SkyLoader takes SKYDOME and SKYDOME_ENVMAP out of the scenery.
       Each placement becomes a matrix, and each kind's LOD models are
       UnInit'ed, so the cull no longer draws the dome.
     - **Sun.obj's data half** is ported in `sun.c`: LoaderSun and
       UnloaderSun, which is slot 14, plus SunTrackLoader and
       SunTrackUnloader, which give the five SUN textures order 7.
     - **The End and the Begin** call all four directly now, not through
       seams. Only rain_Load and rain_Unload are still seams.
     - **The viewer** draws the dome the way eDisplayFrame does: Z writes
       off, StuffSky, the deferred list, then Z writes back on, all
       before the scenery. `georender_set_zwrite` is eSetZWriteState.

     Seen on Azahar:
     - SKYDOME is drawn by StuffSky, and the envmap views get their own
       dome.
     - The sun chunk is version 2, at (-16384, 800, 6000).
     - All five sun textures are found, at order 7.
     - The track drew 437 of 438 objects, 1 of them the sky, and the
       mountains and clouds show behind the canyon.
     - The free leaves no solids, models or packs.

     `sky_check`: 45 scenarios, 1,159 lines, 0 differ; 76 of 78
     mutations caught, 2 equivalent. `trackflow_check` is now 702 lines,
     and `loadertable_check` treats slot 14 as ported; 0 differ in each.
     Written up in `docs/formats/sky-sun.md`.

     Three fixes followed the slice:
     - `sinit_run` now calls `sky_static_init` ([6], `0x0011cfb8`).
     - `loadertable_test.c` defines SunPosition, which sun.c writes and
       eviewmatrix.c owns.
     - `loadertable_check`'s dump now shows SunInfo and SunPosition. A new
       scenario takes TRACKB12's sun chunk through both tables at each
       misalignment, then at version 1. That catches `unloader-14-loads`,
       which the first commit left open. The checker is now 27,897 ops
       and 41,988 lines, 0 differ; of its 102 mutations, 100 are caught
       and 2 are equivalent.

   - **The twenty-seventh slice is the sun's draw.**
     - **StuffSun and StuffSunGlare** are ported in `sundraw.c`. That
       includes the glare's globals, PhaseTimes and the 15 SunZBuffers.
     - **ePoly** and its constructor are in `epoly.c`, and ePoly::Render
       is a seam.
     - **The 3DS side** is in `trackview.c` and `georender.c`.
       - `render_epoly` maps the quad's pixels onto the top screen. It
         draws with the poly's blend, the main target's alpha test and no
         depth test. No depth test is needed: the poly's z of 65535 passes
         GEQUAL against any 16-bit Z.
       - `transfer_zbuffer_rect` queues the rect.
       - main() calls `trackview_read_depth` after the next
         C3D_FrameBegin, before the clear. It reads the D24S8 buffer and
         turns each depth into the GS's Z, 16 + (0x0ff000 - 16) t, with
         t the same on both.
     - **A probe** logs 15 screen points' colour and depth words at each
       stop. Scored against seven stops' screenshots, the tiled mapping
       comes out at 531, and its flips at 3,643 to 5,931.

     Seen on Azahar:
     - At every stop the sun is just above the frame. Its rect is off the
       target, so its layers draw at alpha 0.
     - The new `track-sun` shot goes back to stop 1 and looks up. The
       whole rect is sky, and the layers draw at 128, 64, 89 and 40.
     - The halo has a hard edge, and the fourth layer never shows. The
       PS2's alpha test does both of these too, because the textures'
       alpha stops at 0x7f.

     `sun_check`: 91 scenarios, 2,680 lines, 0 differ; of its 115
     mutations, 114 are caught and 1 is equivalent. Written up in
     `docs/formats/sun-draw.md`.

     **Next is the rest of step 3.**
     - WeatherMan, slot 29 (`0x34250`): LoaderWeatherMan (`0x0019dff8`)
       and WeatherManQuery (`0x0019e290`), and the fog it drives
       (CreateFogPalette, `0x00119678`).
     - The RainSystem, behind rain_Load (`0x00128bf8`).
     - Nothing sets bStartGlare until the munitions are ported.
       Munition::ExplodeWarhead (`0x001b4798`) sets it for a
       MunitionsType of 1.

     "The road to a playable demo", below, has everything after it.

   Things to know before the next slice:
   - **A bundle with texture packs must sit at 128 in memory.**
     LoaderTexturePack rounds the blob's address up to 128, and the
     packer sized each blob's filler for the file's own address. A buffer
     from plain malloc shifts every texture. Read bundles with
     `memalign(128, ...)`, as `uirender.c` and `trackview.c` do.
   - **Nothing fixes the tables up between the Begin and the End of
     loading.** `eDisableFixUpTables` is 1 from
     BeginGameFlowLoadingTrackSpecific until the End clears it. A solid
     loaded in between has its texture table as the loader left it
     until then. The Begin of unloading sets the flag again, and it
     stays set after the viewer's free.
   - **`eMathInit` must run before anything draws.** It is the only
     thing that fills `eMathIdentityMatrix`, which StuffScenery hands to
     every object drawn in place: the road and the terrain. Left zero,
     they fold to a point. `main.c` calls it where InitializeEverything
     does, just before eInitEngine's share.
   - **Azahar refuses a .3dsx with a bad relocation and says only "Error
     1".** `tools/check_3dsx.py` runs after every build now and names the
     word. The first one was gcc folding `table + negative constant` in
     `bFixATan1` for INT32_MIN; `bmath.c` compares unsigned there now.
   - **The GPU command buffer is 4x citro3d's default**, and it has to
     be: stop 2 uses 139,068 of its 262,144 words. `GPUCMD_Add` drops
     what does not fit silently, so `trackview.c` stops 8,192 words short
     and counts the draws it skipped.
   - **A subtraction from zero is not a negation.** VU0 makes a negative
     with `vsub` from vf00, and 0 - (+0) is +0 where -(+0) is -0. The
     camera's eye was wrong this way from the camera's port until
     `eview_check` printed its bits. Where the listing subtracts from vf00, the port
     writes `0.0f - x`.
   - **`sinit.c`'s bracketed index is 1-based past the count word.** The
     list's first function is [1], and `sinit_check` reads every index, so
     an index that is off by one fails there.
   - **The track fits the Old 3DS's linear heap.** `heapcfg.c` gives it
     about 68 MB. The scenery's 932 solids are 122,937 triangles, which is
     10.3 MB as `georender`'s triangle lists. Their 330 textures are
     27.3 MB as RGBA8, and 11 more are in no pack.
   - **The track's surface is loaded on hardware, but not built.** The
     track viewer's `load_chunks` reaches `track_loader_geometry` and
     TopologyTree::Loader now, with the collision volumes and the track
     path. The `InitTree` call in `EndGameFlowLoadingTrackSpecific`
     (`0x0016461c`) is still not wired, and it is the one thing left
     before the surface is live. Car.obj's `SetInterestBBox(bVector3)`
     wrapper (`0x00134f28`) is ported.
   - **A slot is taken by its guard even when its object is not ported.**
     `bchunkload.c`'s unported slots claim the image's types and hand the
     chunk to `gUnportedLoaderFn`, which is NULL. So TRACKB12's lights,
     effects, event manager, cameras, sun, cops, soundscape, helicopter,
     smokeables and weather (14 chunks, 10 slots) load as nothing, with no
     `bBreak`. Porting one means calling its loader from the guard, as
     the seven ported slots do.
   - **LoaderSolidList fixes up the file in place.** It moves each strip's
     `Data` by the packet's address and writes the texture and
     light-material pointers into the bundle. The unloader does not move
     the strips back, so a second load of the same buffer moves them
     twice, unloaded in between or not. The game reads a bundle afresh
     for each load, and the port has to as well. The viewer never reads
     the strips' `Data`, and `geo_open` parses the bundle before
     `load_chunks` runs.
   - **`chunk_loader_table.py` misses five of LoaderTrackGeometry's seven
     types**: `0x34146`, and `0x34130`..`0x34133`, which go through the
     tail call into TopologyTree::Loader. `bchunk.md` explains the two
     causes. Trust `topology.md`'s list over the tool's.
   - **`NumUpsideDownTrackPolygons` holds (placed) minus (vertical)**, which
     is the total for an all-floor build. Nothing in Track.obj reads it back.
     Check any reader outside it.
   - **`WorldTimer` is set per step case** in `carmode_check` (`mv(now=)`,
     W by default). The blink tail's sentinels only show with a clock a
     quarter second past them.
   - **A mutation pattern replaces its first match.** If the pattern is
     also in a comment above the code, the mutant edits the comment and
     survives. Two of the step's did that. Spell a pattern so it only
     matches code.
   - **The rest of Car** is 17 methods, and every one reaches a class
     that is not ported: the constructor and destructor, `TriggerEvents`
     (the ferns, the event manager, `Player::TriggerVisibleDrivingLine`),
     the AnimatedDriver pair, the damage, render and force-feedback
     groups, and `DoSnapshot`. `car.md` lists them.
   - **Two clocks are still apart from the clock object.** `gameflow.c`
     keeps its own in the flow's record (`bgf_advance_time`), and
     `main.c`'s `uiTimer` drives the scrolling textures. Both tick at the
     same 1/60. Fold them in when the flow's MainLoop is.
   - **A walk hides its steps.** VClip settles on the same closest pair
     whichever way one step goes, so 21 mutants of the checks and clips
     survived every whole-walk scenario. `OP_CHECK` runs one check on its
     own, set up the way VClip sets it up, and the single-step scenarios
     kill all 21. Build each survivor's harness once and run candidate
     scripts through it without the emulator; that finds a killing
     family in seconds. The model then confirms it.
   - **`hostbuild` failed a link with every object cached** under msys2
     ("compile failed (msys2 bash)" with no diagnostic). It treated
     "nothing to compile" as failure. Fixed in `_build_cached`.
   - **mipsemu zero-extends a call's arguments.** Pass anything the image
     reads as signed through `s32` first. Find of a hash with the top bit
     set missed in the model until `polyhedra_check` did.
   - **A disc container only loads at its own 16-byte residue.** The
     pipeline laid each array's pad out for where the container lies, and
     the loader just rounds up. A copy moved anywhere else has to be
     repacked first; `polyhedra_check` has the code.
   - **Run a long `--mutate` with `python -u`** when its output goes to a
     file, or nothing shows until it ends. A background shell's timeout
     did not stop one either. Keep a copy of any untracked source a pass
     edits, in case the run dies mid-mutant.
   - **A guard the image does not have needs its own case.** The image
     calls PortRumbleImpact and StartForceImpact with no test, so the
     model always calls them, and the harness always set both seams.
     The port's NULL tests never ran until `G_SEAMS` left the seams
     NULL and quieted the model's two stubs.
   - **A length only shows its sum's order off a tie.** Every impulse
     in the first script summed exactly. (4.5, 0.1, 0.2) sums to
     different floats the two ways, and the difference survives the
     root. A quick search over float32 finds such a triple.
   - **Two of Init's allocations are short, and the image reads past
     both.** The NumberAllocator takes `n >> 3` bytes, so IDs 200 to 205
     are in a twenty-sixth byte, and the witness bit field is 5304 bytes
     for 42,436 bits. On the console both land in bMalloc's round-up.
     The port asks for the byte more (`COLLISIONBODY_SHORT_SLACK`).
   - **A witness never joins a body with a negative ID, or a body to
     itself.** The pair bit `ID1 * 206 + ID2` would land before the
     field, and the witness's last destructor would destroy a track body
     twice. The game converts a virgin smokeable (ID `~index`) before it
     builds a witness. A script that does either reads junk on the host.
   - **A mutant that breaks the body list hangs the harness.**
     `collisionbody_check`'s timeout is 30 s now, not 300. The first pass
     ran with 300, and the hung harnesses were killed by hand after 30 s.
   - **An equivalence has to hold for what is printed, not just for the
     state.** The pair bits are symmetric, but DoesWitnessExist answers
     the masked byte, so swapping the order was caught although it was
     listed as equivalent. Every checker's tally now counts the
     equivalents that survived, and fails on one whose mutant was caught
     or that names no mutation. Eighteen of them printed the list's size
     until this session; every mutation pass was rerun whole after the
     change, with no stale entry and 0 unexplained.
   - **A dot product's order only shows at a tie.** The script's values
     summed exactly, so both association mutants of TrackPolygonCheck
     survived. Put a compare one rounding away from its tie: 1.5 plus two
     of -2^-24 is 1.5 added one way and just under it the other.
   - **`MaxCollisionBodyWidthX` can be below a body's width.** When the
     widest body narrows, the recount leaves it out, and MaybeCreateWitnesses'
     walk then stops short of it.
   - **CollisionImpulse divides by the slide**, and a car dropped straight
     onto flat ground has none. The EE's −0 / 0 is FLT_MAX, which the zero
     slide then makes 0; IEEE's is NaN, which would reach both bodies. The
     port calls `ee_div` there, and `collisionbody_check` runs mipsemu with
     `eediv` and stops if any other division sees a zero.
   - **A stamp only shows if a dump comes before the next one.** Two of the
     contacts' survivors had their case in the script, but the test after
     it stamped the same body again before any dump. The same thing hid
     the car count's highest in slice C.
   - **A product and a quotient round apart.** Update's age is
     `(float)ticks * 0.00025f`, and `ticks / 4000.0f` differs from it at
     5 ticks (3aa3d70b against 3aa3d70a). Both of Update's mutants that
     changed the scale survived a script of round ages. A lifetime one
     ulp above each age's product, at 5, 1200 and 4000 ticks, kills them.
   - **A NaN or an exact boundary is what tells an order apart.** Five
     of the timestep's seven survivors swapped `min.s`/`max.s` operands or
     turned a `<` into `<=`, and only a NaN clock or a value exactly on
     the line (0.3 s of wait, 100 and 150 from a player) separates them.
   - **A multiply by the identity is not a no-op for the check.** OBB's
     Render takes `m × I`, and a mutant that swapped it for `I × m`
     survived every random box. Each column of `I × m` adds the identity's
     fourth row times zero, a +0, so only an axis that is -0 in one lane
     and negative in the rest tells the two apart.
   - **The closest-point search walks the paths, not the points.**
     `trackpath_find_closest_point` loops over `NumPaths`, so a manager
     with no points still hands back a point. To test "no point", zero
     `NumPaths`, as `carmode_check`'s `nopaths` case does.
   - **A BAM angle never lands on a round radian.** GetYaw is one of
     65536 differences times `BAM_TO_RAD`, and a scan of all of them finds
     none exactly on 3.14/32 or 3.14/8, so a yaw's `<` and `<=` are
     equivalent. Scan before hunting for the boundary case.
   - **Next are the track's rendering and streaming, and RaceCoordinator's
     InitForRace** (`0x001473c0`, 500 bytes), which is what will build a
     World outside a harness. InitForRace reaches much that is not ported:
     the `Player(JoystickPort, int)` constructor, the ReplayManager and
     Race constructors, InitCars (`0x00147ce8`, which needs Car's
     constructor), InitPlayers (`0x001476e8`), Race::Init, SetupGhostCars,
     SetAIDriverModesFromPlayers, and the speech and collision-sound
     resets. The World constructor it calls is ported.
   - **The 3DS build compiles every file so far.** `tools/build_cia.ps1`
     built the CIA, 316,352 bytes, with `worldinit.c`, `obb.c` and
     `bplist.c` in it and no warnings from the port's sources. Nothing on
     the boot path calls them yet, so the linker drops them and the size
     did not move.

2. **Task 26's second slice is closed: `TrackedController` and
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
   - **`drivetarget_image_check` then found a second one.** Above 1 m/s
     StraightLinePredict normalises the velocity inline on VU0, and the
     last multiply is `.xyzw`: the pad lane is divided by the length too.
     Port and model both copied it across unscaled. Fixed on both sides;
     `fn slp divide` and two new mutants cover it. The image checker runs
     every DriveTarget method in mipsemu with the model's scenarios, and
     both passes come out 262 mutations, 243 caught, 19 equivalent.
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
3. Then in order: 26 race/cop AI, 27 track render/stream/collision,
   28 New3DS perf, 29 save/options/sound mix, 30 split-screen scope,
   31 final CIA + Old3DS/New3DS pass.
4. **`QuickSpline.obj` is ported** (Session 29, continued), which pays
   task 24's debt. `TrackPathCoordinate::UpdatePosition` now measures
   through the spline, so `SetFirstAndLastPoints`, `Signpost::SetDistances`
   and `TestSignpostConsistency` run for real. `gTrackPathDistanceFn` is
   now only `trackroute_check`'s closed form, and it is `NULL` on
   hardware. `cammover.c` still leaves out the CM_TRACK_CAR and
   CM_TRACK_FLY movers, which needed the spline too.
5. Whenever a screen class gets ported, take its row in `kScreens[]` off
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

## The road to a playable demo

"Playable" means the demo's own loop: pick a car and a mode in the
frontend, race TRACKB12 against the AI with the cops on, see the result,
and go back to the menus. The count below is in slices of the size the
last ten were, which is one or two sessions each. It is an estimate, and
it will move as each class shows what it reaches.

| Step | What | Slices |
|---|---|---|
| 1 | ~~The track on the screen: the viewer mode, eModel over `georender`, a free camera~~ done, task 27's twenty-third slice | 1 |
| 2 | ~~The LoaderTable: every chunk type in TRACKB12, with the solids, the texture packs, the topology and the routes live~~ done, task 27's twenty-fourth and twenty-fifth slices | 2 |
| 3 | The sky, the sun and the weather's draw. The dome, the sun's data and the sun's draw are done (task 27's twenty-sixth and twenty-seventh slices); the weather and the rain are left | 2-3 |
| 4 | Car's constructor and destructor, and CarRenderInfo, so that a car draws on the track | 3-4 |
| 5 | Player and the chase cameras (CM_DRIVE and the rest of `cammover.c`'s set) | 2 |
| 6 | RaceCoordinator's InitForRace, InitCars, InitPlayers and Race::Init, and the game flow from the frontend into a race and back | 2-3 |
| 7 | **One car driving the track.** Steps 1-6 are this milestone: about 10-13 slices | |
| 8 | The rest of task 26: the racer and traffic AI, the six classes behind Car's constructor seams | 4-6 |
| 9 | The cops and the pursuit: CopManager, the cop drivers, roadblocks and spikes | 4-6 |
| 10 | The two-screen HUD, to the split decided below | 1-2 |
| 11 | The car and world sounds and the speech | 2-3 |
| 12 | **A whole race with the AI and the cops.** Steps 8-11 add about 11-17 slices | |
| 13 | Save data and the options screens (task 29) | 1-2 |
| 14 | Old 3DS performance: 16-bit or ETC1 textures, fewer draw calls, and the New 3DS's second core (task 28) | 2-3 |
| 15 | The split-screen decision (task 30), then the final CIA, banner and hardware pass (task 31) | 1-2 |

That is about 26-37 slices to a demo that is ready to publish. The replay
(`ReplaySnapshot` and every `DoSnapshot`) is not in the count. The demo
can ship without its auto-replay, and it is its own slice if it goes in.

## What not to trust

Ordered roughly by how much time it costs to rediscover.

* **A checker whose model was written from the disassembly can share a
  misreading with the port.** `drivetarget_check`'s model and
  `drivetarget.c` both had FillWithCurrentAcceleration's first test
  negated. The two agreed, and the checker's own `fi-dominates-flipped`
  mutant was "caught" against the wrong answer. Only running the image
  (`realcontroller_check`) showed it. The image-backed checkers are
  airoute, average, car, carmode, drivetarget_image, joystick,
  mellowmover, physicscar, quickspline, realcontroller, realdriver and
  trackpath. Every other
  `*_check.py` compares against a Python model, which includes most of
  task 25: carstate, engine, cartypeinfo, cardriver, steering, rigidbody,
  suspension, wheel, drivetrain, graph, physicssystem,
  aerodynamics and physcomp. car_check, physicscar_check and
  mellowmover_check do run the image's copies of some of those beneath
  them, but only as far as their scenarios reach. A model-only pass is
  evidence that two readings agree, not that either matches the console.
  DriveTarget did it twice (the Fill test, then StraightLinePredict's pad
  lane) before `drivetarget_image_check` took the model out of the oracle.
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
  after five top-level chunks. The real counts are 497 top-level and 7,101
  recursively. The dumper still leaves out the 25 all-zero headers, so it
  counts 472 and 7,076. `bchunk.c` had always skipped them, so the C and the
  tool disagreed silently. Fixed this session -- but the lesson is that the
  dumper is not the authority, the loader is. LoadChunks walks all 497, and
  LoaderNull takes the 285 of type 0, the 25 zero headers among them.
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
