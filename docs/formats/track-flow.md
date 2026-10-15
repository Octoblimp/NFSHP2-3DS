# The track flow -- loading and unloading a race's track

    BeginGameFlowLoadingTrackCommon      0x00168db8
    GameFlowLoadingTrackCommonPart1      0x00168ac0
    GameFlowLoadingTrackCommonPart2      0x00168928
    LoadHudTextures                      0x00168c30
    ChooseLoadableTextures               0x001ee3c0   (hudtex.c)
    BeginGameFlowLoadingTrackSpecific    0x001690a0
    GameFlowLoadingTrackSpecificPart1-6  0x00169058 0x00169048 0x00169018
                                         0x00168f98 0x00168f78 0x00168f28
    EndGameFlowLoadingTrackSpecific      0x00169168
    BeginGameFlowUnloadingTrackSpecific  0x00169288
    BeginGameFlowUnloadingTrackCommon    0x00168ea0

These are the game flow's four track states, with the load callbacks that
chain them. See [boot-flow](boot-flow.md) for the table they sit in
(retail's `0x002faea0`) and for `ServiceGameFlow`, which calls them:

| State | | Begin | End |
|---:|---|---|---|
| 4 | `LOADING_TRACK_COMMON` | BeginGameFlowLoadingTrackCommon | |
| 5 | `LOADING_TRACK_SPECIFIC` | BeginGameFlowLoadingTrackSpecific | EndGameFlowLoadingTrackSpecific |
| 7 | `UNLOADING_TRACK_SPECIFIC` | BeginGameFlowUnloadingTrackSpecific | |
| 8 | `UNLOADING_TRACK_COMMON` | BeginGameFlowUnloadingTrackCommon | |

The common part is what every race loads whatever the track: INGAMEB and
the cars. The specific part is the track and what goes with it. Each
loading Begin queues files, and the last file's callback runs the next
part, so a state is a chain of callbacks, and the last link changes the
state.

The port is `3DS Files/source/trackflow.{c,h}` and `hudtex.{c,h}`. It is
cross-checked by `tools/trackflow_check.py` against
`tools/src/trackflow_test.c`. The track viewer (`trackview.c`) runs the
End and the Begin of unloading the track's part on their own.

## Loading the common part

**BeginGameFlowLoadingTrackCommon.**

1. `FreeMemoryBeforeLoadingTrackCommon = bCountFreeMemory(16)`;
2. `eDisableFixUpTables = 1`;
3. unless SkipFE, `SetFlailerScreenVisibility(LOADING_TRACK, 0)`, the
   loading screen up (`0xd0131dd1`; retail picks the demo disc's screen
   when `TheDemoDiscManager.bActive`, which the port never is);
4. `LoadResourceFile("GLOBAL\INGAMEA.BUN", 2, 0, NULL, 0)`;
5. `AnimatedDriverNeedsFixup = 1`;
6. `while (!IsResourceLoadingComplete()) ServiceResourceLoading()`.
   INGAMEA is 0 bytes on the disc, but it is waited out before INGAMEB is
   asked for;
7. `LoadResourceFile("GLOBAL\INGAMEB.LZC", 2, HOTCHUNKABLE | LZCOMPRESSED,
   Part1, 0)`, renamed `GLOBAL\INGAMEB.BUN` for hot chunking.

Type 2 is the in-game files and 3 the track's: each Begin of unloading
hands back one type. The card has INGAMEB both ways; it has the tracks'
TRACKB only as `.BUN`, already expanded, so `bfile.c` opens a missing
`.LZC` as its `.BUN`, and ResourceFile loads a file with no `COMP` header
as it is.

**Part1, the cars.** `TheCarLoader.InFrontEndFlag` and `RoundRobinFlag`
go to 0. Then two passes over the drivers:

1. The cars that cannot be vertex-damaged. A traffic car
   (`UsageType == 2`) is loaded with SkinNumber -1, and its skin is put
   back after. Its InstanceIndex is 0: traffic shares one set of solids.
   Any other car's InstanceIndex is what `CarLoader::Load` returns, as a
   signed byte.
2. The cars that can: InstanceIndex is Load's answer, whatever the type.

Then `TheCarLoader.BeginLoading(Part2)`. Load counts the instances of each
type, so the second car of a type is instance 1. See
[car-loader](car-loader.md).

**Part2, the copies.** A car's first instance draws with the solids its
bundle loaded. Each driver whose InstanceIndex is above 0 gets copies,
named by its BaseModelName and the instance:

- if it can be vertex-damaged, `%s_A` as `%s_A%d` and `%s_B` as `%s_B%d`,
  the two halves it deforms;
- then every such car's `%s_SCUFFS` as `%s_SCUFFS%d`.

Each is one `eDuplicateSolid(from, to)`. The image builds the two names
in 32-byte buffers on the stack, and a longer name runs over them; the
disc's longest base name is 11 characters. The port's buffers are 48
bytes, enough for a 31-letter name. Then
`ChangeGameFlow(LOADING_TRACK_SPECIFIC, 0)`.

## Loading the track's part

**BeginGameFlowLoadingTrackSpecific.**
`FreeMemoryBeforeLoadingTrackSpecific = bCountFreeMemory(16)`,
`eDisableFixUpTables = 1`, then `TRACKS\TRACKA%d.BUN` (type 3, no flags,
no callback) and `TRACKS\TRACKB%d.LZC` (type 3, hot-chunkable and
compressed, Part1), renamed `.BUN`. `%d` is `TheRaceParameters.TrackNumber`.

The parts, each started by the one before's last load:

| Part | What | Next |
|---:|---|---|
| 1 | the current language's speech; the demo replay's file if `TheDemoModeReplay.ActiveFlag`; `LoadSoundRegionsInGame(Part2, 0)` | the sound regions' callback |
| 2 | `LoadHudTextures(Part3)` | the last HUD texture's callback |
| 3 | unless SkipFE, `GLOBAL\PRERACEANIM.LZC` (type 3, compressed) | its callback, or Part4 at once |
| 4 | `TRACKS\TEX%dTRACK.BIN`, then `TRACKS\TEX%dLOCATION.BIN`, both hot-chunkable | the second's callback |
| 5 | `GLOBAL\DRIVTEX.BIN` | its callback |
| 6 | the loading screen down (`SetFlailerScreenVisibility(LOADING_TRACK, 1)`), `ChangeGameFlow(RACING, 0)` | |

The speech is `LanguageManager` at `0x0021e250`, which the port's
`gameflow.c` already had for the frontend; `bgf_load_current_speech` and
`bgf_unload_current_speech` make it public.

Every one is a ResourceFile. Its load is `LoadChunks` and then
`PostLoadFixup` (see [loader-table](loader-table.md)). With
`eDisableFixUpTables` set, `eFixUpTables` returns at once, so the solids'
texture tables stay as the loaders left them until the End clears the flag
and fixes everything once. A track's solids name textures that only its
`TEX%dLOCATION.BIN` has, and that file loads after the bundle: the single
fix-up is what lets them find those textures.

### LoadHudTextures

The player's gauges, then the third-person gauge everybody has. All go
into `pHudTexturePack` (`GLOBAL\HUDTEX.BIN`), one
`LoadTexturesFromFile(pack, &hash, 1, cb, 0)` each, and only the last has
a callback:

1. If there is one player car: the driver numbered 0, or the one numbered 1
   if 0 is missing or knocked out of the event (`EliminatedRank > 0`). If
   the one it lands on is there and in, its car's Speedo, Shadow and
   ThirdPerson, and its Tach if it has one, in that order, from
   ChooseLoadableTextures.
2. `3RDPERSONGAUGE_KMH` if the units are KPH (1), else
   `3RDPERSONGAUGE_MPH`, with the callback.

Each hash is in a word of its own on the stack: the pack keeps the pointer
only for the call.

### ChooseLoadableTextures -- 0x001ee3c0

Also called by `Player::SetHudFeatures` (`0x001796b0`), so it is in
`hudtex.c`. From the car's CarTypeInfo (see
[car-type-info](car-type-info.md)), whose HudInfo at +1232 holds
IsIntegrated (int, +0) and MaxRPM (float, +16):

- **ThirdPerson** is `3RDPERSON_%d` of MaxRPM truncated (`cvt.w.s`).
- **The base name** is `MURCIELAGO` for `LAMBOCOP`. Otherwise it is the
  car's name less a `COP` or an `HP` on its end. The tails are compared at
  `len-3` and `len-2` with no length check; the disc has no name short
  enough to read before it.
- **Speedo** is `%s_KMH` for units 1 and `%s_MPH` for units 0. Any other
  units leave the name buffer as it was, so Speedo is ThirdPerson's hash.
- An integrated car (IsIntegrated not 0) has **Tach** 0 and **Shadow**
  `OVERLAY_%s`. Any other has Tach `%s_TACH` and Shadow `OVERLAY_GENERIC`.

All four are `bStringHash`es.

## EndGameFlowLoadingTrackSpecific -- 0x00169168

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
| 7 | `InitPhysics()` | the ten physics pools; it reads NumDriverInfo itself, and the port's is handed it |
| 8 | `SkyLoader()`, `rain_Load()`, `SunTrackLoader()`, InitDebugTopology, InitTrackMarkers | rain_Load is empty (`rain.md`); the last two are seams |
| 9 | `InitVisibleZones()` | the `MARKER_BOUNDARY` model |
| 10 | `InitTrackPaths()` | |
| 11 | `TheTrackPathManager.ReverseTrackDirection = (TrackDirection == 1)` | in InitTrackRoutes' delay slot, so before it |
| 12 | `InitTrackRoutes(TrackDirection != 1)` | `forward` |
| 13 | InitTrackRouteEditor, InitWorldObjects, InitAnimatedDriver | seams |
| 14 | `WeHaveCheckedIfJR2ServerExists = 0` | in InitAIPlans' delay slot |
| 15 | InitAIPlans | seam |
| 16 | unless an AI or replay demo, SetRenderEggFromEasterEggs (`0x0024bf18`) | seam; eggs 0-4 and 8 pick the Stomper's modes |
| 17 | `pRaceCoordinator = new RaceCoordinator` | `bMalloc(144, "RaceCoordinator", 0, 16)`, then the ctor at `0x00149738`; one seam |

Both directions come from one `xori a0,a0,1` (`sltiu` for reverse, `sltu`
for forward), so backward is 1 exactly, and every other value runs
forward, including 2 and -1.

**The RaceCoordinator is not checked.** `pRaceCoordinator` is overwritten,
not deleted first, and the port does the same.

## BeginGameFlowUnloadingTrackSpecific -- 0x00169288

| # | What | Note |
|---:|---|---|
| 1 | `eDisableFixUpTables = 1`, `InGameFlag = 0` | |
| 2 | the loading screen up | seam, as in the common Begin |
| 3 | eWaitUntilRenderingDone | seam |
| 4 | if `pRaceCoordinator`: `delete pRaceCoordinator` | seam; the deleting dtor, flags 3 |
| 5 | `pRaceCoordinator = 0` | in the next call's delay slot: after the delete, before the HUD pack |
| 6 | `pHudTexturePack->UnloadAllTexturesFromFile()` | seam; no NULL check in the image |
| 7 | CloseAIPlans, CloseAnimatedDriver, CloseWorldObjects, CloseTrackRouteEditor | seams |
| 8 | `CloseTrackRoutes()`, `CloseVisibleZones()` | |
| 9 | CloseTrackMarkers, CloseDebugTopology, `SunTrackUnloader()`, `SkyUnloader()`, `rain_Unload()` | the first two are seams |
| 10 | `ClosePhysics()`, then CloseSmokeables (seam) | |
| 11 | `TheTopologyTree.CloseTree()`, `CloseTrackPaths()`, `CloseContact()`, `CloseCollisionBody()`, `CloseCollision()` | |
| 12 | `while ((f = FindResourceFile(3))) UnloadResourceFile(f)` | two seams; see below |
| 13 | UnLoadSoundRegions, `TheDemoModeReplay.UnloadResourceFile()`, the speech | the first two are seams |
| 14 | `TheSlotPoolManager.CleanupExpandedSlotPools()` | |
| 15 | `while (!bIsAsyncDone(NULL))` | seam; spins until every queued read is done |
| 16 | if `bCountFreeMemory(16) != FreeMemoryBeforeLoadingTrackSpecific`: `eFlashScreen(0, 128, 0, "Memory Leak - Track Specific", 1.0)` | seams; a green flash for a second |
| 17 | `SkipFE = 0` | in the branch's delay slot, so on both paths |
| 18 | `ChangeGameFlow(PendingGameFlowState ? PendingGameFlowState : UNLOADING_TRACK_COMMON, 0)` | |
| 19 | unless an AI or replay demo, ResetRenderEggs and ClearTemporaryEasterEggs | seams; the latter zeroes +48 of each 56-byte egg whose +52 is 0 |

This is the one reader of `PendingGameFlowState`: where a race was going
when it was asked to leave. The second argument of 0 clears it.

**The resource-file loop.** `FindResourceFile` (`0x00199890`) returns the
newest file of the type. `UnloadResourceFile` (`0x00199728`) first waits
out a load still in flight, then takes the file off the list, so the
track's files go newest first. See [resource-file](resource-file.md).

## BeginGameFlowUnloadingTrackCommon -- 0x00168ea0

1. `while ((f = FindResourceFile(2))) UnloadResourceFile(f)`;
2. `eDeleteAllDuplicatedSolids()`, the copies Part2 made;
3. `TheCarLoader.UnloadEverything()`;
4. the same leak check against `FreeMemoryBeforeLoadingTrackCommon`,
   "Memory Leak - Track Common";
5. `ChangeGameFlow(LOADING_FRONTEND, 0)`.

## The port

`trackflow.c` calls the ported callees directly; every other callee goes
through a seam in `trackflow.h`. A NULL seam does nothing, one that
returns a pointer gives NULL, a NULL `gBIsAsyncDoneFn` counts as done and
a NULL `gBCountFreeMemoryFn` counts 0. A NULL load seam
(`gLoadSoundRegionsInGameFn`, `gLoadTexturesFromFileFn`) runs its
callback at once, so the chain still reaches RACING.
`gFindResourceFileFn` and `gUnloadResourceFileFn` are used as a pair:
Find with no Unload would spin in the image as well.

`BGameFlow` keeps `SkipFE`, `DesiredGameFlowState` and
`PendingGameFlowState` in its struct, not as globals, so the states reach
them through `gTrackFlowGameFlow`. `main.c`'s wrappers for the four states
set it to the flow before each runs. When it is NULL, the steps that need
it are skipped: SkipFE reads 0, and the ChangeGameFlows and the speech are
not done. The viewer runs the Begin of unloading with it NULL, so it
neither changes the flow nor unloads the frontend's speech.

The globals, at retail's addresses: `InGameFlag` (`0x00330540`),
`pHudTexturePack` (`0x0033053c`), `WeHaveCheckedIfJR2ServerExists`
(`0x003303ec`), `FreeMemoryBeforeLoadingTrackCommon` (`0x0033052c`),
`FreeMemoryBeforeLoadingTrackSpecific` (`0x00330530`),
`AnimatedDriverNeedsFixup` (`0x00330570`) and `DemoModeReplayActiveFlag`
(`TheDemoModeReplay` +0, `0x002f0960`).

**Not on the device yet.** Nothing enters `LOADING_TRACK_COMMON`: the
frontend's race start is not ported. Before it can, the device needs the
texture pack streaming behind `LoadTexturesFromFile` and a
`pHudTexturePack`, `LoadSoundRegionsInGame`, the demo replay's file,
and the eggs. `eDuplicateSolid` and `eDeleteAllDuplicatedSolids` are
ported (Session 52, [loader-table](loader-table.md)); before that a
second car of the player's type drew its wheels alone.

### The viewer

`trackview_load` loads the track's files in the game's order, with
`eDisableFixUpTables` set, then runs the End. `trackview_free` runs the
Begin of unloading with Find and Unload seams over the viewer's files,
newest first, each unloaded the way `~ResourceFile` does it.

### The race's view

In a race `main.c` attaches a view to the track the flow loaded
(`raceAttachTrack`): meshes, textures and heap of its own, read out of
the bundles the flow keeps in. `gTrackFlowViewUnloadFn`, the port's own
seam, called right after step 3 (eWaitUntilRenderingDone), lets go of it
while those bundles are still in: `raceDetachTrack` waits for the GPU's
queue (`gxCmdQueueWait`, half a second at most) and runs
`trackview_free`, which for an attached view frees only what the view
made. NULL does nothing, as retail; the viewer leaves it NULL.

Before Session 108 the main loop let go of the view only once the
coordinator was gone, on its next pass. Next Race's unload goes on to
the next race's load in the same pass of the flow, so the second load's
TRACKB (9 MB) found the heap still holding the first race's view, and
both Azahars aborted (`bMalloc: 8995308 bytes for TRACKS\TRACKB11.LZC`).
The main loop's check stays, for a race gone some other way.

## Checking it

```bash
python tools/trackflow_check.py
python tools/trackflow_check.py --mutate
python tools/trackflow_check.py --dump out/trackflow
```

The model runs the retail image's own functions, with RaceParameters'
GetDriverInfo and the string and memory routines under them, and every
other callee stubbed. Each stub prints its name, its arguments and
thirteen globals, read at the moment of the call, so a store that moves
across a call shows. The loads queue their callbacks, and a step of the
script runs the oldest, so a scenario walks a whole chain one link at a
time. CarLoader::Load answers each type's count so far from a base the
script sets, as a signed byte, and after every step the transcript holds
each driver's InstanceIndex and SkinNumber. The cars are GLOBALB.BUN's own
64 records.

There are 22 scenarios. They cover:

- the whole chain, Begin to Begin, for a plain race and for one with
  vertex damage, KPH, SkipFE, driver 0 knocked out, the replay, an AI demo,
  the instance counts wrapping, a leak, a slow INGAMEA, files to unload, a
  busy reader and a pending state;
- the chain with every seam NULL, with and without SkipFE, and the leak
  checks with the counts NULL;
- LoadHudTextures over player counts, units 0, 1, 2, -1 and 127, and
  every way drivers 0 and 1 can be missing or knocked out;
- each part alone and out of order, Part2 over preset instances from -128
  to 127, Part1 over NumDriverInfo above and below the drivers;
- the Begins of unloading over pending states, demo modes and leaks either
  way, and the End over five track directions;
- ChooseLoadableTextures on all 64 cars in four units settings, and on
  patched names (every COP and HP tail, LAMBOCOP's near misses, a 31-letter
  name), MaxRPMs (fractions, negatives, out of range, infinities, NaN) and
  IsIntegrated words;
- a load over patched records: a cop that is traffic, traffic that is a
  racer, a long base name.

Results: 749 ops, 2,333 lines, 0 differ. Of the 254 mutations, 252 are
caught. The other two are port-only: they drop the Unload half of a
resource-file loop's guard, and the image has no seams to test that
against.
