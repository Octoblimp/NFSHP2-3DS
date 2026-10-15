#pragma once
#include <stdint.h>

#include "gameflow.h"
#include "race.h"
#include "texturepack.h"

// The game flow's four track states, retail's (the state table is at
// 0x002faea0), with the chains of load callbacks they start. Decompiled in
// docs/formats/track-flow.md.
//
//   LOADING_TRACK_COMMON      Begin 0x00168db8
//   LOADING_TRACK_SPECIFIC    Begin 0x001690a0, End 0x00169168
//                             (its Loop, 0x00169160, is an empty function)
//   UNLOADING_TRACK_SPECIFIC  Begin 0x00169288
//   UNLOADING_TRACK_COMMON    Begin 0x00168ea0
//
// Loading the common part loads GLOBAL\INGAMEA.BUN and waits for it, then
// GLOBAL\INGAMEB.LZC. Its callback, Part1, has the car loader load every
// driver's car, and when they are in, Part2 duplicates the solids each
// further instance of a car draws with and moves on to the track. The
// track's TRACKA and TRACKB bundles come next. Then Part1 to Part6 run
// each from the last one's load: the speech and the attract replay, the
// sound regions, the HUD's textures, PRERACEANIM unless the frontend is
// skipped, the track's two texture files and DRIVTEX. Part6 takes the
// LOADING_TRACK screen down and asks for RACING, and the End starts every
// per-track system. The two unloading Begins take it all down again, and
// each flashes the screen green if the memory free afterwards is not what
// it was before the load.
//
// The callees the port has are called directly; the rest are seams below.
// A NULL seam does nothing, except that a seam that loads something runs
// its callback at once, as though it had nothing to load, a seam that
// returns a pointer gives NULL, a NULL gBIsAsyncDoneFn is "done" and a NULL
// gBCountFreeMemoryFn counts 0. ChangeGameFlow, SkipFE and the speech go
// through gTrackFlowGameFlow. tools/trackflow_check.py runs all of it out
// of the retail image with every callee stubbed, and diffs the calls,
// their arguments and the globals they leave behind.

// ------------------------------------------------------------- the globals

// gp-21424, 0x00330540. 1 from the End of loading to the Begin of
// unloading: a race's track is up.
extern int32_t InGameFlag;

// gp-21428, 0x0033053c. The HUD's TexturePack (GLOBAL\HUDTEX.BIN), which
// LoadHudTextures streams the gauges into. NULL in the port, which does
// not make the pack yet.
extern TexturePack *pHudTexturePack;

// gp-21764, 0x003303ec. The End of loading clears it, so the network code
// looks for the JR2 server again the next race.
extern int32_t WeHaveCheckedIfJR2ServerExists;

// gp-21444, 0x0033052c, and gp-21440, 0x00330530: bCountFreeMemory(16) as
// each Begin of loading starts, which its Begin of unloading compares.
extern int32_t FreeMemoryBeforeLoadingTrackCommon;
extern int32_t FreeMemoryBeforeLoadingTrackSpecific;

// gp-21376, 0x00330570. Set once INGAMEA is in; InitAnimatedDriver
// (0x001a9238) fixes the driver's model up when it is set, and clears it.
extern int32_t AnimatedDriverNeedsFixup;

// TheDemoModeReplay.ActiveFlag (+0), 0x002f0960: the attract replay is
// playing, so Part1 loads its file. Nothing in the port sets it yet.
extern int32_t DemoModeReplayActiveFlag;

// The flow ChangeGameFlow changes, whose PendingGameFlowState the Begin of
// unloading reads and whose SkipFE it clears and Part3 reads, and whose
// LanguageManager loads and unloads the speech. NULL skips all of those
// and reads SkipFE as 0 -- the viewer, which runs the End and the Begin of
// unloading outside the flow's states.
extern BGameFlow *gTrackFlowGameFlow;

// ----------------------------------------------------------------- seams

// FlailerScreenVisibility, SetFlailerScreenVisibility's second argument.
#define FLAILER_SCREEN_VISIBLE   0
#define FLAILER_SCREEN_INVISIBLE 1

// The End of loading, in call order.
extern void (*gInitSmokeablesFn)(void);            // 0x0021f270
extern void (*gInitDebugTopologyFn)(void);         // 0x00203ce0
extern void (*gInitTrackMarkersFn)(void);          // 0x001be310
extern void (*gInitTrackRouteEditorFn)(void);      // 0x001c5da0
extern void (*gInitWorldObjectsFn)(void);          // 0x001cd918
extern void (*gInitAnimatedDriverFn)(void);        // 0x001a9238
extern void (*gInitAIPlansFn)(void);               // 0x001c6028
// 0x0024bf18, the port's name: it sets the Stomper (pStomper, gp-14932)
// to the render egg of the first Easter egg that is on, of eggs 0, 1, 2,
// 3, 4 and 8. Not for an AI or replay demo.
extern void (*gSetRenderEggFromEasterEggsFn)(void);
// `new RaceCoordinator`: bMalloc(144, "RaceCoordinator", 0, 16) and the
// ctor (0x00149738). racecoord.h's racecoordinator_new is it. A NULL seam
// leaves pRaceCoordinator NULL.
extern RaceCoordinator *(*gNewRaceCoordinatorFn)(void);

// The Begin of unloading, in call order.
extern void (*gSetFlailerScreenVisibilityFn)(uint32_t screen,
                                             int visibility); // 0x0014cbf8
// RaceCoordinator's deleting dtor (0x00149858), with the 3 that frees it:
// racecoordinator_destroy.
extern void (*gDeleteRaceCoordinatorFn)(RaceCoordinator *rc, int32_t flags);
extern void (*gUnloadAllTexturesFromFileFn)(TexturePack *p); // 0x001acf98
extern void (*gCloseAIPlansFn)(void);              // 0x001c6058
extern void (*gCloseAnimatedDriverFn)(void);       // 0x001a9458
extern void (*gCloseWorldObjectsFn)(void);         // 0x001cd948
extern void (*gCloseTrackRouteEditorFn)(void);     // 0x001c5dd8
extern void (*gCloseTrackMarkersFn)(void);         // 0x001be378
extern void (*gCloseDebugTopologyFn)(void);        // 0x00203ce8
extern void (*gCloseSmokeablesFn)(void);           // 0x0021f500
// FindResourceFile(ResourceFileType) (0x00199890) and UnloadResourceFile
// (0x00199728), which both Begins of unloading empty a type with. The
// viewer puts its own in for the track's files.
extern void *(*gFindResourceFileFn)(int type);
extern void (*gUnloadResourceFileFn)(void *file);
extern void (*gUnLoadSoundRegionsFn)(void);        // 0x001af420
// DemoModeReplay::UnloadResourceFile on TheDemoModeReplay (0x002f0960).
extern void (*gDemoModeReplayUnloadFn)(void);      // 0x0013f0c0
extern int (*gBIsAsyncDoneFn)(void *file);         // 0x002548a8
extern int (*gBCountFreeMemoryFn)(int pool);       // 0x00257988
// 0x001083f0, the port's name eFlashScreen: eWaitUntilRenderingDone, the
// screen filled with 0x80bbggrr, and a busy wait of `seconds`. The text
// is not shown. Both Begins of unloading flash (0, 128, 0) for a second
// on a leak.
extern void (*gEFlashScreenFn)(int r, int g, int b, const char *why,
                               float seconds);
// ResetRenderEggs (0x0024bdc0), and 0x0024f700 on TheEasterEggs
// (0x0031d7e8), the port's name ClearTemporaryEasterEggs: every egg not
// kept (+52 of its 56 bytes) is turned off (+48). Not after an AI or
// replay demo.
extern void (*gResetRenderEggsFn)(void);
extern void (*gClearTemporaryEasterEggsFn)(void);

// The loading states'.
// eDuplicateSolid (0x00103bf0): a copy of the solid `from`, named `to`.
extern void (*gEDuplicateSolidFn)(const char *from, const char *to);
extern void (*gEDeleteAllDuplicatedSolidsFn)(void);       // 0x00103d58
// DemoModeReplay::LoadResourceFile on TheDemoModeReplay (0x0013f070).
extern void (*gDemoModeReplayLoadFn)(void);
// LoadSoundRegionsInGame (0x001ae798): the race's sound banks, and `done`
// with `param` once they are in.
extern void (*gLoadSoundRegionsInGameFn)(void (*done)(intptr_t),
                                         intptr_t param);
// The HUD's textures go through carloader.h's gLoadTexturesFromFileFn
// (TexturePack::LoadTexturesFromFile, 0x001acc98), on pHudTexturePack.

// The port's: a local wireless race holds every console at the end of
// its load until all have loaded (netrace.c, TASKS 37c). Part6 asks it
// first; nonzero holds the LOADING_TRACK screen up, and the hold's owner
// goes on with trackflow_go_racing. NULL holds nothing, as retail.
extern int (*gTrackFlowHoldRaceFn)(void);

// The port's: the race's view of the track (main.c, trackview.h) lets go
// of its meshes, textures and heap as the Begin of unloading the track
// starts, while the bundle it reads is still in. Next Race's unload goes
// on to the next race's load in the same pass of the flow, so nothing
// between them would. NULL does nothing, as retail.
extern void (*gTrackFlowViewUnloadFn)(void);

// ------------------------------------------------------------- the steps

// BeginGameFlowLoadingTrackCommon, 0x00168db8.
void BeginGameFlowLoadingTrackCommon(void);
// GameFlowLoadingTrackCommonPart1, 0x00168ac0: INGAMEB's callback.
void GameFlowLoadingTrackCommonPart1(intptr_t param);
// GameFlowLoadingTrackCommonPart2, 0x00168928: the car loader's.
void GameFlowLoadingTrackCommonPart2(void);

// LoadHudTextures, 0x00168c30. With one player, the gauges of the first
// driver still in the event, of drivers 0 and 1; then the third-person
// gauge in the units picked, whose load runs `done`.
void LoadHudTextures(void (*done)(intptr_t));

// BeginGameFlowLoadingTrackSpecific, 0x001690a0, and the six parts of its
// chain: 0x00169058, 0x00169048, 0x00169018, 0x00168f98, 0x00168f78 and
// 0x00168f28.
void BeginGameFlowLoadingTrackSpecific(void);
void GameFlowLoadingTrackSpecificPart1(intptr_t param);
void GameFlowLoadingTrackSpecificPart2(intptr_t param);
void GameFlowLoadingTrackSpecificPart3(intptr_t param);
void GameFlowLoadingTrackSpecificPart4(intptr_t param);
void GameFlowLoadingTrackSpecificPart5(intptr_t param);
void GameFlowLoadingTrackSpecificPart6(intptr_t param);

// Part6's own work, the screen down and RACING asked for: Part6's unless
// gTrackFlowHoldRaceFn held it, and then the hold's.
void trackflow_go_racing(void);

// EndGameFlowLoadingTrackSpecific, 0x00169168.
void EndGameFlowLoadingTrackSpecific(void);

// BeginGameFlowUnloadingTrackSpecific, 0x00169288.
void BeginGameFlowUnloadingTrackSpecific(void);

// BeginGameFlowUnloadingTrackCommon, 0x00168ea0.
void BeginGameFlowUnloadingTrackCommon(void);
