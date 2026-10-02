// Harness for tools/trackflow_check.py: runs the checker's scenarios on
// trackflow.c and hudtex.c and prints what the model prints for the retail
// image. Every callee is a stub here -- the ported ones by name, the rest
// through the seams -- and each logs its name, its arguments and the
// globals the steps write, at the moment of the call. The loads queue
// their callbacks, and D runs the oldest. See the checker's docstring.
//
//     trackflow_test scenarios.txt > out.txt
//
// Scenario lines:
//   R <hex>               the 64 car records, 1376 bytes each, widened to
//                         the host's CarTypeInfo and kept as the pristine set
//   B <n>                 scenario n: every global, stub and driver back to
//                         0, nothing pending, the pristine records
//   A <type> <off> <hex>  bytes into a record, below pCarSpecs
//   G <name> <value>      a global or a stub's setting (see set_global)
//   d <num> <rank> <type> <inst> <skin> <dash> <vd>
//                         one more driver; NumDriverInfo is the count
//   X <step>              C S E U V: the five state functions; p q: the
//                         common Parts 1 and 2; 1..6: the track's Parts;
//                         H: LoadHudTextures with testcb
//   D                     the oldest queued callback runs
//   T <car> <units>       ChooseLoadableTextures
// Every line but R and B is echoed as "> " and its first 40 characters,
// and X and D print the state after.

#include <stdarg.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bslotpool.h"
#include "car.h"
#include "carloader.h"
#include "cartypeinfo.h"
#include "collision.h"
#include "collisionbody.h"
#include "esolid.h"
#include "eview.h"
#include "gameflow.h"
#include "hudtex.h"
#include "physcomp.h"
#include "race.h"
#include "racecoord.h"
#include "rain.h"
#include "resource.h"
#include "scenery.h"
#include "sky.h"
#include "sun.h"
#include "topology.h"
#include "trackflow.h"
#include "trackpath.h"
#include "trackroute.h"

#define REC_SIZE  1376
#define NUM_TYPES 64
#define MAXDRV    16
#define MAXPEND   32
#define MAXRF     64
#define MAXFILES  16

// ------------------------------------------ the globals trackflow.c reads

int32_t                eDisableFixUpTables;
TopologyTree           TheTopologyTree;
TrackPathManager       TheTrackPathManager;
RaceParameters         TheRaceParameters;
RaceCoordinator       *pRaceCoordinator;
void (*gEWaitUntilRenderingDoneFn)(void);
CarLoader              TheCarLoader;
void (*gLoadTexturesFromFileFn)(TexturePack *p, uint32_t *hashes, int n,
                                CarLoaderDoneFn done, intptr_t param);

// ------------------------------------------------------------ the objects

static BGameFlow    flow;
static char         rc0_obj[144], rc_obj[144];
static TexturePack  hud_obj;
static ResourceFile rf_obj[MAXRF];
static int          files_obj[2][MAXFILES + 1];
static DriverInfo   drivers[MAXDRV];
static int          ndrivers;

static uint8_t     *pristine, *recmem;

// The stubs' settings, from G.
static int lbase, mem0, mstep, nload, nfiles[2], nbusy, null_seams;
// And their state.
static int counts[NUM_TYPES], nmem, nrf, nfound[2];

// The queue of callbacks D runs: a load's, with its parameter, or the car
// loader's, which takes none.
static struct {
    void (*fn)(intptr_t);
    void (*vfn)(void);
    intptr_t param;
} pend[MAXPEND];
static int npend;

static void testcb(intptr_t param);

// ------------------------------------------------------------- the labels

static const char *label(const void *p)
{
    static char buf[8][40];
    static int k;
    char *b = buf[k++ & 7];
    int i;

    if (p == NULL)
        return "null";
    if (p == rc0_obj)
        return "rc0";
    if (p == rc_obj)
        return "rc";
    if (p == &hud_obj)
        return "hud";
    if (p == &TheTopologyTree)
        return "TT";
    if (p == &TheCarLoader)
        return "L0";
    if (p >= (const void *)rf_obj && p < (const void *)(rf_obj + MAXRF)) {
        snprintf(b, 40, "rf%d", (int)((const ResourceFile *)p - rf_obj));
        return b;
    }
    for (i = 0; i < 2; i++)
        if (p >= (const void *)files_obj[i]
            && p < (const void *)(files_obj[i] + MAXFILES + 1)) {
            snprintf(b, 40, "f%d.%d", i + 2,
                     (int)((const int *)p - files_obj[i]));
            return b;
        }
    for (i = 0; i < MAXDRV; i++) {
        if (p == &drivers[i]) {
            snprintf(b, 40, "d%d", i);
            return b;
        }
        if (p == &drivers[i].CurrentRideInfo) {
            snprintf(b, 40, "r%d", i);
            return b;
        }
    }
    snprintf(b, 40, "x%p", p);
    return b;
}

static const char *cblabel(void (*fn)(intptr_t))
{
    if (fn == NULL)
        return "null";
    if (fn == GameFlowLoadingTrackCommonPart1)
        return "P1C";
    if (fn == GameFlowLoadingTrackSpecificPart1)
        return "P1";
    if (fn == GameFlowLoadingTrackSpecificPart2)
        return "P2";
    if (fn == GameFlowLoadingTrackSpecificPart3)
        return "P3";
    if (fn == GameFlowLoadingTrackSpecificPart4)
        return "P4";
    if (fn == GameFlowLoadingTrackSpecificPart5)
        return "P5";
    if (fn == GameFlowLoadingTrackSpecificPart6)
        return "P6";
    if (fn == testcb)
        return "testcb";
    return "?";
}

static const char *vcblabel(void (*fn)(void))
{
    if (fn == NULL)
        return "null";
    if (fn == GameFlowLoadingTrackCommonPart2)
        return "P2C";
    return "?";
}

static void snap(void)
{
    printf(" | ig=%d dft=%d rev=%d jr2=%d rc=%s sfe=%d fc=%d fs=%d adf=%d"
           " fe=%d rr=%d want=%d pend=%d\n", (int)InGameFlag,
           (int)eDisableFixUpTables,
           (int)TheTrackPathManager.ReverseTrackDirection,
           (int)WeHaveCheckedIfJR2ServerExists, label(pRaceCoordinator),
           flow.skipFE, (int)FreeMemoryBeforeLoadingTrackCommon,
           (int)FreeMemoryBeforeLoadingTrackSpecific,
           (int)AnimatedDriverNeedsFixup, (int)TheCarLoader.InFrontEndFlag,
           (int)TheCarLoader.RoundRobinFlag, flow.desired, flow.pending);
}

static void say(const char *fmt, ...)
{
    va_list ap;

    printf("  ");
    va_start(ap, fmt);
    vprintf(fmt, ap);
    va_end(ap);
    snap();
}

static void print_state(void)
{
    int i;

    printf("st");
    snap();
    printf("drv");
    for (i = 0; i < ndrivers; i++)
        printf(" %d/%d", drivers[i].CurrentRideInfo.InstanceIndex,
               drivers[i].CurrentRideInfo.SkinNumber);
    printf("\n");
}

static void queue(void (*fn)(intptr_t), void (*vfn)(void), intptr_t param)
{
    if (npend == MAXPEND) {
        printf("queue full\n");
        exit(7);
    }
    pend[npend].fn = fn;
    pend[npend].vfn = vfn;
    pend[npend].param = param;
    npend++;
}

static void testcb(intptr_t param)
{
    say("testcb %d", (int)param);
}

// ------------------------------------------------------ the ported callees

void efix_up_tables(void) { say("eFixUpTables"); }
void init_collision(void) { say("InitCollision"); }
void init_collision_body(void) { say("InitCollisionBody"); }
void init_contact(void) { say("InitContact"); }
void topotree_init_tree(TopologyTree *t) { say("InitTree %s", label(t)); }
void InitPhysics(int32_t n) { say("InitPhysics %d", (int)n); }
void SkyLoader(void) { say("SkyLoader"); }
void rain_Load(void) { say("rain_Load"); }
void rain_Unload(void) { say("rain_Unload"); }
void SunTrackLoader(void) { say("SunTrackLoader"); }
void SunTrackUnloader(void) { say("SunTrackUnloader"); }
void SkyUnloader(void) { say("SkyUnloader"); }
void scenery_init_visible_zones(void) { say("InitVisibleZones"); }
void init_track_paths(void) { say("InitTrackPaths"); }
void init_track_routes(int forward) { say("InitTrackRoutes %d", forward); }
void close_track_routes(void) { say("CloseTrackRoutes"); }
void scenery_close_visible_zones(void) { say("CloseVisibleZones"); }
void ClosePhysics(void) { say("ClosePhysics"); }
void topotree_close_tree(TopologyTree *t) { say("CloseTree %s", label(t)); }
void close_track_paths(void) { say("CloseTrackPaths"); }
void close_contact(void) { say("CloseContact"); }
void close_collision_body(void) { say("CloseCollisionBody"); }
void close_collision(void) { say("CloseCollision"); }
void bCleanupAllExpandedSlotPools(void) { say("CleanupExpandedSlotPools"); }

void bgf_change_state(BGameFlow *gf, int desired, int pending)
{
    gf->desired = desired;
    gf->pending = pending;
    say("ChangeGameFlow %d %d%s", desired, pending,
        gf == &flow ? "" : " (not the flow)");
}

void bgf_load_current_speech(BGameFlow *gf)
{
    say("LoadSpeech%s", gf == &flow ? "" : " (not the flow)");
}

void bgf_unload_current_speech(BGameFlow *gf)
{
    say("UnloadSpeech%s", gf == &flow ? "" : " (not the flow)");
}

struct DriverInfo *race_parameters_get_driver_info(int32_t i)
{
    return &RaceParametersDriverInfo[i];
}

struct DriverInfo *race_parameters_get_driver_info_by_driver_number(
    int32_t number)
{
    DriverInfo *d = NULL;
    int32_t i;

    for (i = 0; i < RaceParametersNumDriverInfo; i++)
        if (RaceParametersDriverInfo[i].UniqueDriverNumber == number) {
            d = &RaceParametersDriverInfo[i];
            break;
        }
    say("GetDriverInfoByDriverNumber %d -> %s", (int)number, label(d));
    return d;
}

ResourceFile *load_resource_file(const char *name, int32_t type,
                                 int32_t flags, ResourceFileCallback cb,
                                 intptr_t param)
{
    ResourceFile *rf;

    if (nrf == MAXRF)
        exit(8);
    rf = &rf_obj[nrf++];
    say("LoadResourceFile %s %d %d %s %d -> %s", name, (int)type, (int)flags,
        cblabel(cb), (int)param, label(rf));
    if (cb != NULL)
        queue(cb, NULL, param);
    return rf;
}

int32_t service_resource_loading(void)
{
    say("ServiceResourceLoading");
    return 0;
}

int32_t is_resource_loading_complete(void)
{
    int r = nload <= 0;

    if (nload > 0)
        nload--;
    say("IsResourceLoadingComplete -> %d", r);
    return r;
}

void change_filename_for_hot_chunking(ResourceFile *rf, const char *name)
{
    say("ChangeFilenameForHotChunking %s %s", label(rf), name);
}

int carloader_load(CarLoader *cl, const RideInfo *ri)
{
    int t = ri->Type;
    int n = (int8_t)(lbase + (t >= 0 && t < NUM_TYPES ? counts[t]++ : 0));

    say("Load %s %s type=%d inst=%d skin=%d dash=%d vd=%d -> %d", label(cl),
        label(ri), (int)ri->Type, ri->InstanceIndex, ri->SkinNumber,
        ri->HasDash, ri->CanBeVertexDamaged, n);
    return n;
}

void carloader_begin_loading(CarLoader *cl, void (*callback)(void))
{
    say("BeginLoading %s %s", label(cl), vcblabel(callback));
    if (callback != NULL)
        queue(NULL, callback, 0);
}

void carloader_unload_everything(CarLoader *cl)
{
    say("UnloadEverything %s", label(cl));
}

// --------------------------------------------------------------- the seams

#define SEAM(fn, name) static void fn(void) { say(name); }
SEAM(s_smokeables, "InitSmokeables")
SEAM(s_debugtopo, "InitDebugTopology")
SEAM(s_markers, "InitTrackMarkers")
SEAM(s_routeeditor, "InitTrackRouteEditor")
SEAM(s_worldobjects, "InitWorldObjects")
SEAM(s_animdriver, "InitAnimatedDriver")
SEAM(s_aiplans, "InitAIPlans")
SEAM(s_egg, "SetRenderEggFromEasterEggs")
SEAM(s_wait, "eWaitUntilRenderingDone")
SEAM(s_closeaiplans, "CloseAIPlans")
SEAM(s_closeanimdriver, "CloseAnimatedDriver")
SEAM(s_closeworldobjects, "CloseWorldObjects")
SEAM(s_closerouteeditor, "CloseTrackRouteEditor")
SEAM(s_closemarkers, "CloseTrackMarkers")
SEAM(s_closedebugtopo, "CloseDebugTopology")
SEAM(s_closesmokeables, "CloseSmokeables")
SEAM(s_soundregions, "UnLoadSoundRegions")
SEAM(s_demoreplay, "DemoModeReplayUnload")
SEAM(s_demoreplayload, "DemoModeReplayLoad")
SEAM(s_reseteggs, "ResetRenderEggs")
SEAM(s_cleareggs, "ClearTemporaryEasterEggs")
SEAM(s_deletedups, "eDeleteAllDuplicatedSolids")

// bMalloc and the ctor: two calls in the image, one seam here.
static RaceCoordinator *s_new_rc(void)
{
    say("bMalloc 144 RaceCoordinator 0 16");
    say("RaceCoordinator");
    return (RaceCoordinator *)(void *)rc_obj;
}

static void s_flailer(uint32_t screen, int vis)
{
    say("SetFlailerScreenVisibility %08x %d", (unsigned)screen, vis);
}

static void s_delete_rc(RaceCoordinator *rc, int flags)
{
    say("~RaceCoordinator %s %d", label(rc), flags);
}

static void s_hudunload(TexturePack *p)
{
    say("UnloadAllTexturesFromFile %s", label(p));
}

static void *s_find(int type)
{
    void *f = NULL;
    int k = type - 2;

    if ((k == 0 || k == 1) && nfound[k] < nfiles[k])
        f = &files_obj[k][++nfound[k]];
    say("FindResourceFile %d -> %s", type, label(f));
    return f;
}

static void s_unloadrf(void *f) { say("UnloadResourceFile %s", label(f)); }

static int s_async(void *f)
{
    int r = nbusy <= 0;

    if (nbusy > 0)
        nbusy--;
    say("bIsAsyncDone %s -> %d", label(f), r);
    return r;
}

static int s_countfree(int pool)
{
    int v = mem0 + mstep * nmem++;

    say("bCountFreeMemory %d -> %d", pool, v);
    return v;
}

static void s_flash(int r, int g, int b, const char *why, float seconds)
{
    say("eFlashScreen %d %d %d %s %g", r, g, b, why, (double)seconds);
}

static void s_dup(const char *from, const char *to)
{
    say("eDuplicateSolid %s %s", from, to);
}

static void s_soundregionsin(void (*done)(intptr_t), intptr_t param)
{
    say("LoadSoundRegionsInGame %s %d", cblabel(done), (int)param);
    if (done != NULL)
        queue(done, NULL, param);
}

static void s_loadtex(TexturePack *p, uint32_t *hashes, int n,
                      CarLoaderDoneFn done, intptr_t param)
{
    int i;

    printf("  LoadTexturesFromFile %s %d %s %d:", label(p), n, cblabel(done),
           (int)param);
    for (i = 0; i < n; i++)
        printf(" %08x", (unsigned)hashes[i]);
    snap();
    if (done != NULL)
        queue(done, NULL, param);
}

static void set_seams(int on)
{
    gInitSmokeablesFn = on ? s_smokeables : NULL;
    gInitDebugTopologyFn = on ? s_debugtopo : NULL;
    gInitTrackMarkersFn = on ? s_markers : NULL;
    gInitTrackRouteEditorFn = on ? s_routeeditor : NULL;
    gInitWorldObjectsFn = on ? s_worldobjects : NULL;
    gInitAnimatedDriverFn = on ? s_animdriver : NULL;
    gInitAIPlansFn = on ? s_aiplans : NULL;
    gSetRenderEggFromEasterEggsFn = on ? s_egg : NULL;
    gNewRaceCoordinatorFn = on ? s_new_rc : NULL;
    gSetFlailerScreenVisibilityFn = on ? s_flailer : NULL;
    gEWaitUntilRenderingDoneFn = on ? s_wait : NULL;
    gDeleteRaceCoordinatorFn = on ? s_delete_rc : NULL;
    gUnloadAllTexturesFromFileFn = on ? s_hudunload : NULL;
    gCloseAIPlansFn = on ? s_closeaiplans : NULL;
    gCloseAnimatedDriverFn = on ? s_closeanimdriver : NULL;
    gCloseWorldObjectsFn = on ? s_closeworldobjects : NULL;
    gCloseTrackRouteEditorFn = on ? s_closerouteeditor : NULL;
    gCloseTrackMarkersFn = on ? s_closemarkers : NULL;
    gCloseDebugTopologyFn = on ? s_closedebugtopo : NULL;
    gCloseSmokeablesFn = on ? s_closesmokeables : NULL;
    gFindResourceFileFn = on ? s_find : NULL;
    gUnloadResourceFileFn = on ? s_unloadrf : NULL;
    gUnLoadSoundRegionsFn = on ? s_soundregions : NULL;
    gDemoModeReplayUnloadFn = on ? s_demoreplay : NULL;
    gBIsAsyncDoneFn = on ? s_async : NULL;
    gBCountFreeMemoryFn = on ? s_countfree : NULL;
    gEFlashScreenFn = on ? s_flash : NULL;
    gResetRenderEggsFn = on ? s_reseteggs : NULL;
    gClearTemporaryEasterEggsFn = on ? s_cleareggs : NULL;
    gEDuplicateSolidFn = on ? s_dup : NULL;
    gEDeleteAllDuplicatedSolidsFn = on ? s_deletedups : NULL;
    gDemoModeReplayLoadFn = on ? s_demoreplayload : NULL;
    gLoadSoundRegionsInGameFn = on ? s_soundregionsin : NULL;
    gLoadTexturesFromFileFn = on ? s_loadtex : NULL;
}

// --------------------------------------------------------------- the input

static char  *line;
static size_t line_cap;

static int hexval(int c)
{
    if (c >= '0' && c <= '9')
        return c - '0';
    if (c >= 'a' && c <= 'f')
        return c - 'a' + 10;
    return -1;
}

static size_t unhex(const char *s, uint8_t **out)
{
    size_t len = strlen(s) / 2, n;
    uint8_t *b = malloc(len ? len : 1);

    for (n = 0; n < len; n++) {
        int hi = hexval(s[2 * n]), lo = hexval(s[2 * n + 1]);

        if (hi < 0 || lo < 0)
            exit(5);
        b[n] = (uint8_t)(hi << 4 | lo);
    }
    *out = b;
    return len;
}

static int read_line(FILE *f)
{
    size_t n = 0;
    int c;

    while ((c = fgetc(f)) != EOF && c != '\n') {
        if (n + 2 > line_cap) {
            line_cap = line_cap ? 2 * line_cap : 4096;
            line = realloc(line, line_cap);
            if (line == NULL)
                exit(3);
        }
        line[n++] = (char)c;
    }
    if (c == EOF && n == 0)
        return 0;
    if (line == NULL) {
        line_cap = 16;
        line = malloc(line_cap);
    }
    line[n] = '\0';
    return 1;
}

static void restore_records(void)
{
    CarTypeInfo *recs;
    int i;

    free(recmem);
    recmem = calloc(NUM_TYPES, sizeof(CarTypeInfo));
    recs = (CarTypeInfo *)(void *)recmem;
    for (i = 0; i < NUM_TYPES; i++) {
        const uint8_t *src = pristine + (size_t)i * REC_SIZE;

        memcpy(&recs[i], src, offsetof(CarTypeInfo, pCarSpecs));
        recs[i].pCarSpecs = NULL;
        memcpy(&recs[i].Pad1, src + REC_SIZE - 4, 4);
    }
    CarTypeInfoArray = recs;
}

static void op_records(const char *s)
{
    if (unhex(s, &pristine) != (size_t)NUM_TYPES * REC_SIZE)
        exit(4);
    restore_records();
}

static void op_patch(const char *s)
{
    int type, off, used;
    uint8_t *bytes;
    size_t len;

    if (sscanf(s, "%d %d %n", &type, &off, &used) != 2)
        exit(4);
    len = unhex(s + used, &bytes);
    if (type < 0 || type >= NUM_TYPES || off < 0
        || (size_t)off + len > offsetof(CarTypeInfo, pCarSpecs))
        exit(4);
    memcpy(recmem + (size_t)type * sizeof(CarTypeInfo) + (size_t)off, bytes,
           len);
    free(bytes);
}

static void reset(void)
{
    InGameFlag = 0;
    pHudTexturePack = NULL;
    WeHaveCheckedIfJR2ServerExists = 0;
    FreeMemoryBeforeLoadingTrackCommon = 0;
    FreeMemoryBeforeLoadingTrackSpecific = 0;
    AnimatedDriverNeedsFixup = 0;
    DemoModeReplayActiveFlag = 0;
    eDisableFixUpTables = 0;
    TheTrackPathManager.ReverseTrackDirection = 0;
    RaceParametersTrackDirection = 0;
    RaceParametersTrackNumber = 0;
    RaceParametersNumPlayerCars = 0;
    RaceParametersAIDemoMode = 0;
    RaceParametersReplayDemoMode = 0;
    memset(&RaceParametersGlobalDisplaySettings, 0,
           sizeof RaceParametersGlobalDisplaySettings);
    pRaceCoordinator = NULL;
    memset(&TheCarLoader, 0, sizeof TheCarLoader);
    memset(&flow, 0, sizeof flow);
    memset(drivers, 0, sizeof drivers);
    ndrivers = 0;
    RaceParametersDriverInfo = drivers;
    RaceParametersNumDriverInfo = 0;
    lbase = mem0 = mstep = nload = nbusy = null_seams = 0;
    nfiles[0] = nfiles[1] = 0;
    memset(counts, 0, sizeof counts);
    nmem = nrf = 0;
    nfound[0] = nfound[1] = 0;
    npend = 0;
    set_seams(1);
    restore_records();
}

static void set_global(const char *name, int v)
{
    if (strcmp(name, "track") == 0) RaceParametersTrackNumber = v;
    else if (strcmp(name, "dir") == 0) RaceParametersTrackDirection = v;
    else if (strcmp(name, "np") == 0) RaceParametersNumPlayerCars = v;
    else if (strcmp(name, "units") == 0)
        RaceParametersGlobalDisplaySettings.Units = (int8_t)v;
    else if (strcmp(name, "aid") == 0) RaceParametersAIDemoMode = v;
    else if (strcmp(name, "rpd") == 0) RaceParametersReplayDemoMode = v;
    else if (strcmp(name, "ndi") == 0) RaceParametersNumDriverInfo = v;
    else if (strcmp(name, "sfe") == 0) flow.skipFE = v;
    else if (strcmp(name, "pend") == 0) flow.pending = v;
    else if (strcmp(name, "ig") == 0) InGameFlag = v;
    else if (strcmp(name, "dft") == 0) eDisableFixUpTables = v;
    else if (strcmp(name, "rev") == 0)
        TheTrackPathManager.ReverseTrackDirection = v;
    else if (strcmp(name, "jr2") == 0) WeHaveCheckedIfJR2ServerExists = v;
    else if (strcmp(name, "fc") == 0) FreeMemoryBeforeLoadingTrackCommon = v;
    else if (strcmp(name, "fs") == 0)
        FreeMemoryBeforeLoadingTrackSpecific = v;
    else if (strcmp(name, "adf") == 0) AnimatedDriverNeedsFixup = v;
    else if (strcmp(name, "fe") == 0) TheCarLoader.InFrontEndFlag = v;
    else if (strcmp(name, "rr") == 0) TheCarLoader.RoundRobinFlag = v;
    else if (strcmp(name, "rc") == 0)
        pRaceCoordinator = v ? (RaceCoordinator *)(void *)rc0_obj : NULL;
    else if (strcmp(name, "hud") == 0) pHudTexturePack = v ? &hud_obj : NULL;
    else if (strcmp(name, "rep") == 0) DemoModeReplayActiveFlag = v;
    else if (strcmp(name, "lbase") == 0) lbase = v;
    else if (strcmp(name, "mem0") == 0) mem0 = v;
    else if (strcmp(name, "mstep") == 0) mstep = v;
    else if (strcmp(name, "nload") == 0) nload = v;
    else if (strcmp(name, "nf2") == 0) nfiles[0] = v;
    else if (strcmp(name, "nf3") == 0) nfiles[1] = v;
    else if (strcmp(name, "nbusy") == 0) nbusy = v;
    else if (strcmp(name, "null") == 0) {
        null_seams = v;
        set_seams(!v);
    } else
        exit(6);
}

static void run_step(char step)
{
    switch (step) {
    case 'C': BeginGameFlowLoadingTrackCommon(); break;
    case 'S': BeginGameFlowLoadingTrackSpecific(); break;
    case 'E': EndGameFlowLoadingTrackSpecific(); break;
    case 'U': BeginGameFlowUnloadingTrackSpecific(); break;
    case 'V': BeginGameFlowUnloadingTrackCommon(); break;
    case 'p': GameFlowLoadingTrackCommonPart1(0); break;
    case 'q': GameFlowLoadingTrackCommonPart2(); break;
    case '1': GameFlowLoadingTrackSpecificPart1(0); break;
    case '2': GameFlowLoadingTrackSpecificPart2(0); break;
    case '3': GameFlowLoadingTrackSpecificPart3(0); break;
    case '4': GameFlowLoadingTrackSpecificPart4(0); break;
    case '5': GameFlowLoadingTrackSpecificPart5(0); break;
    case '6': GameFlowLoadingTrackSpecificPart6(0); break;
    case 'H': LoadHudTextures(testcb); break;
    default: exit(9);
    }
}

static void run_pending(void)
{
    void (*fn)(intptr_t);
    void (*vfn)(void);
    intptr_t param;
    int i;

    if (npend == 0) {
        printf("  nothing pending\n");
        return;
    }
    fn = pend[0].fn;
    vfn = pend[0].vfn;
    param = pend[0].param;
    for (i = 1; i < npend; i++)
        pend[i - 1] = pend[i];
    npend--;
    if (fn != NULL)
        fn(param);
    else
        vfn();
}

static void op_choose(const char *s)
{
    int car, units;
    tLoadableHudTextures t;

    if (sscanf(s, "%d %d", &car, &units) != 2)
        exit(4);
    memset(&t, 0xee, sizeof t);
    ChooseLoadableTextures(car, units, &t);
    printf("  tex %08x %08x %08x %08x\n", (unsigned)t.Speedo,
           (unsigned)t.Tach, (unsigned)t.Shadow, (unsigned)t.ThirdPerson);
}

// ----------------------------------------------------------------- driver

int main(int argc, char **argv)
{
    FILE *fh;

    if (argc < 2 || (fh = fopen(argv[1], "r")) == NULL) {
        fprintf(stderr, "usage: trackflow_test scenarios.txt\n");
        return 2;
    }
    gTrackFlowGameFlow = &flow;
    while (read_line(fh)) {
        char name[16];
        int v[7];

        if (line[0] == 'R') {
            op_records(line + 2);
            continue;
        }
        if (line[0] == 'B') {
            printf("%s\n", line);
            reset();
            continue;
        }
        printf("> %.40s\n", line);
        switch (line[0]) {
        case 'A':
            op_patch(line + 2);
            break;
        case 'G':
            if (sscanf(line + 2, "%15s %d", name, &v[0]) != 2)
                return 4;
            set_global(name, v[0]);
            break;
        case 'd': {
            DriverInfo *d;

            if (sscanf(line + 2, "%d %d %d %d %d %d %d", &v[0], &v[1], &v[2],
                       &v[3], &v[4], &v[5], &v[6]) != 7
                || ndrivers == MAXDRV)
                return 4;
            d = &drivers[ndrivers++];
            d->UniqueDriverNumber = (int8_t)v[0];
            d->EliminatedRank = (int8_t)v[1];
            d->TheDriverType = DRIVER_TYPE_AI_RACER;
            d->CurrentRideInfo.Type = v[2];
            d->CurrentRideInfo.InstanceIndex = (int8_t)v[3];
            d->CurrentRideInfo.SkinNumber = (int8_t)v[4];
            d->CurrentRideInfo.HasDash = (int8_t)v[5];
            d->CurrentRideInfo.CanBeVertexDamaged = (int8_t)v[6];
            RaceParametersNumDriverInfo = ndrivers;
            break;
        }
        case 'X':
            run_step(line[2]);
            print_state();
            break;
        case 'D':
            run_pending();
            print_state();
            break;
        case 'T':
            op_choose(line + 2);
            break;
        default:
            return 6;
        }
    }
    fclose(fh);
    return 0;
}
