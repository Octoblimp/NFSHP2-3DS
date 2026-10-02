// trackflow -- see trackflow.h.

#include "trackflow.h"

#include <stddef.h>
#include <stdio.h>

#include "bchunk.h"
#include "bslotpool.h"
#include "car.h"
#include "carloader.h"
#include "cartypeinfo.h"
#include "collision.h"
#include "collisionbody.h"
#include "esolid.h"
#include "eview.h"
#include "hudtex.h"
#include "physcomp.h"
#include "racecoord.h"
#include "rain.h"
#include "resource.h"
#include "scenery.h"
#include "sky.h"
#include "sun.h"
#include "topology.h"
#include "trackpath.h"
#include "trackroute.h"

int32_t      InGameFlag;                            // 0x00330540
TexturePack *pHudTexturePack;                       // 0x0033053c
int32_t      WeHaveCheckedIfJR2ServerExists;        // 0x003303ec
int32_t      FreeMemoryBeforeLoadingTrackCommon;    // 0x0033052c
int32_t      FreeMemoryBeforeLoadingTrackSpecific;  // 0x00330530
int32_t      AnimatedDriverNeedsFixup;              // 0x00330570
int32_t      DemoModeReplayActiveFlag;              // 0x002f0960
BGameFlow   *gTrackFlowGameFlow;

void (*gInitSmokeablesFn)(void);
void (*gInitDebugTopologyFn)(void);
void (*gInitTrackMarkersFn)(void);
void (*gInitTrackRouteEditorFn)(void);
void (*gInitWorldObjectsFn)(void);
void (*gInitAnimatedDriverFn)(void);
void (*gInitAIPlansFn)(void);
void (*gSetRenderEggFromEasterEggsFn)(void);
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
void (*gCloseSmokeablesFn)(void);
void *(*gFindResourceFileFn)(int type);
void (*gUnloadResourceFileFn)(void *file);
void (*gUnLoadSoundRegionsFn)(void);
void (*gDemoModeReplayUnloadFn)(void);
int (*gBIsAsyncDoneFn)(void *file);
int (*gBCountFreeMemoryFn)(int pool);
void (*gEFlashScreenFn)(int r, int g, int b, const char *why, float seconds);
void (*gResetRenderEggsFn)(void);
void (*gClearTemporaryEasterEggsFn)(void);

void (*gEDuplicateSolidFn)(const char *from, const char *to);
void (*gEDeleteAllDuplicatedSolidsFn)(void);
void (*gDemoModeReplayLoadFn)(void);
void (*gLoadSoundRegionsInGameFn)(void (*done)(intptr_t), intptr_t param);

#define CALL(fn) do { if ((fn) != NULL) (fn)(); } while (0)

// bCountFreeMemory's pool: the main heap.
#define MAIN_POOL 16

// INGAMEB and TRACKB: hot-chunkable and LZ-compressed.
#define BUNDLE_FLAGS \
    (RESOURCE_FILE_FLAG_HOTCHUNKABLE | RESOURCE_FILE_FLAG_LZCOMPRESSED)

// ------------------------------------------------------------- the helpers

static int32_t count_free_memory(void)
{
    return gBCountFreeMemoryFn != NULL ? gBCountFreeMemoryFn(MAIN_POOL) : 0;
}

// SkipFE, gp-23220.
static int skip_fe(void)
{
    return gTrackFlowGameFlow != NULL && gTrackFlowGameFlow->skipFE != 0;
}

// ChangeGameFlow(state, NONE).
static void change_game_flow(int state)
{
    if (gTrackFlowGameFlow != NULL)
        bgf_change_state(gTrackFlowGameFlow, state, BGF_NONE);
}

static void set_loading_screen(int visibility)
{
    // Retail picks the demo disc's own screen when bActive is set.
    if (gSetFlailerScreenVisibilityFn != NULL)
        gSetFlailerScreenVisibilityFn(BGF_SCREEN_LOADING_TRACK, visibility);
}

// The leak check that ends both Begins of unloading.
static void check_for_leak(int32_t before, const char *why)
{
    if (count_free_memory() != before && gEFlashScreenFn != NULL)
        gEFlashScreenFn(0, 128, 0, why, 1.0f);
}

static void duplicate_solid(const char *from, const char *to)
{
    if (gEDuplicateSolidFn != NULL)
        gEDuplicateSolidFn(from, to);
}

static void load_hud_texture(uint32_t *hash, void (*done)(intptr_t))
{
    if (gLoadTexturesFromFileFn != NULL)
        gLoadTexturesFromFileFn(pHudTexturePack, hash, 1, done, 0);
    else if (done != NULL)
        done(0);
}

// ------------------------------------------------- loading, the common part

void BeginGameFlowLoadingTrackCommon(void)
{
    ResourceFile *rf;

    FreeMemoryBeforeLoadingTrackCommon = count_free_memory();
    eDisableFixUpTables = 1;
    if (!skip_fe())
        set_loading_screen(FLAILER_SCREEN_VISIBLE);

    // INGAMEA is 0 bytes on the disc, so it loads as nothing, but it is
    // waited for before INGAMEB is asked for.
    load_resource_file("GLOBAL\\INGAMEA.BUN", RESOURCE_FILE_INGAME, 0, NULL,
                       0);
    AnimatedDriverNeedsFixup = 1;
    while (!is_resource_loading_complete())
        service_resource_loading();

    rf = load_resource_file("GLOBAL\\INGAMEB.LZC", RESOURCE_FILE_INGAME,
                            BUNDLE_FLAGS, GameFlowLoadingTrackCommonPart1, 0);
    change_filename_for_hot_chunking(rf, "GLOBAL\\INGAMEB.BUN");
}

void GameFlowLoadingTrackCommonPart1(intptr_t param)
{
    int32_t i;

    (void)param;
    TheCarLoader.InFrontEndFlag = 0;
    TheCarLoader.RoundRobinFlag = 0;

    // The cars that cannot be vertex-damaged first. A traffic car is
    // loaded with no skin of its own (-1), and its InstanceIndex is 0
    // however many there are: traffic shares one set of solids.
    for (i = 0; i < RaceParametersNumDriverInfo; i++) {
        DriverInfo *di = race_parameters_get_driver_info(i);
        RideInfo *ri = &di->CurrentRideInfo;
        const CarTypeInfo *ct;
        int8_t skin;
        int n;

        if (ri->CanBeVertexDamaged)
            continue;
        ct = cartypeinfo_get(ri->Type);
        skin = ri->SkinNumber;
        if (ct->UsageType == CAR_USAGE_TYPE_TRAFFIC)
            ri->SkinNumber = -1;
        n = carloader_load(&TheCarLoader, ri);
        ri->InstanceIndex = ct->UsageType != CAR_USAGE_TYPE_TRAFFIC
                          ? (int8_t)n : 0;
        ri->SkinNumber = skin;
    }
    for (i = 0; i < RaceParametersNumDriverInfo; i++) {
        RideInfo *ri = &race_parameters_get_driver_info(i)->CurrentRideInfo;

        if (ri->CanBeVertexDamaged)
            ri->InstanceIndex = (int8_t)carloader_load(&TheCarLoader, ri);
    }
    carloader_begin_loading(&TheCarLoader, GameFlowLoadingTrackCommonPart2);
}

void GameFlowLoadingTrackCommonPart2(void)
{
    // Retail's two buffers are 32 bytes, and a name past that runs over its
    // stack; the disc's longest base model name, 11 letters, leaves
    // "%s_SCUFFS%d" room. These hold what any 31-letter name makes.
    char from[48], to[48];
    int32_t i;

    // The first instance of a car draws with the solids its bundle loaded;
    // each further one gets copies, numbered by its InstanceIndex: the two
    // halves a vertex-damageable car deforms, and every car's scuffs.
    for (i = 0; i < RaceParametersNumDriverInfo; i++) {
        const RideInfo *ri =
            &race_parameters_get_driver_info(i)->CurrentRideInfo;
        const char *base = cartypeinfo_get(ri->Type)->BaseModelName;
        int inst = ri->InstanceIndex;

        if (inst <= 0)
            continue;
        if (ri->CanBeVertexDamaged) {
            int c;

            for (c = 'A'; c < 'C'; c++) {
                snprintf(from, sizeof from, "%s_%c", base, c);
                snprintf(to, sizeof to, "%s_%c%d", base, c, inst);
                duplicate_solid(from, to);
            }
        }
        snprintf(from, sizeof from, "%s_SCUFFS", base);
        snprintf(to, sizeof to, "%s_SCUFFS%d", base, inst);
        duplicate_solid(from, to);
    }
    change_game_flow(BGF_LOADING_TRACK_SPECIFIC);
}

// --------------------------------------------------------------- the HUD

void LoadHudTextures(void (*done)(intptr_t))
{
    int32_t units = RaceParametersGlobalDisplaySettings.Units;
    // One word each, as retail has them: the pack keeps the pointer only
    // for the call.
    uint32_t speedo, shadow, third, tach, gauge;

    if (RaceParametersNumPlayerCars == 1) {
        DriverInfo *di = race_parameters_get_driver_info_by_driver_number(0);

        // Driver 0 knocked out of the event: driver 1's gauges.
        if (di == NULL || di->EliminatedRank > 0)
            di = race_parameters_get_driver_info_by_driver_number(1);
        if (di != NULL && di->EliminatedRank <= 0) {
            tLoadableHudTextures t;

            ChooseLoadableTextures(di->CurrentRideInfo.Type, units, &t);
            speedo = t.Speedo;
            load_hud_texture(&speedo, NULL);
            shadow = t.Shadow;
            load_hud_texture(&shadow, NULL);
            third = t.ThirdPerson;
            load_hud_texture(&third, NULL);
            if (t.Tach != 0) {
                tach = t.Tach;
                load_hud_texture(&tach, NULL);
            }
        }
    }
    gauge = bchunk_hash(units == UNITS_KPH ? "3RDPERSONGAUGE_KMH"
                                           : "3RDPERSONGAUGE_MPH");
    load_hud_texture(&gauge, done);
}

// ----------------------------------------------- loading, the track's part

void BeginGameFlowLoadingTrackSpecific(void)
{
    char name[64];
    int32_t track = RaceParametersTrackNumber;
    ResourceFile *rf;

    FreeMemoryBeforeLoadingTrackSpecific = count_free_memory();
    eDisableFixUpTables = 1;
    snprintf(name, sizeof name, "TRACKS\\TRACKA%d.BUN", (int)track);
    load_resource_file(name, RESOURCE_FILE_TRACK, 0, NULL, 0);
    snprintf(name, sizeof name, "TRACKS\\TRACKB%d.LZC", (int)track);
    rf = load_resource_file(name, RESOURCE_FILE_TRACK, BUNDLE_FLAGS,
                            GameFlowLoadingTrackSpecificPart1, 0);
    snprintf(name, sizeof name, "TRACKS\\TRACKB%d.BUN", (int)track);
    change_filename_for_hot_chunking(rf, name);
}

void GameFlowLoadingTrackSpecificPart1(intptr_t param)
{
    (void)param;
    if (gTrackFlowGameFlow != NULL)
        bgf_load_current_speech(gTrackFlowGameFlow);
    if (DemoModeReplayActiveFlag)
        CALL(gDemoModeReplayLoadFn);
    if (gLoadSoundRegionsInGameFn != NULL)
        gLoadSoundRegionsInGameFn(GameFlowLoadingTrackSpecificPart2, 0);
    else
        GameFlowLoadingTrackSpecificPart2(0);
}

void GameFlowLoadingTrackSpecificPart2(intptr_t param)
{
    (void)param;
    LoadHudTextures(GameFlowLoadingTrackSpecificPart3);
}

void GameFlowLoadingTrackSpecificPart3(intptr_t param)
{
    (void)param;
    // The cars' intro animations, unless the race skips the frontend.
    if (!skip_fe())
        load_resource_file("GLOBAL\\PRERACEANIM.LZC", RESOURCE_FILE_TRACK,
                           RESOURCE_FILE_FLAG_LZCOMPRESSED,
                           GameFlowLoadingTrackSpecificPart4, 0);
    else
        GameFlowLoadingTrackSpecificPart4(0);
}

void GameFlowLoadingTrackSpecificPart4(intptr_t param)
{
    char name[64];
    int32_t track = RaceParametersTrackNumber;

    (void)param;
    snprintf(name, sizeof name, "TRACKS\\TEX%dTRACK.BIN", (int)track);
    load_resource_file(name, RESOURCE_FILE_TRACK,
                       RESOURCE_FILE_FLAG_HOTCHUNKABLE, NULL, 0);
    snprintf(name, sizeof name, "TRACKS\\TEX%dLOCATION.BIN", (int)track);
    load_resource_file(name, RESOURCE_FILE_TRACK,
                       RESOURCE_FILE_FLAG_HOTCHUNKABLE,
                       GameFlowLoadingTrackSpecificPart5, 0);
}

void GameFlowLoadingTrackSpecificPart5(intptr_t param)
{
    (void)param;
    load_resource_file("GLOBAL\\DRIVTEX.BIN", RESOURCE_FILE_TRACK, 0,
                       GameFlowLoadingTrackSpecificPart6, 0);
}

void GameFlowLoadingTrackSpecificPart6(intptr_t param)
{
    (void)param;
    set_loading_screen(FLAILER_SCREEN_INVISIBLE);
    change_game_flow(BGF_RACING);
}

void EndGameFlowLoadingTrackSpecific(void)
{
    // `sw zero,-24944(gp)` ahead of the jal: the tables the track's
    // bundles dirtied are fixed up here, once, and not by each bundle.
    eDisableFixUpTables = 0;
    efix_up_tables();
    InGameFlag = 1;                     // the jal's delay slot

    init_collision();
    init_collision_body();
    init_contact();
    topotree_init_tree(&TheTopologyTree);
    CALL(gInitSmokeablesFn);
    // Retail's InitPhysics takes no argument and reads NumDriverInfo
    // itself; the port's is handed it.
    InitPhysics(RaceParametersNumDriverInfo);
    SkyLoader();
    rain_Load();
    SunTrackLoader();
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

    if (!RaceParametersAIDemoMode && !RaceParametersReplayDemoMode)
        CALL(gSetRenderEggFromEasterEggsFn);
    pRaceCoordinator = gNewRaceCoordinatorFn != NULL
                     ? gNewRaceCoordinatorFn() : NULL;
}

// --------------------------------------------------------------- unloading

void BeginGameFlowUnloadingTrackSpecific(void)
{
    void *file;

    eDisableFixUpTables = 1;
    InGameFlag = 0;
    set_loading_screen(FLAILER_SCREEN_VISIBLE);
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
    SunTrackUnloader();
    SkyUnloader();
    rain_Unload();
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
           && (file = gFindResourceFileFn(RESOURCE_FILE_TRACK)) != NULL)
        gUnloadResourceFileFn(file);

    CALL(gUnLoadSoundRegionsFn);
    CALL(gDemoModeReplayUnloadFn);
    if (gTrackFlowGameFlow != NULL)
        bgf_unload_current_speech(gTrackFlowGameFlow);
    bCleanupAllExpandedSlotPools();

    // bIsAsyncDone(NULL): every queued read, not one file.
    while (gBIsAsyncDoneFn != NULL && !gBIsAsyncDoneFn(NULL))
        ;
    check_for_leak(FreeMemoryBeforeLoadingTrackSpecific,
                   "Memory Leak - Track Specific");

    if (gTrackFlowGameFlow != NULL) {
        BGameFlow *gf = gTrackFlowGameFlow;
        int pending = gf->pending;

        gf->skipFE = 0;
        bgf_change_state(gf, pending != BGF_NONE ? pending
                                                 : BGF_UNLOADING_TRACK_COMMON,
                         BGF_NONE);
    }

    // The eggs a race turned on for itself go; an AI or replay demo left
    // them alone.
    if (!RaceParametersAIDemoMode && !RaceParametersReplayDemoMode) {
        CALL(gResetRenderEggsFn);
        CALL(gClearTemporaryEasterEggsFn);
    }
}

void BeginGameFlowUnloadingTrackCommon(void)
{
    void *file;

    while (gFindResourceFileFn != NULL && gUnloadResourceFileFn != NULL
           && (file = gFindResourceFileFn(RESOURCE_FILE_INGAME)) != NULL)
        gUnloadResourceFileFn(file);
    CALL(gEDeleteAllDuplicatedSolidsFn);
    carloader_unload_everything(&TheCarLoader);
    check_for_leak(FreeMemoryBeforeLoadingTrackCommon,
                   "Memory Leak - Track Common");
    change_game_flow(BGF_LOADING_FRONTEND);
}
