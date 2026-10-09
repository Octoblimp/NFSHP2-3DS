// pullover_test -- tools/pullover_check.py's harness.
//
// Runs pullover.c over the checker's script. Everything it calls is a stub
// here that logs its arguments and answers from the script, as the model's
// stubs do; the cops' and the controllers' tables are vtable.c's, faked.
// Pointers print as names: M0 and M1 the managers, W the world, R the
// race, RP the race parameters, U0.. pursuits, RB the roadblock, A0..
// cars, D0.. drivers, K0.. controllers, RD0.. real drivers, P0.. players
// (P0.nis their overlay), C0.. cops, RT0.. routes and RP0.. points; a
// cop's or a controller's `this` for a virtual call is the name plus the
// table's delta.
//
//     pullover_test script.txt > out.txt

#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "aicarcontroller.h"
#include "airoute.h"
#include "car.h"
#include "carcontroller.h"
#include "cop.h"
#include "copmanager.h"
#include "copmgr.h"
#include "hudnis.h"
#include "hudscore.h"
#include "nisoverlay.h"
#include "player.h"
#include "playercam.h"
#include "playerhud.h"
#include "pullover.h"
#include "pursuit.h"
#include "race.h"
#include "racefinish.h"
#include "raceparams.h"
#include "raceupdate.h"
#include "realdriver.h"
#include "vtable.h"
#include "world.h"

#define NM    2
#define NCARS 5
#define NPL   3
#define NCOPS 6
#define NP    2

// The fake tables: the cops' IsAIControlled at 16, the controllers'
// ReleaseBoost at 104, each with its own delta.
#define VT_AI      0x7f000100u
#define VT_PL      0x7f000200u
#define VT_CTL     0x7f000300u
#define AI_DELTA   4
#define PL_DELTA   8
#define CTL_DELTA  12

static uint32_t fb(float f)
{
    uint32_t u;

    memcpy(&u, &f, 4);
    return u;
}

static float bf(uint32_t u)
{
    float f;

    memcpy(&f, &u, 4);
    return f;
}

// ---------------------------------------------------- what the port reads

World          *pCurrentWorld;
tCopManager    *pCopManager;
Race           *pCurrentRace;
RaceParameters  TheRaceParameters;
void          (*gCopSpeechFlushQueueFn)(void);

static tCopManager     mgrs[NM];
static World           world;
static Race            race;
static Car             cars[NCARS];
static DriverInfo      drivers[NCARS];
static AICarController ctls[NCARS];
static char            rds[NCARS][16];
static Player          players[NPL];
static tAICop          cops[NCOPS];
static tPursuit        ps[NP];
static tRoadBlock      rb;
static char            routes[2][16];
static char            points[2][16];

static uint32_t spk;
static int32_t  free_run;
static uint32_t base_time;
static int32_t  nis_playing[NPL];
static int      point_on = 1;
static int      next_route;

// ---------------------------------------------------------------- names

#define NNAMES 128

static const void *name_p[NNAMES];
static char        name_s[NNAMES][16];
static int         nnames;

static void name(const void *p, const char *s)
{
    name_p[nnames] = p;
    snprintf(name_s[nnames], 16, "%s", s);
    nnames++;
}

static const char *sym(const void *p)
{
    int i;

    if (p == NULL)
        return "0";
    for (i = 0; i < nnames; i++)
        if (name_p[i] == p)
            return name_s[i];
    return "?";
}

static void names(void)
{
    char b[16];
    int  k;

    for (k = 0; k < NM; k++) {
        snprintf(b, 16, "M%d", k);
        name(&mgrs[k], b);
    }
    name(&world, "W");
    name(&race, "R");
    name(&TheRaceParameters, "RP");
    name(&rb, "RB");
    for (k = 0; k < NP; k++) {
        snprintf(b, 16, "U%d", k);
        name(&ps[k], b);
    }
    for (k = 0; k < NCARS; k++) {
        snprintf(b, 16, "A%d", k);
        name(&cars[k], b);
        snprintf(b, 16, "D%d", k);
        name(&drivers[k], b);
        snprintf(b, 16, "K%d", k);
        name(&ctls[k], b);
        snprintf(b, 16, "K%d+%d", k, CTL_DELTA);
        name((const char *)&ctls[k] + CTL_DELTA, b);
        snprintf(b, 16, "RD%d", k);
        name(rds[k], b);
    }
    for (k = 0; k < NPL; k++) {
        snprintf(b, 16, "P%d", k);
        name(&players[k], b);
        snprintf(b, 16, "P%d.nis", k);
        name(&players[k].mFlailerNIS, b);
    }
    for (k = 0; k < NCOPS; k++) {
        snprintf(b, 16, "C%d", k);
        name(&cops[k], b);
        snprintf(b, 16, "C%d+%d", k, AI_DELTA);
        name((const char *)&cops[k] + AI_DELTA, b);
        snprintf(b, 16, "C%d+%d", k, PL_DELTA);
        name((const char *)&cops[k] + PL_DELTA, b);
    }
    for (k = 0; k < 2; k++) {
        snprintf(b, 16, "RT%d", k);
        name(routes[k], b);
        snprintf(b, 16, "RP%d", k);
        name(points[k], b);
    }
}

// ---------------------------------------------------------------- stubs

uint32_t tpursuit_get_cop_speaker(const tPursuit *p)
{
    printf("  speaker %s -> %08x\n", sym(p), (unsigned)spk);
    return spk;
}

int32_t tpursuit_remove_cop_from_pursuit(tPursuit *p, tCop *c)
{
    printf("  remove %s %s\n", sym(p), sym(c));
    return 1;
}

void tcop_set_desired_logic_state(tCop *c, eLogicState s)
{
    printf("  state %s %d\n", sym(c), (int)s);
    c->DesiredLogicState = s;
}

void player_start_score(Player *p, int32_t scoring)
{
    printf("  score %s %d\n", sym(p), (int)scoring);
}

int32_t race_parameters_is_free_run(const RaceParameters *rp)
{
    printf("  freerun %s -> %d\n", sym(rp), (int)free_run);
    return free_run;
}

void player_remove_camera_movers(Player *p)
{
    printf("  rmcam %s\n", sym(p));
}

int32_t player_is_nis_playing(const Player *p)
{
    int k = (int)(p - players);

    printf("  nisplaying %s -> %d\n", sym(p), (int)nis_playing[k]);
    return nis_playing[k];
}

float copmanager_get_base_speed_trap_spawn_time(tCopManager *m)
{
    printf("  base %s -> %08x\n", sym(m), (unsigned)base_time);
    return bf(base_time);
}

void copmanager_reset_all_damage(tCopManager *m, Car *car)
{
    printf("  resetdmg %s %s\n", sym(m), sym(car));
}

void realdriver_force_ebrake_stop(RealDriver *d, float t)
{
    printf("  ebrake %s %08x\n", sym(d), (unsigned)fb(t));
}

void race_finish_car_by_car(Race *r, Car *car, int32_t position,
                            int32_t blink, eRaceFinishReason reason)
{
    printf("  finish %s %s %d %d %d\n", sym(r), sym(car), (int)position,
           (int)blink, (int)reason);
}

TrackRoute *car_get_route(Car *c, int find)
{
    printf("  route %s %d -> RT0\n", sym(c), find);
    return (TrackRoute *)(void *)routes[0];
}

TrackRoutePoint *car_get_route_point(Car *c, int find)
{
    TrackRoutePoint *p = point_on ? (TrackRoutePoint *)(void *)points[0]
                                  : NULL;

    printf("  point %s %d -> %s\n", sym(c), find, sym(p));
    return p;
}

void ai_get_next_route_point(NearestRoutePointInfo *info)
{
    printf("  next %s %s\n", sym(info->Route), sym(info->Point));
    info->Point = (TrackRoutePoint *)(void *)points[1];
    if (next_route)
        info->Route = (TrackRoute *)(void *)routes[1];
}

void car_reset_to_route_point(Car *c, TrackRoute *route,
                              TrackRoutePoint *point, float speed,
                              int32_t blink, float direction)
{
    printf("  reset %s %s %s %08x %d %08x\n", sym(c), sym(route),
           sym(point), (unsigned)fb(speed), (int)blink,
           (unsigned)fb(direction));
}

void nisoverlay_start_busted(NISOverlayManager *o)
{
    printf("  busted_on %s\n", sym(o));
}

void nisoverlay_finish(NISOverlayManager *o)
{
    printf("  busted_off %s\n", sym(o));
}

static void flush(void)
{
    printf("  flush\n");
}

static void caught(uint32_t speaker, uint32_t n, int32_t type)
{
    printf("  caught %08x %u %d\n", (unsigned)speaker, (unsigned)n,
           (int)type);
}

static void pullover_event(void)
{
    printf("  pullover_event\n");
}

static void arrests(int32_t a, int32_t b, int32_t c, int32_t d)
{
    printf("  arrests %d %d %d %d\n", (int)a, (int)b, (int)c, (int)d);
}

static void ticket_speech(tPursuit *p)
{
    printf("  ticket_speech %s\n", sym(p));
}

static int32_t play_next_nis(Player *pl, Car *car, Car *cop,
                             void (*done)(int32_t), int32_t param)
{
    printf("  nis %s %s %s %s %d\n", sym(pl), sym(car), sym(cop),
           done == copmanager_end_pullover_callback ? "cb" : "?",
           (int)param);
    return 1;
}

static int32_t is_ai(void *self)
{
    printf("  isai %s -> 1\n", sym(self));
    return 1;
}

static int32_t is_not_ai(void *self)
{
    printf("  isai %s -> 0\n", sym(self));
    return 0;
}

static void release_boost(void *self)
{
    printf("  release %s\n", sym(self));
}

static VtEntry ai_vt[VT_SLOT(TCOP_VT_IS_AI_CONTROLLED) + 1];
static VtEntry pl_vt[VT_SLOT(TCOP_VT_IS_AI_CONTROLLED) + 1];
static VtEntry ctl_vt[VT_SLOT(CARCONTROLLER_VT_RELEASE_BOOST) + 1];

// --------------------------------------------------------------- dumps

static void dump(void)
{
    int k, i;

    for (k = 0; k < NM; k++) {
        const tCopManager *m = &mgrs[k];

        printf("M%d arrests %d time %08x\n", k,
               (int)m->nBeACopNumArrestsMade, (unsigned)fb(m->fBeACopTime));
        for (i = 0; i < NCARS; i++) {
            const tCarPulloverInfo *pl = &m->CarPullovers[i];

            printf("M%d.%d cop %d hold %08x t %d a %d n %d r %d b %d "
                   "pt %08x st %08x\n", k, i, (int)pl->nCopIndex,
                   (unsigned)fb(pl->fHoldTimer), (int)pl->nNumTickets,
                   (int)pl->bActive, (int)pl->bPlayNIS, (int)pl->bArrest,
                   (int)pl->bShouldDisplayBustedText,
                   (unsigned)fb(m->fPursuableTimer[i]),
                   (unsigned)fb(m->fSpeedTrapSpawnTimer[i]));
        }
    }
    for (i = 0; i < NCARS; i++) {
        const Car *c = &cars[i];
        uint32_t   lights;

        memcpy(&lights, &c->CopLights, 4);
        printf("A%d drv %d vis %d lights %08x siren %d bits %d num %d "
               "rumble %08x\n", i, (int)c->DriverRenderingEnabled,
               (int)c->bVisibleOnTrackMap, (unsigned)lights,
               (int)c->TheSirenMode, (int)c->BlownTireBits,
               (int)c->NumBlownTires,
               (unsigned)fb(c->fBlownTireControllerRumbleTimer));
        printf("K%d act %d to %08x\n", i, (int)ctls[i].ForceCurrentAction,
               (unsigned)fb(ctls[i].PullOverTimeout));
    }
    for (i = 0; i < NCOPS; i++)
        printf("C%d st %d sub %d timer %08x\n", i,
               (int)cops[i].Base.DesiredLogicState,
               (int)cops[i].Base.LogicSubState,
               (unsigned)fb(cops[i].fSubStateTimer));
}

// --------------------------------------------------------------- the script

#define MAXT 24

static int split(char *line, char **t)
{
    int   n = 0;
    char *s = line;

    for (;;) {
        char *bar = strchr(s, '|');

        if (n < MAXT)
            t[n++] = s;
        if (bar == NULL)
            break;
        *bar = 0;
        s = bar + 1;
    }
    return n;
}

static uint32_t hx(const char *s)
{
    return (uint32_t)strtoll(s, NULL, 0);
}

static int ix(const char *s)
{
    return (int)strtol(s, NULL, 0);
}

#define AT(arr, s) (ix(s) >= 0 ? &(arr)[ix(s)] : NULL)

static void reset(void)
{
    int k;

    memset(mgrs, 0, sizeof mgrs);
    memset(&world, 0, sizeof world);
    memset(&race, 0, sizeof race);
    memset(&TheRaceParameters, 0, sizeof TheRaceParameters);
    memset(cars, 0, sizeof cars);
    memset(drivers, 0, sizeof drivers);
    memset(ctls, 0, sizeof ctls);
    memset(cops, 0, sizeof cops);
    memset(ps, 0, sizeof ps);
    memset(&rb, 0, sizeof rb);
    for (k = 0; k < NCARS; k++) {
        cars[k].MyDriver = &drivers[k];
        cars[k].pCarController = &ctls[k].Base;
        cars[k].pCarDriver = (CarDriver *)(void *)rds[k];
        ctls[k].Base._vtable = VT_CTL;
    }
    for (k = 0; k < NCOPS; k++)
        cops[k].Base.vptr = VT_AI;
    pCopManager = &mgrs[0];
    spk = 0;
    free_run = 0;
    base_time = 0;
    memset(nis_playing, 0, sizeof nis_playing);
    point_on = 1;
    next_route = 0;
}

static void run(char **t, int n)
{
    const char *o = t[0];

    (void)n;
    if (strcmp(o, "reset") == 0) {
        reset();
        return;
    } else if (strcmp(o, "rp") == 0) {
        int32_t v = (int32_t)hx(t[2]);

        if (strcmp(t[1], "tt") == 0)
            TheRaceParameters.TimeTrialTime.PackedTime = (uint32_t)v;
        else if (strcmp(t[1], "players") == 0)
            TheRaceParameters.NumPlayerCars = v;
        else if (strcmp(t[1], "beacop") == 0)
            TheRaceParameters.BeACop = v;
        else if (strcmp(t[1], "reset") == 0)
            TheRaceParameters.BeACopResetTimerAfterArrest = v;
        else if (strcmp(t[1], "tickets") == 0)
            TheRaceParameters.nNumTicketsBeforeArrest = v;
        else
            fprintf(stderr, "no rp field %s\n", t[1]);
        return;
    } else if (strcmp(o, "race") == 0) {
        race.NumRacingCars = (int32_t)hx(t[1]);
        return;
    } else if (strcmp(o, "world") == 0) {
        int j;

        world.AICarPos = (int32_t)hx(t[1]);
        for (j = 0; j < NCARS; j++)
            world.CarTable[j] = AT(cars, t[2 + j]);
        return;
    } else if (strcmp(o, "cur") == 0) {
        pCopManager = &mgrs[ix(t[1])];
        return;
    } else if (strcmp(o, "m") == 0) {
        tCopManager *m = &mgrs[ix(t[1])];

        m->nNumAICops = (int32_t)hx(t[2]);
        m->nNumCops = (int32_t)hx(t[3]);
        m->nPlayerCopIndex = (int32_t)hx(t[4]);
        m->nBeACopNumArrestsMade = (int32_t)hx(t[5]);
        m->fBeACopTime = bf(hx(t[6]));
        return;
    } else if (strcmp(o, "mcop") == 0) {
        mgrs[ix(t[1])].Cops[ix(t[2])] =
            ix(t[3]) >= 0 ? &cops[ix(t[3])].Base : NULL;
        return;
    } else if (strcmp(o, "pl") == 0) {
        tCarPulloverInfo *pl = &mgrs[ix(t[1])].CarPullovers[ix(t[2])];

        pl->nCopIndex = (int32_t)hx(t[3]);
        pl->fHoldTimer = bf(hx(t[4]));
        pl->nNumTickets = (int8_t)hx(t[5]);
        pl->bActive = (int32_t)hx(t[6]);
        pl->bPlayNIS = (int32_t)hx(t[7]);
        pl->bArrest = (int32_t)hx(t[8]);
        pl->bShouldDisplayBustedText = (int32_t)hx(t[9]);
        return;
    } else if (strcmp(o, "tm") == 0) {
        tCopManager *m = &mgrs[ix(t[1])];

        m->fPursuableTimer[ix(t[2])] = bf(hx(t[3]));
        m->fSpeedTrapSpawnTimer[ix(t[2])] = bf(hx(t[4]));
        return;
    } else if (strcmp(o, "car") == 0) {
        Car     *c = &cars[ix(t[1])];
        uint32_t lights = hx(t[14]);

        c->CarIndex = (int16_t)hx(t[2]);
        drivers[ix(t[1])].TheDriverType = (DriverType)hx(t[3]);
        c->pPlayer = AT(players, t[4]);
        c->TheControlMode = (ControlMode)hx(t[5]);
        c->State.Position.x = bf(hx(t[6]));
        c->State.Position.y = bf(hx(t[7]));
        c->BlownTireBits = (uint8_t)hx(t[8]);
        c->NumBlownTires = (uint8_t)hx(t[9]);
        c->fBlownTireControllerRumbleTimer = bf(hx(t[10]));
        c->bVisibleOnTrackMap = (int32_t)hx(t[11]);
        c->DriverRenderingEnabled = (int32_t)hx(t[12]);
        c->TheSirenMode = (SirenMode)hx(t[13]);
        memcpy(&c->CopLights, &lights, 4);
        return;
    } else if (strcmp(o, "ctl") == 0) {
        AICarController *c = &ctls[ix(t[1])];

        c->ForceCurrentAction = (AIActionType)hx(t[2]);
        c->PullOverTimeout = bf(hx(t[3]));
        return;
    } else if (strcmp(o, "cop") == 0) {
        tAICop *c = &cops[ix(t[1])];

        c->Base.pMyCar = AT(cars, t[2]);
        c->Base.nCopNumber = (int32_t)hx(t[3]);
        c->Base.DesiredLogicState = (eLogicState)hx(t[4]);
        c->Base.LogicSubState = (eLogicSubState)hx(t[5]);
        c->fSubStateTimer = bf(hx(t[6]));
        c->Base.vptr = hx(t[7]) ? VT_AI : VT_PL;
        return;
    } else if (strcmp(o, "pu") == 0) {
        tPursuit *p = &ps[ix(t[1])];

        p->nNumCops = (int32_t)hx(t[2]);
        p->Cops[0] = ix(t[3]) >= 0 ? &cops[ix(t[3])].Base : NULL;
        p->Cops[1] = ix(t[4]) >= 0 ? &cops[ix(t[4])].Base : NULL;
        p->pRoadBlock = hx(t[5]) ? &rb : NULL;
        p->nHUDPursuitLevel = (int32_t)hx(t[6]);
        return;
    } else if (strcmp(o, "rb") == 0) {
        rb.cops[0] = ix(t[1]) >= 0
                         ? (struct stAICop *)(void *)&cops[ix(t[1])] : NULL;
        rb.cops[1] = ix(t[2]) >= 0
                         ? (struct stAICop *)(void *)&cops[ix(t[2])] : NULL;
        return;
    } else if (strcmp(o, "spk") == 0) {
        spk = hx(t[1]);
        return;
    } else if (strcmp(o, "free") == 0) {
        free_run = (int32_t)hx(t[1]);
        return;
    } else if (strcmp(o, "base") == 0) {
        base_time = hx(t[1]);
        return;
    } else if (strcmp(o, "nisp") == 0) {
        nis_playing[ix(t[1])] = (int32_t)hx(t[2]);
        return;
    } else if (strcmp(o, "pt") == 0) {
        point_on = ix(t[1]);
        return;
    } else if (strcmp(o, "nxr") == 0) {
        next_route = ix(t[1]);
        return;
    }

    if (strcmp(o, "create") == 0) {
        printf("create M%s %s A%s %s\n", t[1],
               ix(t[2]) >= 0 ? sym(&ps[ix(t[2])]) : "0", t[3], t[4]);
        copmanager_create_pullover(&mgrs[ix(t[1])], AT(ps, t[2]),
                                   &cars[ix(t[3])], (int32_t)hx(t[4]));
    } else if (strcmp(o, "end") == 0) {
        printf("end M%s %s\n", t[1], t[2]);
        copmanager_end_pullover(&mgrs[ix(t[1])], ix(t[2]));
    } else if (strcmp(o, "cb") == 0) {
        printf("cb %s\n", t[1]);
        copmanager_end_pullover_callback(ix(t[1]));
    } else if (strcmp(o, "gao") == 0) {
        tCop *c = copmanager_get_arresting_officer(&mgrs[ix(t[1])],
                                                   AT(ps, t[2]));

        printf("gao M%s %s -> %s\n", t[1],
               ix(t[2]) >= 0 ? sym(&ps[ix(t[2])]) : "0", sym(c));
    } else if (strcmp(o, "rmt") == 0) {
        printf("rmt M%s A%s\n", t[1], t[2]);
        copmanager_remove_speed_traps_for_car(&mgrs[ix(t[1])],
                                              &cars[ix(t[2])]);
    } else if (strcmp(o, "done") == 0) {
        printf("done C%s\n", t[1]);
        taicop_done_writing_ticket(&cops[ix(t[1])]);
    } else if (strcmp(o, "sbd") == 0) {
        printf("sbd P%s\n", t[1]);
        player_start_busted_display(&players[ix(t[1])]);
    } else if (strcmp(o, "xbd") == 0) {
        printf("xbd P%s\n", t[1]);
        player_stop_busted_display(&players[ix(t[1])]);
    } else {
        fprintf(stderr, "unknown op %s\n", o);
        exit(2);
    }
    dump();
}

int main(int argc, char **argv)
{
    static char line[4096];
    char       *t[MAXT];
    FILE       *f;

    if (argc != 2) {
        fprintf(stderr, "usage: pullover_test script\n");
        return 2;
    }
    f = fopen(argv[1], "r");
    if (f == NULL) {
        perror(argv[1]);
        return 2;
    }
    names();
    pCurrentWorld = &world;
    pCurrentRace = &race;
    gCopSpeechFlushQueueFn = flush;
    gSpeechRaiseRacerCaughtFn = caught;
    gSpeechPulloverEventFn = pullover_event;
    gSpeechBeACopArrestFn = arrests;
    gPursuitAITicketSpeechFn = ticket_speech;
    gPlayerPlayNextNisFn = play_next_nis;
    ai_vt[VT_SLOT(TCOP_VT_IS_AI_CONTROLLED)].delta = AI_DELTA;
    ai_vt[VT_SLOT(TCOP_VT_IS_AI_CONTROLLED)].fn = (VtFn)is_ai;
    pl_vt[VT_SLOT(TCOP_VT_IS_AI_CONTROLLED)].delta = PL_DELTA;
    pl_vt[VT_SLOT(TCOP_VT_IS_AI_CONTROLLED)].fn = (VtFn)is_not_ai;
    ctl_vt[VT_SLOT(CARCONTROLLER_VT_RELEASE_BOOST)].delta = CTL_DELTA;
    ctl_vt[VT_SLOT(CARCONTROLLER_VT_RELEASE_BOOST)].fn = (VtFn)release_boost;
    vt_install(VT_AI, ai_vt, (int)(sizeof ai_vt / sizeof ai_vt[0]));
    vt_install(VT_PL, pl_vt, (int)(sizeof pl_vt / sizeof pl_vt[0]));
    vt_install(VT_CTL, ctl_vt, (int)(sizeof ctl_vt / sizeof ctl_vt[0]));
    reset();
    while (fgets(line, sizeof line, f) != NULL) {
        char *e = line + strlen(line);
        int   n;

        while (e > line && (e[-1] == '\n' || e[-1] == '\r'))
            *--e = 0;
        if (line[0] == 0)
            continue;
        n = split(line, t);
        run(t, n);
    }
    fclose(f);
    return 0;
}
