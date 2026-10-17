// Host harness for 3DS Files/source/playerzone.c's camera zones and the
// jump cam's two movers. Runs the op script tools/playerzone_check.py
// writes and prints the transcript it diffs against the retail image, run
// in mipsemu over the same script.
//
// The harness owns what the zones reach outside the file, and prints each
// call as the model's stubs print retail's: the camera calls (a change of
// mover gives a fake one, M0, M1, ...), the HUD's and the input mode's,
// the world's pause and time scale (the callback is kept, for "X" to
// fire), the radial blur, the freeze and preview seams, and the sound's
// (samples S0, S1, ..., the common region's RS, GetInGameSample's I0 to
// I3). For the movers: bMalloc (a pool of 0xa5-filled blocks), the
// TrackCarCameraMover constructor, the TopologyCoordinate and its
// elevation, and the TrackPathCoordinate's ratio, through trackpath.c's
// distance seam with a track one unit long. previewroute.c and
// trackroute.c are the port's own, for the route points' positions.
//
// The players live below 2 GB, at PLAYER_BASE, so that the callback's
// int parameter holds one as it does on the 3DS.
//
// A float prints as its bits, every NaN as "nan", and a pointer by what it
// points at.
#define _DEFAULT_SOURCE
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>

#include "bmem.h"
#include "car.h"
#include "cartypeinfo.h"
#include "player.h"
#include "playercam.h"
#include "playerinit.h"
#include "playerzone.h"
#include "previewroute.h"
#include "race.h"
#include "rcstates.h"
#include "realdriver.h"
#include "realtime.h"
#include "topology.h"
#include "track.h"
#include "trackcarcam.h"
#include "trackpath.h"
#include "trackroute.h"
#include "world.h"

#define PAT         0xa5
#define POOL        (1 << 20)
#define NALLOC      256
#define NPOINTS     40
#define NMOVERS     256
#define NSAMPLES    256
#define PLAYER_BASE ((void *)0x30000000)
#define PLAYER_AREA (1 << 16)

// What the zones read outside themselves.
RaceParameters TheRaceParameters;
TrackInfo *CurrentTrackInfo;
int32_t PlayerNumPlayers;
struct Player *PlayerPlayersByIndex[2];
int32_t SoundEnabled;
int32_t WorldTimer;
int32_t WorldLoopCounter;   // realtime.c's too; ReplaySnapshot_Init reads it
int32_t RealTimer;
float WorldTimeElapsed;
int32_t TweakerPauseWorld;
World *pCurrentWorld;
RaceCoordinator *pRaceCoordinator;
Race *pCurrentRace;

void (*gSamplePlayFn)(struct bSample *s, float volume, float a, float b);
struct bSample *(*gGetInGameSampleFn)(const char *name);
void (*gSampleDeleteFn)(struct bSample *s);
void (*gRadialBlurOnFn)(int32_t);
void (*gRadialBlurOffFn)(int32_t);
CameraMover *(*gZoneFreezeCameraMoverFn)(void *mem, int viewID,
                                         struct Car *car,
                                         CameraMover *saved);
CameraMover *(*gZonePreviewCameraMoverFn)(void *mem, int viewID,
                                          struct PreviewRoute *route,
                                          bVector3 *pos);

static struct Player *p0, *p1;
static TrackInfo trackinfo;
static CarTypeInfo cti;
static Car car;
static CameraDataItems cd;
static bVector3 fov[32];
static PreviewRoute pr;
static PreviewRoutePoint pts[NPOINTS];
static TrackRoutePoint rpts[NPOINTS];
static PreviewRoute fake_route;
static World world;
static char rc_mem[64], race_mem[64];

static struct {
    CameraMover m;
    unsigned char rest[64];
} movers[NMOVERS];
static int nmovers;
static struct {
    unsigned char b[256];
} samples[NSAMPLES], region_sample, ingame[4];
static int nsamples;

static const char *const ingame_names[3] = {"Wind", "PreviewZone",
                                            "SlomoZone"};

static unsigned char pool[POOL] __attribute__((aligned(16)));
static size_t pool_used;
static void *allocs[NALLOC];
static int nalloc;

// The script's answers.
static int32_t rc_state, replay_demo, race_stage, nis;
static int32_t find_route, violates;
static float freeze_dur, preview_dur, cat_volume, tpc_ratio, elevation;

// The world's callback.
static void (*cb)(int32_t);
static int32_t cb_param;
static int have_cb;

static void fill(void *p, size_t n)
{
    memset(p, PAT, n);
}

static int is_pat(const void *p)
{
    uintptr_t v = (uintptr_t)p;
    size_t i;

    for (i = 0; i < sizeof v; i++)
        if (((v >> (8 * i)) & 0xff) != PAT)
            return 0;
    return 1;
}

static const char *nm(const void *p)
{
    static char buf[16][32];
    static int slot;
    char *b = buf[slot++ & 15];
    int i;

    if (p == NULL)
        return "null";
    if (is_pat(p))
        return "pat";
    if (p == p0)
        return "p0";
    if (p == p1)
        return "p1";
    if (p == &car)
        return "car";
    if (p == &cd)
        return "cd";
    if (p == fov)
        return "fov";
    if (p == p0->EyeVerts)
        return "eye";
    if (p == p0->BankVerts)
        return "bank";
    if (p == &pr)
        return "pr";
    if (p == &fake_route)
        return "route";
    if (p == &world)
        return "world";
    if (p == &region_sample)
        return "RS";
    for (i = 0; i < 4; i++) {
        if (p == &ingame[i]) {
            sprintf(b, "I%d", i);
            return b;
        }
    }
    for (i = 0; i < nmovers; i++) {
        if (p == &movers[i]) {
            sprintf(b, "M%d", i);
            return b;
        }
    }
    for (i = 0; i < nsamples; i++) {
        if (p == &samples[i]) {
            sprintf(b, "S%d", i);
            return b;
        }
    }
    for (i = 0; i < nalloc; i++) {
        if (p == allocs[i]) {
            sprintf(b, "A%d", i);
            return b;
        }
    }
    sprintf(b, "?%08lx", (unsigned long)(uint32_t)(uintptr_t)p);
    return b;
}

static uint32_t bits(float f)
{
    uint32_t u;

    memcpy(&u, &f, 4);
    return u;
}

static const char *fx(float f)
{
    static char buf[16][12];
    static int slot;
    char *b = buf[slot++ & 15];
    uint32_t u = bits(f);

    if ((u & 0x7f800000u) == 0x7f800000u && (u & 0x7fffffu))
        return "nan";
    sprintf(b, "%08x", (unsigned)u);
    return b;
}

static float fh(const char *s)
{
    uint32_t u = (uint32_t)strtoul(s, NULL, 16);
    float f;

    memcpy(&f, &u, 4);
    return f;
}

static const char *cb_name(void (*f)(int32_t))
{
    return f == player_clear_zone_callback ? "clearzone" : "?";
}

// ------------------------------------------------------------ the stubs

void *bMalloc(int size, const char *name, int line, int flags)
{
    unsigned char *a;

    (void)flags;
    pool_used = (pool_used + 15) & ~(size_t)15;
    a = pool + pool_used;
    if (size < 0)
        size = 0;
    pool_used += (size_t)size;
    if (pool_used > POOL || nalloc >= NALLOC) {
        fprintf(stderr, "pool exhausted\n");
        exit(2);
    }
    fill(a, (size_t)size);
    allocs[nalloc] = a;
    // The mover's size on the 3DS, which trackcarcam.h checks.
    printf("  malloc A%d %s %d size %d\n", nalloc, name, line,
           size == (int)sizeof(TrackCarCameraMover) ? 1136 : size);
    nalloc++;
    return a;
}

void bFree(void *p)
{
    printf("  free %s\n", nm(p));
}

TrackRoute *car_get_route(Car *c, int find)
{
    (void)c;
    (void)find;
    return NULL;
}

TrackRoutePoint *car_get_route_point(Car *c, int find)
{
    (void)c;
    (void)find;
    return NULL;
}

void player_clean_up_jump_cam(struct Player *p)
{
    printf("  cleanup %s\n", nm(p));
}

int32_t player_is_nis_playing(const struct Player *p)
{
    printf("  nis %s -> %d\n", nm(p), (int)nis);
    return nis;
}

RCState racecoordinator_get_current_state(const RaceCoordinator *rc)
{
    if ((const void *)rc != rc_mem) {
        fprintf(stderr, "not the coordinator\n");
        exit(2);
    }
    return rc_state;
}

int32_t racecoordinator_is_replay_demo_mode(const RaceCoordinator *rc)
{
    printf("  replaydemo %s -> %d\n",
           (const void *)rc == rc_mem ? "rc" : "?", (int)replay_demo);
    return replay_demo;
}

eRaceStage race_get_race_stage(const Race *r)
{
    if ((const void *)r != race_mem) {
        fprintf(stderr, "not the race\n");
        exit(2);
    }
    return race_stage;
}

void player_change_camera_mover(struct Player *p, CameraMoverType type,
                                int keep)
{
    CameraMover *m;

    if (nmovers >= NMOVERS) {
        fprintf(stderr, "too many movers\n");
        exit(2);
    }
    m = &movers[nmovers++].m;
    printf("  ccm %s %d %d -> %s\n", nm(p), (int)type, keep, nm(m));
    p->pCameraMover = m;
}

void player_restore_camera_mover(struct Player *p)
{
    printf("  restore %s\n", nm(p));
}

void player_clear_hud_animations(struct Player *p)
{
    printf("  clearhud %s\n", nm(p));
}

void player_determine_input_mode(struct Player *p)
{
    printf("  inputmode %s\n", nm(p));
}

void world_set_world_paused(World *w, float seconds,
                            void (*callback)(int32_t), int32_t param)
{
    printf("  paused %s %s %s %s\n", nm(w), fx(seconds), cb_name(callback),
           nm((void *)(intptr_t)param));
    cb = callback;
    cb_param = param;
    have_cb = 1;
}

void world_set_time_scale(World *w, float scale, float timer,
                          void (*callback)(int32_t), int32_t param)
{
    printf("  scale %s %s %s %s %s\n", nm(w), fx(scale), fx(timer),
           cb_name(callback), nm((void *)(intptr_t)param));
    cb = callback;
    cb_param = param;
    have_cb = 1;
}

void world_reset_time_scale(World *w)
{
    printf("  resetscale %s\n", nm(w));
}

static void blur_on(int32_t view)
{
    printf("  bluron %d\n", (int)view);
}

static void blur_off(int32_t view)
{
    printf("  bluroff %d\n", (int)view);
}

static float s_freeze_dur(void)
{
    printf("  freezedur -> %s\n", fx(freeze_dur));
    return freeze_dur;
}

static struct PreviewRoute *s_find_route(struct Car *c)
{
    struct PreviewRoute *r = find_route ? &fake_route : NULL;

    printf("  findroute %s -> %s\n", nm(c), nm(r));
    return r;
}

static int32_t s_violates(struct CameraMover *m)
{
    printf("  violates %s -> %d\n", nm(m), (int)violates);
    return violates;
}

static float s_preview_dur(struct CameraMover *m)
{
    printf("  previewdur %s -> %s\n", nm(m), fx(preview_dur));
    return preview_dur;
}

static float s_cat_volume(uint32_t category)
{
    printf("  catvol %u -> %s\n", (unsigned)category, fx(cat_volume));
    return cat_volume;
}

static struct bSample *s_new_sample(void)
{
    struct bSample *s;

    if (nsamples >= NSAMPLES) {
        fprintf(stderr, "too many samples\n");
        exit(2);
    }
    s = (struct bSample *)&samples[nsamples++];
    printf("  newsample %s\n", nm(s));
    return s;
}

static void s_initialize(struct bSample *s, struct bSample *from)
{
    printf("  init %s %s\n", nm(s), nm(from));
}

static void s_set_category(struct bSample *s, uint32_t category)
{
    printf("  setcat %s %08x\n", nm(s), (unsigned)category);
}

static struct bSample *s_region_sample(const char *name)
{
    printf("  region %s -> RS\n", name);
    return (struct bSample *)&region_sample;
}

static void s_play(struct bSample *s, float volume, float a, float b)
{
    printf("  play %s %s %s %s\n", nm(s), fx(volume), fx(a), fx(b));
}

static struct bSample *s_ingame(const char *name)
{
    int i;

    for (i = 0; i < 3 && strcmp(name, ingame_names[i]) != 0; i++)
        ;
    printf("  ingame %s -> %s\n", name, nm(&ingame[i]));
    return (struct bSample *)&ingame[i];
}

static void s_delete(struct bSample *s)
{
    printf("  deletesample %s\n", nm(s));
}

// Never called: zone_ported asks only that they are there.
static CameraMover *fake_freeze(void *mem, int viewID, struct Car *c,
                                CameraMover *saved)
{
    (void)mem, (void)viewID, (void)c, (void)saved;
    fprintf(stderr, "freeze mover built\n");
    exit(2);
}

static CameraMover *fake_preview(void *mem, int viewID,
                                 struct PreviewRoute *route, bVector3 *pos)
{
    (void)mem, (void)viewID, (void)route, (void)pos;
    fprintf(stderr, "preview mover built\n");
    exit(2);
}

// The jump cam's movers.

TrackCarCameraMover *track_car_camera_mover_init(
    TrackCarCameraMover *m, int viewID, struct Car *c,
    const CameraDataItems *d, const CameraShake *shake, int focusEffects)
{
    const unsigned char *b = (const unsigned char *)shake;
    int i;

    printf("  tcc %s view %d car %s cd %s fe %d shake", nm(m), viewID,
           nm(c), nm(d), focusEffects);
    for (i = 0; i < (int)sizeof *shake; i += 4) {
        uint32_t w;

        memcpy(&w, b + i, 4);
        if (w != 0)
            printf(" %d:%08x", i, (unsigned)w);
    }
    printf("\n");
    return m;
}

static TopologyCoordinate *topo_at;

void topology_init(TopologyCoordinate *tc)
{
    printf("  topo\n");
    topo_at = tc;
}

void topology_destroy(TopologyCoordinate *tc)
{
    printf("  topodel %s\n", tc == topo_at ? "same" : "other");
}

float topology_get_elevation(TopologyCoordinate *tc, const bVector3 *pt,
                             int32_t *terrain, bVector3 *normal,
                             int32_t *found)
{
    printf("  elev %s %s %s %s %d%d%d -> %s\n",
           tc == topo_at ? "same" : "other", fx(pt->x), fx(pt->y),
           fx(pt->z), terrain != NULL, normal != NULL, found != NULL,
           fx(elevation));
    return elevation;
}

static float s_distance(const bVector2 *pos)
{
    printf("  tpc %s %s -> %s\n", fx(pos->x), fx(pos->y), fx(tpc_ratio));
    return tpc_ratio;
}

// ------------------------------------------------------------ the dumps

static void dump_player(void)
{
    const struct Player *p = p0;
    int i;

    printf("  pz zone %d prev %d t", (int)p->nZoneCurrent,
           (int)p->nZonePrevious);
    for (i = 0; i < 8; i++)
        printf(" %08x", (unsigned)p->tAutoZoneTimers[i].PackedTime);
    printf(" pov %08x\n", (unsigned)p->tIgnoreNextPovChange.PackedTime);
    printf("  pz route %s sample %s muffle %d %s mover %s\n", nm(p->pRoute),
           nm(p->pZoneSample), (int)p->bZoneMuffleSound,
           fx(p->fZoneMuffleVolume), nm(p->pCameraMover));
}

static void dump_v(const char *tag, int i, const bVector3 *v)
{
    printf("  %s %d %s %s %s\n", tag, i, fx(v->x), fx(v->y), fx(v->z));
}

static void dump_jumper(void)
{
    const CameraDataItems *d = &cd;
    int i;

    printf("  cd type %d name %s iso %d min %s max %s es %s ls %s fs %s"
           " le %d ll %d\n", (int)d->Type, nm(d->Name), (int)d->IsFOVIso,
           fx(d->MinPercent), fx(d->MaxPercent), fx(d->EyeSplineSpeed),
           fx(d->LookSplineSpeed), fx(d->FOVSplineSpeed),
           (int)d->LockEyeSpeedToCar, (int)d->LockLookSpeedToCar);
    printf("  cd mina %s maxa %s near %s far %s back %d fov %s nav %d"
           " av %s naf %d af %s\n", fx(d->MinAreaPercent),
           fx(d->MaxAreaPercent), fx(d->NearClip), fx(d->FarClip),
           (int)d->Backwards, nm(d->FOVTable), (int)d->NumAreaVerts,
           nm(d->AreaVerts), (int)d->NumAreaFaces, nm(d->AreaFaces));
    printf("  cd nev %d ev %s bv %s nlv %d lv %s\n", (int)d->NumEyeVerts,
           nm(d->EyeVerts), nm(d->BankVerts), (int)d->NumLookVerts,
           nm(d->LookVerts));
    printf("  cd spring %s %s %s %s %s look %s %s %s\n", fx(d->SpringXVel),
           fx(d->SpringYVel), fx(d->SpringZVel), fx(d->SpringDamp),
           fx(d->SpringConst), fx(d->LookOffsetX), fx(d->LookOffsetY),
           fx(d->LookOffsetZ));
    printf("  cd enter %s %s leave %s %s set %d wipe %s %d shake %d\n",
           fx(d->EnterVertComp), fx(d->EnterHorizComp),
           fx(d->LeaveVertComp), fx(d->LeaveHorizComp), (int)d->IsLeaveSet,
           fx(d->WipeDistance), (int)d->WipeAutoDisable,
           (int)d->ShakeBankNumber);
    for (i = 0; i < 3; i++)
        dump_v("eyev", i, &p0->EyeVerts[i]);
    for (i = 0; i < 3; i++)
        dump_v("bankv", i, &p0->BankVerts[i]);
    for (i = 0; i < 32; i++)
        dump_v("fovt", i, &fov[i]);
}

// ------------------------------------------------------------ the world

static void reset(void)
{
    pool_used = 0;
    nalloc = 0;
    nmovers = 0;
    nsamples = 0;
    have_cb = 0;
    cb = NULL;
    cb_param = 0;
    rc_state = 3;
    replay_demo = 0;
    race_stage = RACE_STAGE_RACING;
    nis = 0;
    find_route = 1;
    violates = 0;
    freeze_dur = 2.0f;
    preview_dur = 3.0f;
    cat_volume = 1.0f;
    tpc_ratio = 0.5f;
    elevation = 0.0f;

    memset(&TheRaceParameters, 0, sizeof TheRaceParameters);
    TheRaceParameters.GlobalDisplaySettings.JumpCams = 1;
    TheRaceParameters.GlobalDisplaySettings.ZoneCams = 1;
    fill(&trackinfo, sizeof trackinfo);
    CurrentTrackInfo = &trackinfo;
    PlayerNumPlayers = 1;
    SoundEnabled = 1;
    WorldTimer = 100000;
    RealTimer = 200000;
    WorldTimeElapsed = 0.0333f;
    TweakerPauseWorld = 0;
    pCurrentWorld = &world;
    pRaceCoordinator = (RaceCoordinator *)(void *)rc_mem;
    pCurrentRace = (Race *)(void *)race_mem;
    TheTrackPathManager.TrackLength = 1.0f;
    gTrackPathDistanceFn = s_distance;

    fill(p0, sizeof *p0);
    fill(p1, sizeof *p1);
    PlayerPlayersByIndex[0] = p0;
    PlayerPlayersByIndex[1] = p1;
    p0->MyCar = &car;
    p0->PlayerNumber = 1;
    p0->ViewID = 3;
    p0->nZoneCurrent = 0;
    p0->nZonePrevious = 0;
    memset(p0->tAutoZoneTimers, 0, sizeof p0->tAutoZoneTimers);
    p0->tIgnoreNextPovChange.PackedTime = 0;
    p0->pZoneSample = NULL;
    p0->bZoneMuffleSound = 0;
    p0->fZoneMuffleVolume = 0.0f;
    p0->pCameraMover = NULL;
    p0->bWrongWay = 0;
    p0->myCD = &cd;
    p0->FOVtable = fov;
    p0->pJumpCamRoute = &pr;
    p1->nZoneCurrent = 0;

    fill(&car, sizeof car);
    fill(&cti, sizeof cti);
    car.pCarTypeInfo = &cti;
    fill(&cd, sizeof cd);
    fill(fov, sizeof fov);
    fill(&pr, sizeof pr);
    fill(pts, sizeof pts);
    fill(rpts, sizeof rpts);
    pr.pPoints = pts;
    pr.nPoints = 0;
}

static void op(char **t, int n)
{
    const char *c = t[0];

    (void)n;
    if (strcmp(c, "rc") == 0) {
        rc_state = atoi(t[1]);
    } else if (strcmp(c, "rd") == 0) {
        replay_demo = atoi(t[1]);
    } else if (strcmp(c, "st") == 0) {
        race_stage = atoi(t[1]);
    } else if (strcmp(c, "nis") == 0) {
        nis = atoi(t[1]);
    } else if (strcmp(c, "tw") == 0) {
        TweakerPauseWorld = atoi(t[1]);
    } else if (strcmp(c, "wt") == 0) {
        WorldTimer = (int32_t)strtoul(t[1], NULL, 16);
    } else if (strcmp(c, "rt") == 0) {
        RealTimer = (int32_t)strtoul(t[1], NULL, 16);
    } else if (strcmp(c, "we") == 0) {
        WorldTimeElapsed = fh(t[1]);
    } else if (strcmp(c, "se") == 0) {
        SoundEnabled = atoi(t[1]);
    } else if (strcmp(c, "cv") == 0) {
        cat_volume = fh(t[1]);
    } else if (strcmp(c, "jc") == 0) {
        TheRaceParameters.GlobalDisplaySettings.JumpCams = (int8_t)atoi(t[1]);
    } else if (strcmp(c, "zc") == 0) {
        TheRaceParameters.GlobalDisplaySettings.ZoneCams = (int8_t)atoi(t[1]);
    } else if (strcmp(c, "np") == 0) {
        PlayerNumPlayers = atoi(t[1]);
    } else if (strcmp(c, "ww") == 0) {
        p0->bWrongWay = atoi(t[1]);
    } else if (strcmp(c, "fr") == 0) {
        find_route = atoi(t[1]);
    } else if (strcmp(c, "vt") == 0) {
        violates = atoi(t[1]);
    } else if (strcmp(c, "fd") == 0) {
        freeze_dur = fh(t[1]);
    } else if (strcmp(c, "pd") == 0) {
        preview_dur = fh(t[1]);
    } else if (strcmp(c, "tm") == 0) {
        p0->tAutoZoneTimers[atoi(t[1])].PackedTime =
            (uint32_t)strtoul(t[2], NULL, 16);
    } else if (strcmp(c, "zn") == 0) {
        p0->nZoneCurrent = atoi(t[1]);
    } else if (strcmp(c, "sm") == 0) {
        p0->pZoneSample = atoi(t[1]) ? s_new_sample() : NULL;
    } else if (strcmp(c, "dir") == 0) {
        TheRaceParameters.TrackDirection = atoi(t[1]);
    } else if (strcmp(c, "car") == 0) {
        car.State.Position.x = fh(t[1]);
        car.State.Position.y = fh(t[2]);
        car.State.Position.z = fh(t[3]);
        car.State.Velocity.x = fh(t[4]);
        car.State.Velocity.y = fh(t[5]);
        car.State.Velocity.z = fh(t[6]);
        car.TheTrackPathCoordinate.RatioAroundTrack = fh(t[7]);
    } else if (strcmp(c, "rp") == 0) {
        TrackRoutePoint *q = &rpts[atoi(t[1])];

        q->Position.x = fh(t[2]);
        q->Position.y = fh(t[3]);
        q->Elevation = fh(t[4]);
        q->Direction.x = fh(t[5]);
        q->Direction.y = fh(t[6]);
        q->LeftWidth = fh(t[7]);
        q->RightWidth = fh(t[8]);
        q->BankSlope = fh(t[9]);
        q->ForwardSlope = fh(t[10]);
    } else if (strcmp(c, "pp") == 0) {
        int i;

        pr.nPoints = atoi(t[1]);
        for (i = 0; i < NPOINTS; i++)
            pts[i].pPoint = &rpts[i];
    } else if (strcmp(c, "tr") == 0) {
        tpc_ratio = fh(t[1]);
    } else if (strcmp(c, "el") == 0) {
        elevation = fh(t[1]);
    } else if (strcmp(c, "ey") == 0) {
        bVector3 *v = &p0->EyeVerts[atoi(t[1])];

        v->x = fh(t[2]);
        v->y = fh(t[3]);
        v->z = fh(t[4]);
    } else if (strcmp(c, "eh") == 0) {
        cd.EnterHorizComp = fh(t[1]);
    } else if (strcmp(c, "Z") == 0) {
        int got = player_request_zone(p0, atoi(t[1]), atoi(t[2]),
                                      atoi(t[3]), atoi(t[4]));

        printf("  -> %d\n", got);
        dump_player();
    } else if (strcmp(c, "C") == 0) {
        player_clear_zone(p0, atoi(t[1]));
        dump_player();
    } else if (strcmp(c, "S") == 0) {
        player_clear_zone_sound(p0);
        dump_player();
    } else if (strcmp(c, "X") == 0) {
        if (!have_cb) {
            printf("  nofire\n");
            return;
        }
        printf("  fire %s %s\n", cb_name(cb), nm((void *)(intptr_t)cb_param));
        cb(cb_param);
        dump_player();
    } else if (strcmp(c, "J") == 0) {
        struct CameraMover *m;

        p0->pCameraMover = NULL;
        m = player_jump_cam_mover(p0, p0->MyCar, atoi(t[1]));
        p0->pCameraMover = m;
        if (m != NULL)
            m->pPlayer = p0;
        printf("  jumper -> %s\n", nm(m));
        dump_jumper();
    } else {
        fprintf(stderr, "bad op %s\n", c);
        exit(2);
    }
}

int main(int argc, char **argv)
{
    static char line[8192];
    unsigned char *low;
    FILE *f;

    if (argc != 2) {
        fprintf(stderr, "usage: playerzone_test SCRIPT\n");
        return 2;
    }
    low = mmap(PLAYER_BASE, PLAYER_AREA, PROT_READ | PROT_WRITE,
               MAP_PRIVATE | MAP_ANONYMOUS | MAP_FIXED, -1, 0);
    if (low == MAP_FAILED || sizeof(struct Player) * 2 > PLAYER_AREA) {
        fprintf(stderr, "no low memory for the players\n");
        return 2;
    }
    p0 = (struct Player *)low;
    p1 = p0 + 1;

    gRadialBlurOnFn = blur_on;
    gRadialBlurOffFn = blur_off;
    gSoundGetCategoryVolumeFn = s_cat_volume;
    gNewSampleFn = s_new_sample;
    gSampleInitializeFn = s_initialize;
    gSampleSetCategoryFn = s_set_category;
    gCommonRegionSampleFn = s_region_sample;
    gSamplePlayFn = s_play;
    gGetInGameSampleFn = s_ingame;
    gSampleDeleteFn = s_delete;
    gZoneFreezeDurationFn = s_freeze_dur;
    gZonePreviewFindRouteFn = s_find_route;
    gZonePreviewViolatesTopologyFn = s_violates;
    gZonePreviewDurationFn = s_preview_dur;
    // Set, never called: player_change_camera_mover is the harness's.
    gZoneFreezeCameraMoverFn = fake_freeze;
    gZonePreviewCameraMoverFn = fake_preview;

    f = fopen(argv[1], "r");
    if (f == NULL) {
        perror(argv[1]);
        return 2;
    }
    while (fgets(line, sizeof line, f) != NULL) {
        char *t[64];
        int n = 0;
        char *s;

        line[strcspn(line, "\r\n")] = 0;
        if (line[0] == 0)
            continue;
        if (line[0] == 'B') {
            printf("%s\n", line);
            reset();
            continue;
        }
        printf("> %.60s\n", line);
        for (s = strtok(line, " "); s != NULL && n < 64; s = strtok(NULL, " "))
            t[n++] = s;
        op(t, n);
    }
    fclose(f);
    return 0;
}
