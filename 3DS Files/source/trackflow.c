// trackflow -- see trackflow.h.

#include "trackflow.h"

#include <stddef.h>

#include "bslotpool.h"
#include "collision.h"
#include "collisionbody.h"
#include "demodisc.h"
#include "esolid.h"
#include "eview.h"
#include "physcomp.h"
#include "scenery.h"
#include "topology.h"
#include "trackpath.h"
#include "trackroute.h"

int32_t      InGameFlag;                        // 0x00323628
TexturePack *pHudTexturePack;                   // 0x00323624
int32_t      WeHaveCheckedIfJR2ServerExists;    // 0x003234e4
BGameFlow   *gTrackFlowGameFlow;

void (*gInitSmokeablesFn)(void);
void (*gSkyLoaderFn)(void);
void (*gRainLoadFn)(void);
void (*gSunTrackLoaderFn)(void);
void (*gInitDebugTopologyFn)(void);
void (*gInitTrackMarkersFn)(void);
void (*gInitTrackRouteEditorFn)(void);
void (*gInitWorldObjectsFn)(void);
void (*gInitAnimatedDriverFn)(void);
void (*gInitAIPlansFn)(void);
RaceCoordinator *(*gNewRaceCoordinatorFn)(void);

void (*gSetFlailerScreenVisibilityFn)(uint32_t screen, int visibility);
void (*gDeleteRaceCoordinatorFn)(RaceCoordinator *rc, int flags);
void (*gUnloadAllTexturesFromFileFn)(TexturePack *p);
void (*gCloseAIPlansFn)(void);
void (*gCloseAnimatedDriverFn)(void);
void (*gCloseWorldObjectsFn)(void);
void (*gCloseTrackRouteEditorFn)(void);
void (*gCloseTrackMarkersFn)(void);
void (*gCloseDebugTopologyFn)(void);
void (*gSunTrackUnloaderFn)(void);
void (*gSkyUnloaderFn)(void);
void (*gRainUnloadFn)(void);
void (*gCloseSmokeablesFn)(void);
void *(*gFindResourceFileFn)(int type);
void (*gUnloadResourceFileFn)(void *file);
void (*gUnLoadSoundRegionsFn)(void);
void (*gDemoModeReplayUnloadFn)(void);
void (*gUnloadAllLanguagesFn)(void);
int (*gBIsAsyncDoneFn)(void *file);
int (*gBCountFreeMemoryFn)(int pool);

#define CALL(fn) do { if ((fn) != NULL) (fn)(); } while (0)

// ResourceFileType 3, the track's own: FindResourceFile hands them back one
// at a time until none is left.
#define TRACK_RESOURCE_FILE 3

// GameFlowState 8, where the Begin of unloading goes when nothing is
// pending.
#define UNLOADING_TRACK_COMMON 8

void EndGameFlowLoadingTrackSpecific(void)
{
    // `sw zero,-25520(gp)` ahead of the jal: the tables the track's
    // bundles dirtied are fixed up here, once, and not by each bundle.
    eDisableFixUpTables = 0;
    efix_up_tables();
    InGameFlag = 1;                     // the jal's delay slot

    init_collision();
    init_collision_body();
    init_contact();
    topotree_init_tree(&TheTopologyTree);
    CALL(gInitSmokeablesFn);
    InitPhysics(RaceParametersNumDriverInfo);
    CALL(gSkyLoaderFn);
    CALL(gRainLoadFn);
    CALL(gSunTrackLoaderFn);
    CALL(gInitDebugTopologyFn);
    CALL(gInitTrackMarkersFn);
    scenery_init_visible_zones();
    init_track_paths();

    // `xori a0,a0,1 ; sltiu v0,a0,1 ; sltu a0,zero,a0`: backward is exactly
    // 1, and anything else runs forward. The store is InitTrackRoutes'
    // delay slot, so the paths are reversed before the routes are made.
    TheTrackPathManager.ReverseTrackDirection =
        RaceParametersTrackDirection == TRACK_DIRECTION_BACKWARD;
    init_track_routes(RaceParametersTrackDirection != TRACK_DIRECTION_BACKWARD);

    CALL(gInitTrackRouteEditorFn);
    CALL(gInitWorldObjectsFn);
    CALL(gInitAnimatedDriverFn);
    WeHaveCheckedIfJR2ServerExists = 0; // InitAIPlans' delay slot
    CALL(gInitAIPlansFn);

    pRaceCoordinator = gNewRaceCoordinatorFn != NULL
                     ? gNewRaceCoordinatorFn() : NULL;
}

void BeginGameFlowUnloadingTrackSpecific(void)
{
    void *file;

    eDisableFixUpTables = 1;
    InGameFlag = 0;
    if (!TheDemoDiscManager.bActive && gSetFlailerScreenVisibilityFn != NULL)
        gSetFlailerScreenVisibilityFn(BGF_SCREEN_LOADING_TRACK, 0);
    CALL(gEWaitUntilRenderingDoneFn);

    // The pointer is cleared in UnloadAllTexturesFromFile's delay slot:
    // after the delete, before the HUD pack goes.
    if (pRaceCoordinator != NULL && gDeleteRaceCoordinatorFn != NULL)
        gDeleteRaceCoordinatorFn(pRaceCoordinator, 3);
    pRaceCoordinator = NULL;
    if (gUnloadAllTexturesFromFileFn != NULL)
        gUnloadAllTexturesFromFileFn(pHudTexturePack);

    CALL(gCloseAIPlansFn);
    CALL(gCloseAnimatedDriverFn);
    CALL(gCloseWorldObjectsFn);
    CALL(gCloseTrackRouteEditorFn);
    close_track_routes();
    scenery_close_visible_zones();
    CALL(gCloseTrackMarkersFn);
    CALL(gCloseDebugTopologyFn);
    CALL(gSunTrackUnloaderFn);
    CALL(gSkyUnloaderFn);
    CALL(gRainUnloadFn);
    ClosePhysics();
    CALL(gCloseSmokeablesFn);
    topotree_close_tree(&TheTopologyTree);
    close_track_paths();
    close_contact();
    close_collision_body();
    close_collision();

    // UnloadResourceFile takes the file off the list Find walks, so the
    // pair is both seams or neither: Find alone would spin.
    while (gFindResourceFileFn != NULL && gUnloadResourceFileFn != NULL
           && (file = gFindResourceFileFn(TRACK_RESOURCE_FILE)) != NULL)
        gUnloadResourceFileFn(file);

    CALL(gUnLoadSoundRegionsFn);
    CALL(gDemoModeReplayUnloadFn);
    CALL(gUnloadAllLanguagesFn);
    bCleanupAllExpandedSlotPools();

    // bIsAsyncDone(NULL): every queued read, not one file.
    while (gBIsAsyncDoneFn != NULL && !gBIsAsyncDoneFn(NULL))
        ;
    if (gBCountFreeMemoryFn != NULL)
        (void)gBCountFreeMemoryFn(16);

    if (gTrackFlowGameFlow != NULL) {
        BGameFlow *gf = gTrackFlowGameFlow;
        int pending = gf->pending;

        gf->skipFE = 0;
        bgf_change_state(gf, pending != 0 ? pending : UNLOADING_TRACK_COMMON,
                         0);
    }
}
