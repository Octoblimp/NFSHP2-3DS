# The LoaderTable -- how a bundle's chunks reach their loaders

    ResourceFile's load half        0x0018f6c8 .. 0x0018f918     592 bytes
    LoaderTable                     0x003081d0                   31 slots
    UnloaderTable                   0x00308250                   31 slots
    LoaderSolidList, its unloader   0x00102ff0 .. 0x00103514   1,312 bytes
    eFixUpTables, FixStripEntryTable 0x00103790 .. 0x00103918    392 bytes
    FixTextureTable                 0x0010aa90                  108 bytes
    FixLightMaterialTable           0x0010b130                   84 bytes
    eFindSolid, eModel's list half  0x0010b1f8 .. 0x0010b444,   888 bytes
                                    0x0010b528, 0x0010b7b0 and 0x00114918

Between the unloader and eFixUpTables, `eDuplicateSolid`,
`eDeleteAllDuplicatedSolids` and `eCalcAutoK` are not ported, and neither
are eModel's `AttachReplacementTextureTable` and `RenameTexture`.

A bundle is read whole and loaded in place. `LoadChunks` walks its top
level and gives each chunk to the loader that takes it. Unloading walks
back through a second table. `PostLoadFixup` then settles what the loaders
left dirty: the solids' texture tables, the models' solids, and the eight
textures the renderer keeps pointers to.

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
nothing for a NULL file or a size of 0.

A loader looks at the chunk's type. It returns 0 for a type it does not
take, and nonzero for one it does.

**TraverseChunks** (0x0018f6d8) keeps two counters, a slot and a miss
count. It tries the chunk at the current slot:

- If that slot takes it, the walk moves to the next chunk and the miss
  count goes back to 0. The slot does *not* go back to 0: the next chunk
  is tried from the slot that took this one.
- If that slot does not take it, the slot moves on one, wrapping at 31, and
  the miss count goes up.
- When the miss count passes 31, nobody has taken the chunk. The walk calls
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
30 and stops at the first taker, calling `bBreak` if there is none. Then
the chunk becomes the new `end`. There is no quirk here: every chunk gets
all 31 tries.

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

The types in the "Takes" column are the guards' constants: every type the
disc has, plus the guards' other constants. The counts cover 73 bundles
and 52 top-level types, and "TB12" is TRACKB12.

| Slot | Name | Takes | Disc | TB12 | Port |
|---:|---|---|---:|---:|---|
| 0 | Null | `00000000` padding | 421 | 285 | `loader_null` |
| 1 | TrackGeometry | `34130`..`34133` topology tree, `34146` markers, `34200` track info, `34201` track table | 1 each | 6 | `track.c` |
| 2 | TexturePack | `b0300001`, `b0300100` | 10, 10 | 0 | `texturepack.c` |
| 3 | FontInfo | `15010`, `30200` | 11, 0 | 0 | -- |
| 4 | SolidList | `80034000` | 110 | 65 | `esolid.c` |
| 5 | LightList | `80034015`, `80034019`, `3401c`, `3401e` | 1, 1, 0, 1 | 2 | -- |
| 6 | AcidFX | `80035000`, `80035010`, `35020`, `35021` | 0, 0, 2, 2 | 2 | -- |
| 7 | EventManager | `80036000` | 1 | 1 | -- |
| 8 | PositionMarkers | `34013` | 27 | 0 | -- |
| 9 | CollisionVolumes | `80034020` | 16 | 1 | `polyhedra.c` |
| 10 | FlailerChunk | `80010200` | 3 | 0 | -- |
| 11 | Scenery | `80034100` sections, `34106` zones | 122, 1 | 123 | `scenery.c` |
| 12 | Animations | `80034008` | 20 | 0 | -- |
| 13 | Cameras | `80034405`, `80034410`, `80034415`, `80034420`, `80034425`, `34492` | 1, 1, 1, 0, 1, 1 | 2 | -- |
| 14 | Sun | `34202` | 1 | 1 | `sun.c` |
| 15 | Cops | `80034500` | 1 | 1 | -- |
| 16 | CarInfo | `34600`, `34601` | 1, 1 | 0 | -- |
| 17 | BodyDamage | `34030` | 52 | 0 | -- |
| 18 | TrackRoutes | `34121` routes, `34122` signposts | 1, 1 | 2 | `trackroute.c` |
| 19 | TrackPath | `80034147` | 1 | 1 | `trackpath.c` |
| 20 | PhysPredict | `34700` | 1 | 0 | -- |
| 21 | NisInfo | `37010` | 1 | 0 | -- |
| 22 | SoundScape | `80038000` | 1 | 1 | -- |
| 23 | CharacterInfo | `34300`, `34301` | 1, 1 | 0 | -- |
| 24 | HeliSheet | `34800` | 1 | 1 | -- |
| 25 | EventTree | `80034a00` | 4 | 0 | -- |
| 26 | DifficultyInfo | `34b00` | 1 | 0 | `difficultyinfo.c` |
| 27 | Language | `39000` | 8 | 0 | -- |
| 28 | Smokeables | `34026`, `34027` | 16, 1 | 2 | -- |
| 29 | WeatherMan | `34250` | 1 | 1 | `weatherman.c` |
| 30 | DemoModeReplay | `39100`, `39101`, `39102` | 5, 24, 5 | 0 | -- |

TRACKB12 has 497 top-level chunks, and every one has a taker.

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
   `GetTextureInfo(name, 1)`, and `FixLightMaterialTable` sets each entry's
   pointer to `elGetLightMaterial(name)`.
2. **External rigid animation.** If `ExternalRigidAnimationNameHash` is
   nonzero and a solid of that name is already loaded, the solid takes that
   solid's `pRigidAnimation`.
3. **Names.**
   - If the solid is vertex animated (flag `0x10`), the frames of the
     animation are solids of one name, one after another. The first frame
     takes a 272-byte eVertexAnimator from its slot pool, with a frame rate
     of 30 and itself in `SolidTable[0]`. Each later frame joins that
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
  4. `GetTextureInfo(hash, 0)` for the eight textures the renderer keeps
     (`pTextureInfoRVMInfo` .. `pTextureInfoCarSelectEnvMap`).
- Otherwise, if only `eDirtyAnimations` is set, it calls
  `ReconnectAllAnimations` and clears that flag.

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
- **`ReconnectTextureTable`** gets each replacement's `GetTextureInfo(new,
  1)`. It finds the old name's index in the solid's texture table (or -1)
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
- **In place.** On the handheld an eSolid is 192 bytes, as on the disc,
  and the bundle is loaded where it lies. The checker's host has 8-byte
  pointers, so its harness rebuilds each record with the host's struct
  and the host's pad, and prints offsets in disc bytes.

## Checking it

    python tools/loadertable_check.py
    python tools/loadertable_check.py --mutate [--only a,b]

The check runs 27,897 ops and prints 41,988 lines, with 0 differ. Of the
102 mutations, 100 are caught and 2 are equivalent by construction:

- `load-size0`: `LoadChunks`' size test only ever saves a walk of nothing.
- `unload-count-kept`: an animator's count is not read again once the
  animator is freed.

The scenarios cover:

- **The claims.** Every disc type, every guard constant and their
  neighbours, through all 62 slots.
- **The walks.** Both walks over probe tables: the unclaimed-chunk quirk,
  two takers, short tables, and both directions.
- **The tables.** LoadChunks and UnloadChunks through the real tables,
  including over TRACKB12's 497 chunks.
- **The disc.** Every solid list on the disc is loaded, fixed up and
  unloaded, with models on TRACKB12's names.
- **Built lists.** Vertex animation, duplicate names, external rigid
  animations, labelled frames, every pad and odd sizes.
- **eFixUpTables** under all 16 flag settings, and eModel's calls.
- **The sun.** TRACKB12's own sun chunk is loaded and unloaded through both
  tables at each misalignment, then at version 1. Each dump shows SunInfo
  and SunPosition.
