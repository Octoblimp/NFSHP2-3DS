# The LoaderTable -- how a bundle's chunks reach their loaders

    ResourceFile's load half        0x0018f6c8 .. 0x0018f918     592 bytes
    LoaderTable                     0x003081d0                   31 slots
    UnloaderTable                   0x00308250                   31 slots
    retail's LoaderTable            0x00310280                   30 slots
    retail's UnloaderTable          0x003102f8                   30 slots
    LoaderSolidList, its unloader   0x00102ff0 .. 0x00103514   1,312 bytes
    eFixUpTables, FixStripEntryTable 0x00103790 .. 0x00103918    392 bytes
    retail's eDuplicateSolid        0x00103bf0
    retail's eDeleteAllDuplicatedSolids 0x00103d58
    retail's eSolid::ChangeName     0x00104030
    retail's eFixUpTables           0x00103e68
    retail's falloff ramp           0x00103260 .. 0x001033bc     348 bytes
    retail's ReconnectSolid         0x0010c5e8 .. 0x0010c680     152 bytes
    FixTextureTable                 0x0010aa90                  108 bytes
    FixLightMaterialTable           0x0010b130                   84 bytes
    eFindSolid, eModel's list half  0x0010b1f8 .. 0x0010b444,   888 bytes
                                    0x0010b528, 0x0010b7b0 and 0x00114918

Between the unloader and eFixUpTables, `eCalcAutoK` is not ported, and
neither are eModel's `AttachReplacementTextureTable` and `RenameTexture`.

A bundle is read whole and loaded in place. `LoadChunks` walks its top
level and gives each chunk to the loader that takes it. Unloading walks
back through a second table. `PostLoadFixup` then settles what the loaders
left dirty: the solids' texture tables, the models' solids, and the nine
textures the renderer keeps pointers to (the demo's eight).

The port is in three files:

- `3DS Files/source/bchunkload.{c,h}` has the two walks, the two tables and
  `PostLoadFixup`.
- `3DS Files/source/esolid.{c,h}` has `LoaderSolidList`, its unloader,
  eSolid's three table fix-ups and `eFixUpTables`.
- `3DS Files/source/emodel.{c,h}` is eModel.obj's list half.

They are cross-checked by `tools/loadertable_check.py` against
`tools/src/loadertable_test.c`. Everything above runs as shipped in
mipsemu, with the seams below stubbed at the same calls. The track viewer
(`trackview.c`) loads TRACKB12 this way. See
[track-render](track-render.md).

## The walks

`LoadChunks(c, size)` (0x0018f878) is
`TraverseChunks(c, c + size, LoaderTable, 31)`. `UnloadChunks` (0x0018f8a0)
is `TraverseChunksBackwards(c, c + size, UnloaderTable, 31)`. Both do
nothing for a NULL file or a size of 0. Retail's (0x00199280, 0x001992a8)
pass its tables and 30, and the port does the same.

A loader looks at the chunk's type. It returns 0 for a type it does not
take, and nonzero for one it does.

**TraverseChunks** (0x0018f6d8) keeps two counters, a slot and a miss
count. It tries the chunk at the current slot:

- If that slot takes it, the walk moves to the next chunk and the miss
  count goes back to 0. The slot does *not* go back to 0: the next chunk
  is tried from the slot that took this one.
- If that slot does not take it, the slot moves on one, wrapping at the
  table's size (the demo's 31, retail's 30), and the miss count goes up.
- When the miss count passes the table's size, nobody has taken the
  chunk. The walk calls
  `bBreak` (the debugger's breakpoint; the console carries on) and skips the
  chunk.

The miss count is not reset on a skip. So after one chunk nobody takes,
every later chunk gets **one try**, at whatever slot the walk has reached.
Each chunk that fails that try is another `bBreak` and another skip, until
one chunk is taken at its first try. A file with one stray type can
therefore lose the chunks after it, and whether a given chunk survives
depends on which slot the walk has reached. The port keeps this.

**TraverseChunksBackwards** (0x0018f790) finds the last chunk before `end`
by walking from the start every time. It tries that chunk from slot 0 to
the last and stops at the first taker, calling `bBreak` if there is none.
Then the chunk becomes the new `end`. There is no quirk here: every chunk
gets a try at every slot.

On the disc every type has exactly one taker, in both tables, so neither
walk ever reaches `bBreak`.

**PostLoadFixup** (0x0018f8c8) calls four things in order: `eFixUpTables`,
`eLightUpdateTextures`, `afxUpdateTextures` and `FlailerPostLoadFixup`.
ResourceFile calls it after every load and every unload.
**HotChunksPostLoadFixup** (0x0018f8f8) does the same and then calls
`EmptyFernFlatteners`.

## The slots

The image's slot names are `LoaderX__FP6bChunk` and `UnloaderX__FP6bChunk`.
Slot 0 is `LoaderNull` in both tables.

The port's tables are retail's: the demo's 31 without PhysPredict, the
demo's slot 20. Retail has no `0x34700` chunk and no loader for one. From
slot 20 on, retail's slot is the demo's less one. Retail rewrote two
loaders: Sun's (slot 14; its chunk is the demo's) and HeliSheet's, which
takes the container `0x80034800` (of `0x34801` and `0x34802`) where the
demo's took `0x34800`. Retail's LoadChunks and UnloadChunks differ from
the demo's only in the table and its count.

The types in the "Takes" column are the guards' constants: every type the
disc has, plus the guards' other constants. The counts cover the demo
disc's 73 bundles and 52 top-level types. "TB12" is the demo's TRACKB12
and "R-TB12" retail's, whose 279 top-level chunks all have a taker.

| Slot | Demo | Name | Takes | Disc | TB12 | R-TB12 | Port |
|---:|---:|---|---|---:|---:|---:|---|
| 0 | 0 | Null | `00000000` padding | 421 | 285 | 122 | `loader_null` |
| 1 | 1 | TrackGeometry | `34130`..`34133` topology tree, `34146` markers, `34200` track info, `34201` track table | 1 each | 6 | 6 | `track.c` |
| 2 | 2 | TexturePack | `b0300001`, `b0300100` | 10, 10 | 0 | 0 | `texturepack.c` |
| 3 | 3 | FontInfo | `15010`, `30200` | 11, 0 | 0 | 0 | -- |
| 4 | 4 | SolidList | `80034000` | 110 | 65 | 10 | `esolid.c` |
| 5 | 5 | LightList | `80034015`, `80034019`, `3401c`, `3401e` | 1, 1, 0, 1 | 2 | 2 | `elight.c` |
| 6 | 6 | AcidFX | `80035000`, `80035010`, `35020`, `35021` | 0, 0, 2, 2 | 2 | 2 | `acidsys.c` |
| 7 | 7 | EventManager | `80036000` | 1 | 1 | 1 | -- |
| 8 | 8 | PositionMarkers | `34013` | 27 | 0 | 0 | `epositionmarker.c` |
| 9 | 9 | CollisionVolumes | `80034020` | 16 | 1 | 1 | `polyhedra.c` |
| 10 | 10 | FlailerChunk | `80010200` | 3 | 0 | 0 | -- |
| 11 | 11 | Scenery | `80034100` sections, `34106` zones | 122, 1 | 123 | 123 | `scenery.c` |
| 12 | 12 | Animations | `80034008` | 20 | 0 | 0 | -- |
| 13 | 13 | Cameras | `80034405`, `80034410`, `80034415`, `80034420`, `80034425`, `34492` | 1, 1, 1, 0, 1, 1 | 2 | 2 | `cameracoord.c` ([camera-coordinator](camera-coordinator.md)) |
| 14 | 14 | Sun | `34202` | 1 | 1 | 1 | `sun.c` |
| 15 | 15 | Cops | `80034500` | 1 | 1 | 1 | `copmgr.c` ([cop-manager](cop-manager.md)) |
| 16 | 16 | CarInfo | `34600`, `34601` | 1, 1 | 0 | 0 | `carinfo.c` |
| 17 | 17 | BodyDamage | `34030` | 52 | 0 | 0 | `cardamage.c` ([car-damage](car-damage.md)) |
| 18 | 18 | TrackRoutes | `34121` routes, `34122` signposts | 1, 1 | 2 | 2 | `trackroute.c` |
| 19 | 19 | TrackPath | `80034147` | 1 | 1 | 1 | `trackpath.c` |
| -- | 20 | PhysPredict | `34700` | 1 | 0 | -- | gone in retail |
| 20 | 21 | NisInfo | `37010` | 1 | 0 | 0 | `nisinfo.c` |
| 21 | 22 | SoundScape | `80038000` | 1 | 1 | 1 | -- |
| 22 | 23 | CharacterInfo | `34300`, `34301` | 1, 1 | 0 | 0 | `characterinfo.c` |
| 23 | 24 | HeliSheet | retail `80034800`; the demo's `34800` | 1 | 1 | 1 | `helisheet.c` ([helisheet](helisheet.md)) |
| 24 | 25 | EventTree | `80034a00` | 4 | 0 | 0 | `eventtree.c` ([event-tree](event-tree.md)) |
| 25 | 26 | DifficultyInfo | `34b00` | 1 | 0 | 0 | `difficultyinfo.c` |
| 26 | 27 | Language | `39000` | 8 | 0 | 0 | -- |
| 27 | 28 | Smokeables | `34026`, `34027` | 16, 1 | 2 | 2 | -- |
| 28 | 29 | WeatherMan | `34250` | 1 | 1 | 1 | `weatherman.c` |
| 29 | 30 | DemoModeReplay | `39100`, `39101`, `39102` | 5, 24, 5 | 0 | 0 | -- |

The demo's TRACKB12 has 497 top-level chunks and retail's 279, and every one has a taker.

Slots 15 (Cops), 23 (HeliSheet) and 24 (EventTree) link whole objects. The harness
gets `tools/src/loadertable_copstubs.c`, which stands in for what the
rest of `copmgr.c` calls and exits if any of it is reached; the check
only walks the cop container. The checker had not linked since 12a wired
slot 15; 12k-1 brought it back with slot 23.

In the port, a slot marked "--" is only its guard. It takes the same types
as the image's slot and hands the chunk to `gUnportedLoaderFn(slot, unload,
chunk)`, which is NULL by default and so does nothing. Slot 1's loader
falls through to `TopologyTree::Loader` for the four tree types, exactly as
the image's does.

## LoaderSolidList -- 0x80034000

A solid list is a `0x34001` header followed by one `0x80034002` container
per solid. The header is `eSolidListHeader`: the file's name at +8, and
`InventoryHandle` at +48.

The loader first calls `bAddCodeineInventory`. That tells the debugger's
channel, which the port does not have, and returns
`bStringHash("SolidList,<name>")` into `InventoryHandle`. Then it walks the
containers. Each container's children are compared by type, and any other
type is left alone:

| Child | What | Where it goes |
|---|---|---|
| `34003` | the eSolid, 192 bytes | 16-aligned past a filler |
| `34004` | its eStripEntry table | `StripEntryTable`, 16-aligned |
| `34005` | the strips' VU1 packet | `StripEntryDataStart`, 16-aligned. `SizeofStripEntryData` is the size less the filler, and FixStripEntryTable moves every strip's `Data` by the packet's address |
| `34006` | its eTextureTable, 8 bytes an entry | `pTextureTable`, **unaligned**. `NumTextureTableEntries` is `size / 8` |
| `3401d` | its eLightMaterialEntry table | `LightMaterialTable`, 16-aligned |
| `34007` | its animation tree's nodes | `pAnimationTreeNodes`, 16-aligned. The count is (size less the filler) / 96 |
| `34012` | its eRigidAnimation | `pRigidAnimation`, 16-aligned |
| `34011` | that animation's labelled frames | `pRigidAnimation->pLabelledFrames`, **unaligned** |

The children can come in any order. A child that fills a field of the
eSolid has to come after `34003`, because until then there is no eSolid to
fill.

For each solid, the loader then does four things in order:

1. **Tables.** `FixTextureTable` sets each entry's pointer to
   `GetTextureInfo(name, 1, 0)`, and `FixLightMaterialTable` sets each entry's
   pointer to `elGetLightMaterial(name)`.
2. **External rigid animation.** If `ExternalRigidAnimationNameHash` is
   nonzero and a solid of that name is already loaded, the solid takes that
   solid's `pRigidAnimation`.
3. **Names.**
   - If the solid is vertex animated (flag `0x10`), the frames of the
     animation are solids of one name, one after another. The first frame
     takes a 272-byte eVertexAnimator from its slot pool, with a frame rate
     of 30 and itself in `SolidTable[0]`. `eInitSlotPools` (`0x0010a008`,
     in `eInitEngine`) makes that pool at boot: 16 slots, the default flags
     (it grows), at gp-25192. The port made it only when the track viewer
     started, so a race from the frontend, whose track loads first, wrote
     its animators through NULL (track 62, Session 44); main.c now makes it
     beside the model pool. Each later frame joins that
     animator's table, up to 64 frames, and shares the first frame's
     animator and rigid animation.
   - If the solid is not vertex animated, and a solid of its name is
     already loaded, both solids get flag `0x2`, the duplicate-name flag.
4. **Link.** `eDirtySolids` is set, and the solid goes on the end of
   `SolidList` by the bNode at its start.

**UnloaderSolidList** looks at each container's *first* child only. The
image reads the first child's type and never moves on, so a container
whose eSolid is not first would hang it. When that first child is an
eSolid, the unloader:

1. unlinks the solid;
2. if the solid has an animator, clears `pVertexAnimator` in every solid
   in the animator's table, and frees the animator;
3. sets `eDirtySolids`.

The image has three cases that go wrong, and the port keeps all three. The
checker avoids them, and none of them happens on the disc:

- **An animated solid whose name an earlier plain solid already has.** The
  loader reads that plain solid's NULL animator.
- **Unloading a list that was never loaded.** The unloader unlinks nodes
  that were never linked.
- **Unloading a list of more than 64 frames.** Each frame past the 64th
  frees the animator again.

## eFixUpTables -- what the dirty flags come back to

Four words sit next to each other: `eDisableFixUpTables`, `eDirtySolids`,
`eDirtyTextures` and `eDirtyAnimations`, at gp-25520 .. -25508. Any
nonzero value counts as set.

- If `eDisableFixUpTables` is set, `eFixUpTables` does nothing.
- If `eDirtySolids` or `eDirtyTextures` is set, it does the following in
  order, then clears all three dirty flags:
  1. If textures are dirty: for every solid on `SolidList`, call
     `FixTextureTable`, `FixStripSTs` and `CalcAutoK`.
  2. `ReconnectAllModels`.
  3. `ReconnectAllAnimations`.
  4. `GetTextureInfo(hash, 0, 0)` for the nine textures the renderer keeps
     (`pTextureInfoRVMInfo` .. `pTextureInfoCarSelectEnvMap`).
  5. The falloff ramp, below.
- Otherwise, if only `eDirtyAnimations` is set, it calls
  `ReconnectAllAnimations` and clears that flag.

The demo looked up eight textures, at gp-25672 .. -25644, and made no
ramp. Retail's nine are at gp-25144 .. -25112. The eighth,
`pTextureInfoFalloffRamp`, is new. It sits between SpecularFalloff and
CarSelectEnvMap, and its hash, `0xb9ab56e4`, is not one any file on
either disc names: the texture is made at run time, as SHADOWMAP1's is.
The name is the port's.

### The falloff ramp -- retail's 0x00103260

Only eFixUpTables calls it. It does nothing without the texture or its
`PaletteData` (148). Otherwise, with n = `PaletteSize` (60) >> 2, shifted
arithmetically, each entry i of n becomes a grey whose four bytes are all
v:

    s = max(bSin(i / n * 1.57075 + 1.5707965), 0.01)
    v = (int)(p(s) * 128) & 0xff

p is an inlined fast power: the bits of s read as an integer, times the
power, plus (1 - power) times the bits of 1.0, and back. At the power of
1.0 that is s with its low six bits rounded off. So the ramp falls from
128 to 1 over a quarter turn of sine. With 256 entries or more, the last
ones reach the 0.01 floor. A loop of `Width` (36, read signed) empty
passes comes first and does nothing.

## The copies -- eDuplicateSolid

The second and later car of a type draws its body from copies of the
type's solids. GameFlowLoadingTrackCommonPart2 makes them
([track-flow](track-flow.md)): `%s_A` and `%s_B` as `%s_A%d` and
`%s_B%d` for a car that can be dented, and `%s_SCUFFS` as `%s_SCUFFS%d`.
Without them that car has no body, only its wheels.

**`eDuplicateSolid(from, to)`** (retail `0x00103bf0`):

1. `eFindSolid(bStringHash(from))`; nothing when there is none.
2. A 192-byte copy of the eSolid, `bMalloc(192, "DuplicatedSolid", 0,
   16)` and the copy constructor (`0x00114bb0`, every field), linked at
   `SolidList`'s tail.
3. Copies of the strip data (`"DuplicatedStripEntryData"`,
   `SizeofStripEntryData` bytes) and of the strip table
   (`"DuplicatedStripEntryTable"`, 64 bytes a strip), each with pool 16
   and added to `MemoryUsedByDuplicatedSolids` (gp-24928). The 192 bytes
   are not counted.
4. `FixStripEntryTable` moves each strip's `Data` onto the copied data.
5. Flags gets `4`, and `ChangeName(to)` (`0x00104030`) copies the name
   (`bStrCpy`, unbounded; the disc's longest, `CORVETTECOP_SCUFFS7`, is
   20 bytes of the 24) and sets `NameHash`.

The texture and light-material tables, the animation tree, the rigid
animation and the vertex animator stay the original's.

**`eDeleteAllDuplicatedSolids()`** (retail `0x00103d58`), from the
Begin of unloading: every solid on `SolidList` with flag `4` has its
strip data and strip table freed (each when not NULL) and taken off the
counter, both pointers cleared, and is unlinked and freed. The dirty
flags are left alone.

The port's are in `esolid.c`; `main.c` points trackflow's
`gEDuplicateSolidFn` and `gEDeleteAllDuplicatedSolidsFn` at them.

## eModel's list half

An eModel is a name and a pointer to the solid of that name.

- **`Init(hash)`** stores the name. It clears the replacement table, its
  count and `RigidAnimationStartTime`, and, for a nonzero hash, calls
  `ReconnectSolid` and links the model onto `ModelList`. A hash of 0 does
  not link, and leaves `Solid` as it was.
- **`ReconnectSolid`** does nothing for a hash of 0 or a solid that has
  not changed. Otherwise it stores the found solid (possibly NULL) and
  zeroes the start time. That store is in a branch delay slot, so it
  happens for a NULL solid too. The start time becomes `0xc000` when the
  solid has a rigid animation whose byte at +2, `TriggerableFlag`, is 0.
  In retail, a solid with flag `0x20` then ORs in `bRandom(256)` from
  `bDefaultSeed` (through retail's `0x0025a488`), so that its copies do
  not move as one. The demo's eSolidFlags end at `0x10`. Retail's disc
  sets `0x20` only with vertex animation, on the 90 frames of
  TRACKB61..66's waving flag, and ReconnectSolid is its one reader.
- **`ReconnectTextureTable`** gets each replacement's `GetTextureInfo(new,
  1, 0)`. It finds the old name's index in the solid's texture table (or -1)
  and stores it under the model's instance index, then applies the table.
- **`ReconnectAllModels`** does, for every model: ReconnectSolid,
  ReconnectTextureTable, and `FixStripSTs` if the model has a solid.
- **`UnInit`** does nothing for a hash of 0. Otherwise it unlinks the model
  and zeroes the count, `Solid`, the name, the table and the start time.
- **The deleting destructor** (0x00114918) calls UnInit, then gives the
  slot back to `eModelSlotPool` when bit 0 of the flags is set.

## The seams

Each seam is a function pointer. A NULL seam does nothing, and a seam that
returns a pointer returns NULL.

- **`esolid.h`:** `gGetTextureInfoFn` (TexturePack.obj),
  `gElGetLightMaterialFn` (the light lists), `gFixStripSTsFn` and
  `gCalcAutoKFn` (the renderer's), and `gReconnectAllAnimationsFn` (the
  animation loader).
- **`texturepack.h`:** `gERenderTargetTextureInfoFn` and
  `gServiceQueuedFilesFn`; see [texture-pack](texture-pack.md).
- **`bchunkload.h`:** `gUnportedLoaderFn`, and PostLoadFixup's
  `gELightUpdateTexturesFn`, `gAfxUpdateTexturesFn`,
  `gFlailerPostLoadFixupFn` and `gEmptyFernFlattenersFn`.

## The disc

- **Lists.** The 73 bundles hold 110 solid lists in 44 files, with 1,465
  solids between them.
- **Containers.** Every container has its eSolid first.
- **Children.** 332 solids have light materials, 19 a rigid animation and
  13 an animation tree. None has labelled frames, and none is vertex
  animated, so no animator is ever made from the disc.
- **TRACKB12.** It has 65 lists, but only 10 of them hold containers, 1,135
  solids between them. The other 55 are a header alone, size 60, and each
  is followed by a padding chunk at the top level.
- **Padding.** 285 of TRACKB12's 497 top-level chunks are type 0. Twenty-five
  are an all-zero header, and the rest have a size from 4 to 280.
- **Retail.** The extracted retail bundles hold 352 lists in 80 files,
  with 28,504 solids, and none is a header alone. Every container has its
  eSolid first. 1,782 solids have light materials, 105 a rigid animation
  and 13 an animation tree, and 1,074 name an external rigid animation.
  None has labelled frames. 90 are vertex animated, all with flag `0x20`:
  the waving flag, `XF_FLAG_1_00`, 15 frames on each of TRACKB61..66,
  whose first frame has the rigid animation.
- **In place.** On the handheld an eSolid is 192 bytes, as on the disc,
  and the bundle is loaded where it lies. The checker's host has 8-byte
  pointers, so its harness rebuilds each record with the host's struct
  and the host's pad, and prints offsets in disc bytes.

## Checking it

    python tools/loadertable_check.py
    python tools/loadertable_check.py --mutate [--only a,b]

There are two images. On the retail image (`tools/retail_model.py`),
over the retail disc, run what shows the table -- the claims, and the
walks through LoadChunks -- and everything over the solid list,
eFixUpTables, eModel and the sun, which retail changed. The sun scenario
takes retail TRACKB12's own chunk. On the demo image, over the demo's
disc, run the walks over probe tables and the weather. TraverseChunks is
retail's as it is, and the weather scenarios load through the tables
only chunks a ported slot takes, so no slot number shows. The same
harness answers both.

The retail disc's files add up to more than the model's 32 MB heap, so
each disc file's heap is given back once it is unloaded (`OP_MARK`,
`OP_RELEASE`). The disc scenario takes every file but the tracks, and of
the tracks TRACKB12 and TRACKB61, whose waving flag has flag `0x20`.

The check runs 178 ops and prints 1,617 lines on the demo image, and
37,558 ops and 49,626 lines on the retail one, with 0 differ. Of the 156
mutations, 154 are caught and 2 are equivalent by construction:

- `load-size0`: `LoadChunks`' size test only ever saves a walk of nothing.
- `unload-count-kept`: an animator's count is not read again once the
  animator is freed.

The scenarios cover:

- **The claims.** Every type on the retail disc, every guard constant
  and their neighbours, through all 60 of retail's slots.
- **The walks.** Both walks over probe tables: the unclaimed-chunk quirk,
  two takers, short tables, and both directions.
- **The tables.** LoadChunks and UnloadChunks through the real tables,
  including over retail TRACKB12's 279 chunks.
- **The disc.** Every solid list in the retail disc's files but the
  tracks', and in TRACKB12's and TRACKB61's, is loaded, fixed up and
  unloaded, with models on each track's names and three on the waving
  flag's, whose start times are drawn.
- **Built lists.** Vertex animation, duplicate names, external rigid
  animations, labelled frames, every pad, odd sizes, and a list that is
  a header alone.
- **eFixUpTables** under all 16 flag settings, and eModel's calls.
- **The random start.** Solids with and without flag `0x20`, with and
  without a rigid animation, triggerable or not, and as vertex-animation
  frames, each reconnected under nine seeds and through eFixUpTables.
  `bDefaultSeed` is in every dump.
- **The falloff ramp.** Fourteen textures: palettes of 0 to 1,024
  entries, sizes that are not a multiple of four or are negative, no
  palette, and widths from -32,768 to 32,767. Each palette is printed
  with two guard words. Then a texture while nothing is dirty and while
  fix-ups are disabled, and none.
- **The sun.** TRACKB12's own sun chunk is loaded and unloaded through both
  tables at each misalignment, then at version 1. Each dump shows SunInfo
  and SunPosition.
- **The copies.** The Viper's and the bus's lists in one buffer: the
  body halves and scuffs copied for instances 1 and 7, the bus's scuffs
  that are not there, a copy's copy and a name copied twice. Each copy
  prints its name, its source, whether its strip data (given a pattern
  first, as the disc's comes as sizes) and its strip table but each
  `Data` are the source's, and the counter. Then finds, models on three
  copies, eFixUpTables with the solids dirty, the delete, a second
  delete with nothing left, one more copy and its delete.
