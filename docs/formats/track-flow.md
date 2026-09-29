# The track flow -- the steps either side of a race's track

    EndGameFlowLoadingTrackSpecific      0x001645e8    248 bytes
    BeginGameFlowUnloadingTrackSpecific  0x001646e0    408 bytes

These are two of the game flow's state functions: the End of
`LOADING_TRACK_SPECIFIC` and the Begin of `UNLOADING_TRACK_SPECIFIC`. See
[boot-flow](boot-flow.md) for the table they sit in and for
`ServiceGameFlow`, which calls them. The End runs once the track's bundles
are in, and starts every system that runs on the track. The Begin closes
those systems again, in nearly the reverse order, and hands the track's
files back.

Both are a straight line of calls with a few stores between them.

The port is `3DS Files/source/trackflow.{c,h}`. It is cross-checked by
`tools/trackflow_check.py` against `tools/src/trackflow_test.c`. The track
viewer (`trackview.c`) runs both. See [track-render](track-render.md).

## What loads before the End

`BeginGameFlowLoadingTrackSpecific` sets `eDisableFixUpTables` to 1. It
then queues `TRACKA%d.BUN` and `TRACKB%d.LZC`; the second is renamed `.BUN`
for hot chunking. Then it calls LoadHudTextures. The parts that follow load
these, in order:

1. the languages and the demo replay;
2. `PRERACEANIM` and `POSTRACEANIM%d`;
3. `TEX%dTRACK.BIN`, then `TEX%dLOCATION.BIN`;
4. `GLOBAL\DRIVTEX.BIN`;
5. the LOADING_TRACK screen, then `GetLoadedTexture`.

Every one is a ResourceFile. Its load is `LoadChunks` and then
`PostLoadFixup` (see [loader-table](loader-table.md)). With
`eDisableFixUpTables` set, `eFixUpTables` returns at once. So the solids'
texture tables stay as the loaders left them until the End clears the flag
and fixes everything once. TRACKB12's solids name textures that only
`TEX12LOCATION.BIN` has, and that file loads after the bundle. It is
this single fix-up that lets them find those textures.

## EndGameFlowLoadingTrackSpecific -- 0x001645e8

In order. A call marked *seam* goes through a function pointer in
`trackflow.h`, because the port does not have that callee yet.

| # | What | Note |
|---:|---|---|
| 1 | `eDisableFixUpTables = 0` | stored ahead of the call |
| 2 | `eFixUpTables()` | the one fix-up of everything loaded since the Begin of loading |
| 3 | `InGameFlag = 1` | in the jal's delay slot, so after the fix-up |
| 4 | `InitCollision`, `InitCollisionBody`, `InitContact` | the collision pools |
| 5 | `TheTopologyTree.InitTree()` | `TrackPolygonSlotPool`, 1,024 slots |
| 6 | InitSmokeables | seam |
| 7 | `InitPhysics()` | the ten physics pools; see below for its count |
| 8 | `SkyLoader()`, `rain_Load()`, `SunTrackLoader()`, InitDebugTopology, InitTrackMarkers | Sky, rain and Sun are `sky.c`'s, `rain.c`'s and `sun.c`'s; rain_Load is empty (`rain.md`); the rest are seams |
| 9 | `InitVisibleZones()` | the `MARKER_BOUNDARY` model |
| 10 | `InitTrackPaths()` | |
| 11 | `TheTrackPathManager.ReverseTrackDirection = (TrackDirection == 1)` | in InitTrackRoutes' delay slot, so before it |
| 12 | `InitTrackRoutes(TrackDirection != 1)` | `forward` |
| 13 | InitTrackRouteEditor, InitWorldObjects, InitAnimatedDriver | seams |
| 14 | `WeHaveCheckedIfJR2ServerExists = 0` | in InitAIPlans' delay slot |
| 15 | InitAIPlans | seam |
| 16 | `pRaceCoordinator = new RaceCoordinator` | `bMalloc(144, "RaceCoordinator", 0, 16)`, then the ctor at `0x00147170`; one seam |

`TrackDirection` is `TheRaceParameters.TrackDirection`, at `0x0031252c`.
The listing computes both directions from one `xori a0,a0,1`:

```
00164678  xori   a0,a0,0x0001
0016467c  sltiu  v0,a0,1          ; v0 = (dir == 1)   -> ReverseTrackDirection
00164680  sltu   a0,zero,a0       ; a0 = (dir != 1)   -> forward
```

So backward is 1 exactly, and every other value runs forward, including 2
and -1.

**InitPhysics has no argument in the image.** It reads
`TheRaceParameters.NumDriverInfo` (`0x00312814`) itself. The port's
InitPhysics takes the count as an argument, and the End passes it
`RaceParametersNumDriverInfo`, which is now in `race.c`.
`InitWithDefaults` leaves it 0. The viewer never sets it, so there it is 0.

**The RaceCoordinator is not checked.** `pRaceCoordinator` is overwritten,
not deleted first. A second End without a Begin between them leaks the
first one. The port does the same thing.

## BeginGameFlowUnloadingTrackSpecific -- 0x001646e0

| # | What | Note |
|---:|---|---|
| 1 | `eDisableFixUpTables = 1`, `InGameFlag = 0` | |
| 2 | `SetFlailerScreenVisibility(LOADING_TRACK, 0)` unless `TheDemoDiscManager.bActive` (never set; the port has no demo disc and always hides it) | seam; `0xd0131dd1` |
| 3 | eWaitUntilRenderingDone | `gEWaitUntilRenderingDoneFn` |
| 4 | if `pRaceCoordinator`: `delete pRaceCoordinator` | seam; the deleting dtor, flags 3 |
| 5 | `pRaceCoordinator = 0` | in the next call's delay slot: after the delete, before the HUD pack |
| 6 | `pHudTexturePack->UnloadAllTexturesFromFile()` | seam; no NULL check in the image |
| 7 | CloseAIPlans, CloseAnimatedDriver, CloseWorldObjects, CloseTrackRouteEditor | seams |
| 8 | `CloseTrackRoutes()`, `CloseVisibleZones()` | |
| 9 | CloseTrackMarkers, CloseDebugTopology, `SunTrackUnloader()`, `SkyUnloader()`, `rain_Unload()` | Sun, Sky and rain are ported, and rain_Unload is empty; the rest are seams |
| 10 | `ClosePhysics()`, then CloseSmokeables (seam) | |
| 11 | `TheTopologyTree.CloseTree()`, `CloseTrackPaths()`, `CloseContact()`, `CloseCollisionBody()`, `CloseCollision()` | |
| 12 | `while ((f = FindResourceFile(3))) UnloadResourceFile(f)` | two seams; see below |
| 13 | UnLoadSoundRegions, `TheDemoModeReplay.UnloadResourceFile()`, `TheLanguageManager.UnloadAllLanguages()` | seams |
| 14 | `TheSlotPoolManager.CleanupExpandedSlotPools()` | |
| 15 | `while (!bIsAsyncDone(NULL))` | seam; spins until every queued read is done |
| 16 | `bCountFreeMemory(16)` | seam; the result is thrown away |
| 17 | `SkipFE = 0` | in the branch's delay slot, so on both paths |
| 18 | `ChangeGameFlow(PendingGameFlowState ? PendingGameFlowState : 8, 0)` | a tail call; 8 is `UNLOADING_TRACK_COMMON` |

This is the one reader of `PendingGameFlowState` in the image. The boot
flow's port had called it write-only, which was true only of
`ServiceGameFlow`. The pending state is where a race was going when it
was asked to leave. The second argument of 0 clears it.

**The resource-file loop.** `FindResourceFile` (`0x0018fe88`) walks
`ResourceFileList` from its tail through each node's `prev`, so it returns
the newest file of the type. `UnloadResourceFile` (`0x0018fd20`) first waits
out a load still in flight. Then it takes the file off the list, and
`~ResourceFile` (`0x0018fa50`) runs UnloadChunks, the bFree and
PostLoadFixup. Type 3 is the track's own files, so they go newest first:
TEX12LOCATION, TEX12TRACK, then the bundles.

## The port

`trackflow.c` calls the ported callees directly. Every other callee goes
through a seam. A NULL seam does nothing. A seam that returns a pointer
gives NULL, and a NULL `gBIsAsyncDoneFn` counts as done. The three
seams on objects the port has no global for take no `this`:
DemoModeReplay's, LanguageManager's and the RaceCoordinator's `new`.
`gFindResourceFileFn` and `gUnloadResourceFileFn` are used as a pair.
Find with no Unload would spin in the image as well.

`BGameFlow` keeps `SkipFE` and `PendingGameFlowState` in its struct, not
as globals, so the Begin reaches them through `gTrackFlowGameFlow`. When
that is NULL, the Begin skips all three flow steps: the read of the
pending state, the store to SkipFE and the ChangeGameFlow. The viewer
leaves it NULL, because it runs the two steps outside the flow's states.

Four globals are new: `InGameFlag` (`0x00323628`), `pHudTexturePack`
(`0x00323624`), `WeHaveCheckedIfJR2ServerExists` (`0x003234e4`) and
`RaceParametersNumDriverInfo` (`0x00312814`, in `race.c`).

### The viewer

`trackview_load` loads in the game's order:

1. the shared bundles' packs;
2. `eDisableFixUpTables = 1`;
3. TRACKB12;
4. TEX12TRACK;
5. TEX12LOCATION;
6. the End.

Each file is followed by `post_load_fixup`. `trackview_free` runs the
Begin with Find and Unload seams over the viewer's three files. They go
newest first, each unloaded the way `~ResourceFile` does it.

The viewer was checked on Azahar:

- **Load.** 1,135 solids are linked, and 342 textures uploaded. 49
  names get the default, which matches the disc's count. `InGameFlag` is
  1, `eDisableFixUpTables` 0, and `ReverseTrackDirection` 0.
- **Models.** There are 2,495, one more than before. The extra one is
  InitVisibleZones' `MARKER_BOUNDARY`. It has no solid: the only one on
  the disc is in INGAMEB.BUN, and the viewer hands only INGAMEB's texture
  chunks to the table.
- **Flipbooks.** All 46 frames past the first were uploaded, and none
  failed.
- **Free.** `InGameFlag` is 0 and `eDisableFixUpTables` 1. No solids,
  models or texture packs are left.

## Checking it

```bash
python tools/trackflow_check.py
python tools/trackflow_check.py --mutate
python tools/trackflow_check.py --dump out/trackflow
```

The model runs both functions from the image, with every callee stubbed.
Each stub prints its name and its arguments. It also prints six globals,
read at the moment of the call: InGameFlag, eDisableFixUpTables,
ReverseTrackDirection, WeHaveCheckedIfJR2ServerExists, pRaceCoordinator
and SkipFE. A store that moves across a call therefore shows up. The
calls made on TheDemoModeReplay, TheLanguageManager and TheSlotPoolManager
are also checked for their `this`.

There are 16 scenarios. They cover:

- track directions 0, 1, 2, -1 and 0x101;
- driver counts up to 0x7fffffff;
- a RaceCoordinator or none, and the HUD pack or none;
- 0 to 3 resource files, and 0 to 4 busy polls;
- a pending state or none;
- End then Begin, each alone, each twice, Begin then End, and EBEB;
- two scenarios with every seam NULL.

Results: 709 lines, 0 differ. Of the 74 mutations, 73 are caught. The
other one is port-only: it drops the Unload half of the resource-file
loop's guard, and the image has no seams to test that against.
