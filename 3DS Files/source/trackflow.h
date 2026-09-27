#pragma once
#include <stdint.h>

#include "gameflow.h"
#include "race.h"
#include "texturepack.h"

// The two game-flow steps that bracket a race's track: the End of
// LOADING_TRACK_SPECIFIC, which starts every per-track system once the
// track's bundles are in, and the Begin of UNLOADING_TRACK_SPECIFIC, which
// closes them again. Decompiled in docs/formats/track-flow.md.
//
//   EndGameFlowLoadingTrackSpecific      0x001645e8
//   BeginGameFlowUnloadingTrackSpecific  0x001646e0
//
// Both are straight lines of calls. The callees the port has are called
// directly; the rest are seams below, and a NULL seam does nothing (a seam
// that returns a pointer gives NULL, and a NULL gBIsAsyncDoneFn is "done").
// tools/trackflow_check.py runs both functions out of the image with every
// callee stubbed and diffs the calls, their arguments and the globals they
// leave behind against these.

// ------------------------------------------------------------- the globals

// gp-21960, 0x00323628. 1 from the End of loading to the Begin of
// unloading: a race's track is up.
extern int32_t InGameFlag;

// gp-21964, 0x00323624. LoadHudTextures' TexturePack (TRACKS\HUDTEX.BIN).
// NULL in the port, which does not load the HUD pack yet.
extern TexturePack *pHudTexturePack;

// gp-22284, 0x003234e4. The End of loading clears it, so the network code
// looks for the JR2 server again the next race.
extern int32_t WeHaveCheckedIfJR2ServerExists;

// The flow whose PendingGameFlowState the Begin of unloading reads and
// whose SkipFE it clears, and which it hands to ChangeGameFlow. NULL skips
// all three -- the viewer, which runs these two outside the flow's states.
extern BGameFlow *gTrackFlowGameFlow;

// ----------------------------------------------------------------- seams

// The End of loading, in call order.
extern void (*gInitSmokeablesFn)(void);            // 0x0020bb50
extern void (*gInitDebugTopologyFn)(void);         // 0x001f18f0
extern void (*gInitTrackMarkersFn)(void);          // 0x001b4338
extern void (*gInitTrackRouteEditorFn)(void);      // 0x001bbc78
extern void (*gInitWorldObjectsFn)(void);          // 0x001c3778
extern void (*gInitAnimatedDriverFn)(void);        // 0x0019ee50
extern void (*gInitAIPlansFn)(void);               // 0x001bbf00
// `new RaceCoordinator`: bMalloc(144, "RaceCoordinator", 0, 16) and the
// ctor (0x00147170). A NULL seam leaves pRaceCoordinator NULL.
extern RaceCoordinator *(*gNewRaceCoordinatorFn)(void);

// The Begin of unloading, in call order.
extern void (*gSetFlailerScreenVisibilityFn)(uint32_t screen,
                                             int visibility); // 0x0014a3b8
// RaceCoordinator's deleting dtor (0x00147288), with the 3 that frees it.
extern void (*gDeleteRaceCoordinatorFn)(RaceCoordinator *rc, int flags);
extern void (*gUnloadAllTexturesFromFileFn)(TexturePack *p); // 0x001a2850
extern void (*gCloseAIPlansFn)(void);              // 0x001bbf30
extern void (*gCloseAnimatedDriverFn)(void);       // 0x0019f070
extern void (*gCloseWorldObjectsFn)(void);         // 0x001c37a8
extern void (*gCloseTrackRouteEditorFn)(void);     // 0x001bbcb0
extern void (*gCloseTrackMarkersFn)(void);         // 0x001b43a0
extern void (*gCloseDebugTopologyFn)(void);        // 0x001f18f8
extern void (*gCloseSmokeablesFn)(void);           // 0x0020bb58
// FindResourceFile (0x0018fe88) and UnloadResourceFile (0x0018fd20).
extern void *(*gFindResourceFileFn)(int type);
extern void (*gUnloadResourceFileFn)(void *file);
extern void (*gUnLoadSoundRegionsFn)(void);        // 0x001a5ef0
// DemoModeReplay::UnloadResourceFile on TheDemoModeReplay (0x002e89b0).
extern void (*gDemoModeReplayUnloadFn)(void);      // 0x0013cfd0
// LanguageManager::UnloadAllLanguages on TheLanguageManager (0x00313c90).
extern void (*gUnloadAllLanguagesFn)(void);        // 0x0020b010
extern int (*gBIsAsyncDoneFn)(void *file);         // 0x0023c670
extern int (*gBCountFreeMemoryFn)(int pool);       // 0x0023f280

// ------------------------------------------------------------- the steps

// EndGameFlowLoadingTrackSpecific, 0x001645e8.
void EndGameFlowLoadingTrackSpecific(void);

// BeginGameFlowUnloadingTrackSpecific, 0x001646e0.
void BeginGameFlowUnloadingTrackSpecific(void);
