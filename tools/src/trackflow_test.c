// Harness for tools/trackflow_check.py: runs the checker's scenarios on
// trackflow.c and prints what the model prints for the image. Every callee
// is a stub here -- the ported ones by name, the rest through the seams --
// and each logs its name, its arguments and the globals the two steps
// write, at the moment of the call. See the checker's docstring.
//
//     trackflow_test scenarios.txt > out.txt

#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bslotpool.h"
#include "collision.h"
#include "collisionbody.h"
#include "demodisc.h"
#include "esolid.h"
#include "eview.h"
#include "gameflow.h"
#include "physcomp.h"
#include "race.h"
#include "scenery.h"
#include "topology.h"
#include "trackflow.h"
#include "trackpath.h"
#include "trackroute.h"

// ------------------------------------------ the globals trackflow.c reads

int32_t          eDisableFixUpTables;
TopologyTree     TheTopologyTree;
TrackPathManager TheTrackPathManager;
DemoDiscManager  TheDemoDiscManager;
eTrackDirection  RaceParametersTrackDirection;
int32_t          RaceParametersNumDriverInfo;
RaceCoordinator *pRaceCoordinator;
void (*gEWaitUntilRenderingDoneFn)(void);

static BGameFlow   flow;
static char        rc0_obj[144], rc_obj[144];
static TexturePack hud_obj;
static int         files_obj[64];
static int         nfiles, nbusy, nfound;

// ------------------------------------------------------------- the labels

static const char *label(const void *p)
{
    static char buf[4][32];
    static int k;
    char *b = buf[k++ & 3];

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
    if (p >= (const void *)files_obj && p < (const void *)(files_obj + 64)) {
        snprintf(b, 32, "f%d", (int)((const int *)p - files_obj));
        return b;
    }
    snprintf(b, 32, "x%p", p);
    return b;
}

static void say(const char *fmt, ...)
{
    va_list ap;

    printf("  ");
    va_start(ap, fmt);
    vprintf(fmt, ap);
    va_end(ap);
    printf(" | ig=%d dft=%d rev=%d jr2=%d rc=%s sfe=%d\n", (int)InGameFlag,
           (int)eDisableFixUpTables,
           (int)TheTrackPathManager.ReverseTrackDirection,
           (int)WeHaveCheckedIfJR2ServerExists, label(pRaceCoordinator),
           flow.skipFE);
}

// ------------------------------------------------------ the ported callees

void efix_up_tables(void) { say("eFixUpTables"); }
void init_collision(void) { say("InitCollision"); }
void init_collision_body(void) { say("InitCollisionBody"); }
void init_contact(void) { say("InitContact"); }
void topotree_init_tree(TopologyTree *t) { say("InitTree %s", label(t)); }
void InitPhysics(int32_t n) { say("InitPhysics %d", (int)n); }
void SkyLoader(void) { say("SkyLoader"); }
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
    say("ChangeGameFlow %d %d%s", desired, pending,
        gf == &flow ? "" : " (not the flow)");
}

// --------------------------------------------------------------- the seams

#define SEAM(fn, name) static void fn(void) { say(name); }
SEAM(s_smokeables, "InitSmokeables")
SEAM(s_rain, "rain_Load")
SEAM(s_debugtopo, "InitDebugTopology")
SEAM(s_markers, "InitTrackMarkers")
SEAM(s_routeeditor, "InitTrackRouteEditor")
SEAM(s_worldobjects, "InitWorldObjects")
SEAM(s_animdriver, "InitAnimatedDriver")
SEAM(s_aiplans, "InitAIPlans")
SEAM(s_wait, "eWaitUntilRenderingDone")
SEAM(s_closeaiplans, "CloseAIPlans")
SEAM(s_closeanimdriver, "CloseAnimatedDriver")
SEAM(s_closeworldobjects, "CloseWorldObjects")
SEAM(s_closerouteeditor, "CloseTrackRouteEditor")
SEAM(s_closemarkers, "CloseTrackMarkers")
SEAM(s_closedebugtopo, "CloseDebugTopology")
SEAM(s_rainunload, "rain_Unload")
SEAM(s_closesmokeables, "CloseSmokeables")
SEAM(s_soundregions, "UnLoadSoundRegions")
SEAM(s_demoreplay, "DemoModeReplayUnload")
SEAM(s_languages, "UnloadAllLanguages")

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

    if (nfound < nfiles)
        f = &files_obj[++nfound];
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
    say("bCountFreeMemory %d", pool);
    return 12345;
}

static void set_seams(int on)
{
    gInitSmokeablesFn = on ? s_smokeables : NULL;
    gRainLoadFn = on ? s_rain : NULL;
    gInitDebugTopologyFn = on ? s_debugtopo : NULL;
    gInitTrackMarkersFn = on ? s_markers : NULL;
    gInitTrackRouteEditorFn = on ? s_routeeditor : NULL;
    gInitWorldObjectsFn = on ? s_worldobjects : NULL;
    gInitAnimatedDriverFn = on ? s_animdriver : NULL;
    gInitAIPlansFn = on ? s_aiplans : NULL;
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
    gRainUnloadFn = on ? s_rainunload : NULL;
    gCloseSmokeablesFn = on ? s_closesmokeables : NULL;
    gFindResourceFileFn = on ? s_find : NULL;
    gUnloadResourceFileFn = on ? s_unloadrf : NULL;
    gUnLoadSoundRegionsFn = on ? s_soundregions : NULL;
    gDemoModeReplayUnloadFn = on ? s_demoreplay : NULL;
    gUnloadAllLanguagesFn = on ? s_languages : NULL;
    gBIsAsyncDoneFn = on ? s_async : NULL;
    gBCountFreeMemoryFn = on ? s_countfree : NULL;
}

// ----------------------------------------------------------------- driver

int main(int argc, char **argv)
{
    FILE *fh;
    char  line[256];
    int   n = 0;

    if (argc < 2 || (fh = fopen(argv[1], "r")) == NULL) {
        fprintf(stderr, "usage: trackflow_test scenarios.txt\n");
        return 2;
    }
    gTrackFlowGameFlow = &flow;
    while (fgets(line, sizeof line, fh)) {
        int dir, ndi, demo, rc, hud, nf, nb, pend, sfe, ig, dft, rev, jr2;
        int null;
        char ops[32];

        if (sscanf(line, "S %d %d %d %d %d %d %d %d %d %d %d %d %d %d %31s",
                   &dir, &ndi, &demo, &rc, &hud, &nf, &nb, &pend, &sfe, &ig,
                   &dft, &rev, &jr2, &null, ops) != 15)
            continue;
        RaceParametersTrackDirection = dir;
        RaceParametersNumDriverInfo = ndi;
        TheDemoDiscManager.bActive = demo;
        pRaceCoordinator = rc ? (RaceCoordinator *)(void *)rc0_obj : NULL;
        pHudTexturePack = hud ? &hud_obj : NULL;
        nfiles = nf;
        nfound = 0;
        nbusy = nb;
        flow.pending = pend;
        flow.skipFE = sfe;
        InGameFlag = ig;
        eDisableFixUpTables = dft;
        TheTrackPathManager.ReverseTrackDirection = rev;
        WeHaveCheckedIfJR2ServerExists = jr2;
        set_seams(!null);

        printf("scenario %d %s\n", n++, ops);
        for (const char *o = ops; *o; o++) {
            if (*o == 'E') {
                printf(" end\n");
                EndGameFlowLoadingTrackSpecific();
                say("end done");
            } else if (*o == 'B') {
                printf(" begin\n");
                BeginGameFlowUnloadingTrackSpecific();
                say("begin done");
            }
        }
    }
    fclose(fh);
    return 0;
}
