# Smokeables: the breakable roadside objects

Step 14b (2026-10-12). Signs, fences, bins, cones, the roadblocks' barrels,
and the base class of the helicopter's munitions.

| Object | Retail (SLES_507.31) | Port |
|--------|----------------------|------|
| `Smokeable.obj` | 0x0021ec80 .. 0x002220e8 | `smokeable.{c,h}` |
| `SmokeableInfo`'s loader and list | 0x0021f038 .. 0x0021f270, 0x0021f8f8 | `smokeableinfo.c` |
| Smokeable's table, 28 slots | 0x002bcb10 | `smokeable_install_vtables` |
| its PhysicsSystem's table, 4 slots | 0x002bcaf0 | the same |
| VirginSmokeable's table | 0x002bcbf0 | the same |
| `SmokeableCreators[4]` | 0x0031c1e0 | `smokeable.c` |
| the replay's snapshots | 0x0021fb30, 0x00220128, 0x002208a0 | `smokesnap.c` |

Before this the chunk slot that loads them (27, chunks 0x34026 and
0x34027) was unported, so a race had no breakable objects. The scenery
instances the spawners stand in for kept ExcludeFlags bit 0x10 set, so
`scenerycull.c` hid them too: no cones and no signs on the track. The demo
has the same object, with an 8-byte InitSmokeables. The port follows
retail.

## The two chunks

- **0x34026, the infos.** SmokeableInfos of 224 bytes. LoaderSmokeables puts
  each on the tail of SmokeableInfoList (gp-15848) and loads it: the
  terrain type is matched from TerrainTypeHash, and both emitter lists
  start empty. Then every info's children are found by ChildNameHashes.
  FindSmokeableInfo walks the list by NameHash.
- **0x34027, the spawners.** Records of 8 bytes: the info's hash and the
  scenery section and instance it replaces. They are kept where they lie
  (`pSmokeableSpawners`, `NumSmokeableSpawners`).

The unloader unlinks the infos and forgets the spawners.

## A smokeable's life

1. **InitSmokeables** (0x0021f270, 652 bytes). Each spawner's scenery
   instance has its packed rotation orthonormalised, then written back in
   units of 2^-14, each element truncated (cvt.w.s). The position is
   loaded and stored back unchanged.
2. **SpawnSmokeables** (0x0021f930). It fetches each info's anchor and
   dynamic emitters by group hash. It makes the two pools: a
   VirginSmokeable for each spawner, and 32 Smokeables of 1136 bytes. It
   registers the basic creator. It then makes a virgin for each spawner
   whose scenery section is loaded and whose info is known. In a
   two-player race it skips an instance with ExcludeFlags bit 1 set.
3. **The virgin** (100 bytes). A static body with no polygon, with ID
   `~index` and type VIRGIN_SMOKEABLE_COLLISION_BODY. Its box is the
   instance's box. Init clears the instance's bit 0x10, so the scenery
   draws it; destroy sets the bit again.
4. **The conversion.** DynamicCollisionBody::MaybeCreateWitnesses calls
   `gConvertToSmokeableFn` (ConvertToSmokeable, 0x0021fe90) when a car's
   box first touches a virgin. The virgin's instance becomes a basic
   Smokeable, which is a dynamic body with its own RigidBody, a
   WorldObject to draw it, and copies of the info's emitters. If the
   smokeable would be in the ground it is raised (GroundRaise, which
   sinks back at 0.5 a second once it is loose). Then the virgin is
   destroyed. When the pool is full, nothing is converted.
5. **The impulse** (ConsiderImpulse, 0x00221340).
   - A sleeping, anchored smokeable comes loose only when the impulse's
     size, or its moment about the centre of mass, reaches AnchorStrength.
     The part the anchor took is played back against the centre; the rest
     goes on.
   - A breakable one has its BreakingStrength worn down by half of each
     impulse, until one impulse is as large as what is left. Then it
     stores -1 there, and World::DoTimestepCollisions calls Break
     (`gSmokeableBreakFn`).
   - Break makes an awake smokeable for each child, then destroys this
     one. The pieces' models are named this model's name plus `_CHILD1`
     and on, with the hash carried on from this model's hash
     (`bchunk_hash_from`, bStringHash(const char *, int)).
6. **Move** (0x00220ce8).
   - Steps of at most 0.01 s.
   - Air drag `0.01 |v| v` for two models (hashes 0x98c6023c and
     0x8ac70e76).
   - The system table's ComputeAuxiliaries damps a slowing smokeable
     (0.95) and stops a settled one: under a quarter in both speeds,
     touching something, and two seconds from the last car.
7. **The end** (CheckTimers, 0x00221170).
   - A smokeable that never woke, after two seconds untouched with no
     witnesses, becomes a virgin again at its spawner.
   - One that woke dies when its info's Lifetime runs out, through the
     table's OnLifetimeEnd (slot 216). The munitions override that slot.
8. **DeleteFarAwaySmokeableCollisionBodies** (0x0021f610). DoTimestepMove
   calls it every 128 world steps.
   - It always deletes a smokeable whose numbers blew up: faster than
     1000, or a rotation element past 50.
   - When fewer than 10 slots are free, it also deletes sleeping ones
     woken more than 45 s ago and more than 120 from every player.
   - Neither rule deletes one whose info's Padding2 word is nonzero.

## The roadblock's barrels

`barricade.c` spawns its barrels through `smokeable_spawn` (0x0021ed28).
It stands each barrel on the ground at x and y, turned about the ground's
normal. The barrel's info is `CS_RoadBlock_Barrel`. Its mass and inertia
are scaled by the barricade.

`main.c` binds two seams for the barricade:
- `gBarricadeDeleteBarrelFn` deletes a barrel by id (0x0021ef88). It
  deletes nothing if the id is no longer one of that info's.
- `gBarricadeMarkBodyFadingFn` is SetBlinking.

## The replay

TASKS 72d-2 ported SnapshotAllSmokeables (0x0021fb30) and the two
DoSnapshots in slot 16, Smokeable's (0x002208a0) and VirginSmokeable's
(0x00220128), in `smokesnap.c`. What each moves is in
[replay.md](replay.md); `tools/worldsnap_check.py` runs them against
retail.

## Where the port differs from the image

- **smokeable_delete** tests the body for NULL before reading its Type. The
  image reads the Type first, which reads low memory when the body is
  gone.
- **Uninitialised w lanes.** The image leaves some vector w lanes as
  whatever was on the stack: the cross products in Spawn, the angular
  momentum in SetInitialPosition, the stopped momenta, and drag's point.
  The port writes 0.
- **CheckTimers' return.** It returns 1 when it destroyed the smokeable,
  and Move then leaves it alone. Retail writes GroundRaise into the freed
  slot, which the next init sets again.
- **VirginSmokeable's name.** The port bounds the snprintf (the image's
  bSPrintf has none). The name is at most 15 + 23 characters.
- **The deletes' list on the stack** is a whole CollisionBody, reached
  through the bodies' own links, as the image's bTList<CollisionBody>
  is. It was a bare CollisionBodyNode, and to GCC's strict aliasing at
  -O3 a write through a CollisionBody could never touch it: the loop
  that empties the list was dropped. Every smokeable and virgin then
  stayed alive past the race's end and the far-away deletes, off the
  body list but its WorldObject still on WorldObjectList, after its pool
  was freed, and Restart Race's world update went round a NULL node
  (TASKS 37f-2). Once that was mended, `destroy_list`'s first push onto
  CollisionBodyList linked a stale head, reached the same way, so the
  Makefile now builds with `-fno-strict-aliasing`. The port reaches
  other lists' heads through their items' types too.

## The checker

`tools/smokeable_check.py` runs retail's image through `retail_model`, and
`tools/src/smokeable_test.c` runs the port; the two logs must match.

The script covers:
- loading the two chunks, a quad of children, and a zero-hash info;
- spawning ten spawners, converting and re-virgining;
- Break;
- the sleep, slowing and settled cases;
- the timers, including OnLifetimeEnd through a logging table (`vtlife`);
- the far-away deletes;
- `smokeable_spawn`, with and without ground;
- clearing and closing.

Results:
- `--dump out/smokeable`: 384 ops, 1238 lines, 0 differ.
- Mutations: 276 over `smokeable.c` and `smokeableinfo.c`, all caught or
  equivalent. The list's mutations (`move-*`, `destroy-*`, `far-pool`,
  `far-type`, `far-destroy`, `clear-delall`) name the list's whole
  CollisionBody since 37f-2. The equivalents are `rec-used`, `delete-flags`,
  `vconv-pos-raise`, `drain-null` and `move-timers`; the script states
  each one's reason.

The host harness is 64-bit, so offsetof(Smokeable, System) is 296 there.
The harness prints retail's 256 wherever a table's delta is that offset.

`loadertable_check` now drives the smokeables' slot (its table's 28,
`bchunkload.c`'s 27). One check loads a chunk of one
info whose first child is itself; the other loads two spawners. Each
checks the list, the child, the emitter lists, and the spawners.
