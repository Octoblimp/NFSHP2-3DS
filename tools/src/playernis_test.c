// playernis_test -- tools/playernis_check.py's harness.
//
// Runs playernis.c over the checker's script, with nisinfo.c's lookups and
// timer.c's SetTime real. Everything else it calls is a stub here that logs
// its arguments and answers from the script, as the model's stubs do.
// Pointers print as names: P0.. players (P0.nis their overlay), M0.. their
// NisManagers, A0.. cars (A0.st their state, A0.pos its Position), AV0..
// the players' averages, CM the cop manager, U a pursuit, NC the camera
// coordinator, RC the race coordinator, R the race, RP the race
// parameters, RT the route, PT its point, N0.. the NIS records and SEED
// bDefaultSeed.
//
//     playernis_test script.txt > out.txt

#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "average.h"
#include "bmath.h"
#include "car.h"
#include "carstate.h"
#include "cartypeinfo.h"
#include "collisionbody.h"
#include "copmanager.h"
#include "hudnis.h"
#include "nisinfo.h"
#include "nismanager.h"
#include "nisoverlay.h"
#include "player.h"
#include "playercam.h"
#include "playernis.h"
#include "playerzone.h"
#include "pursuit.h"
#include "race.h"
#include "racecoord.h"
#include "raceparams.h"
#include "realdriver.h"
#include "realtime.h"
#include "sundraw.h"
#include "trackroute.h"

#define MAXT  64
#define NPL   3
#define NCARS 4
#define NREC  12
#define NA    10
#define NATAN 8

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

static uint32_t hx(const char *s)
{
    return (uint32_t)strtoul(s, NULL, 0);
}

static int ix(const char *s)
{
    return (int)strtol(s, NULL, 0);
}

// ---------------------------------------------------- what the port reads

RaceCoordinator *pRaceCoordinator;
Race            *pCurrentRace;
tCopManager     *pCopManager;
RaceParameters   TheRaceParameters;
struct Player   *PlayerPlayersByIndex[2];
int32_t          PlayerNumPlayers;
int32_t          WorldTimer;
int32_t          WorldTimeFrames;
float            WorldTimeElapsed;
int32_t          bResetGlare;
uint32_t         bDefaultSeed;
void           (*gRadialBlurOffFn)(int32_t view);
void           (*gCollisionSoundPlayBustRoadBlockFn)(const bVector3 *pos);
// playerzone.c's.
const int8_t PlayerZoneBlocksRequest[PLAYER_ZONE_COUNT] = {
    0, 0, 0, 1, 1, 1, 1, 1,
};

static Player           players[NPL];
static NisManager       mgrs[NPL];
static Average          avgs[NPL];
static Car              cars[NCARS];
static CarCollisionBody bodies[NCARS];
static CarTypeInfo      types[NCARS];
static RaceCoordinator  rc;
static Race             race;
static TrackRoute       route;
static TrackRoutePoint  point;
static NisInfo          table[NREC];
static char             cm[16];
static char             pursuit[16];
static char             coord[16];

static int32_t  tickets, free_run, dbg_loop, demo, pursued, zone_ok;
static int      route_on, point_on;
static uint32_t avg_next, yaw_bits, rnd;
static int32_t  atans[NATAN];
static int      natan, atan_at;

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

    for (k = 0; k < NPL; k++) {
        snprintf(b, 16, "P%d", k);
        name(&players[k], b);
        snprintf(b, 16, "P%d.nis", k);
        name(&players[k].mFlailerNIS, b);
        snprintf(b, 16, "M%d", k);
        name(&mgrs[k], b);
        snprintf(b, 16, "AV%d", k);
        name(&avgs[k], b);
    }
    for (k = 0; k < NCARS; k++) {
        snprintf(b, 16, "A%d", k);
        name(&cars[k], b);
        snprintf(b, 16, "A%d.st", k);
        name(&cars[k].State, b);
        snprintf(b, 16, "A%d.pos", k);
        name(&cars[k].State.Position, b);
    }
    for (k = 0; k < NREC; k++) {
        snprintf(b, 16, "N%d", k);
        name(&table[k], b);
    }
    name(cm, "CM");
    name(pursuit, "U");
    name(coord, "NC");
    name(&rc, "RC");
    name(&race, "R");
    name(&TheRaceParameters, "RP");
    name(&route, "RT");
    name(&point, "PT");
    name(&bDefaultSeed, "SEED");
}

// ---------------------------------------------------------------- stubs

int32_t copmanager_get_num_tickets(tCopManager *m, struct Car *c)
{
    printf("  tickets %s %s -> %d\n", sym(m), sym(c), (int)tickets);
    return tickets;
}

void player_clear_zone(struct Player *p, int32_t sound)
{
    printf("  clearzone %s %d\n", sym(p), (int)sound);
}

static void blur_off(int32_t view)
{
    printf("  blur %d\n", (int)view);
}

void car_stop_blinking(Car *c)
{
    printf("  noblink %s\n", sym(c));
}

int32_t race_parameters_is_free_run(const RaceParameters *rp)
{
    printf("  freerun %s -> %d\n", sym(rp), (int)free_run);
    return free_run;
}

void nismanager_start(NisManager *m, int32_t nis, int32_t camera,
                      struct Car *player, struct Car *other)
{
    printf("  start %s %d %d %s %s\n", sym(m), (int)nis, (int)camera,
           sym(player), sym(other));
    m->Playing = 1;
    m->NisNumber = nis;
    m->CamNumber = camera;
    m->EndTime = WorldTimeFrames + 30;
}

void nismanager_stop(NisManager *m)
{
    printf("  stop %s\n", sym(m));
    m->Playing = 0;
}

void nismanager_unload(NisManager *m)
{
    printf("  unload %s\n", sym(m));
}

int32_t nismanager_allow_debug_looping(const NisManager *m)
{
    printf("  adl %s -> %d\n", sym(m), (int)dbg_loop);
    return dbg_loop;
}

void nisoverlay_start_ticket(NISOverlayManager *o)
{
    printf("  ticket %s\n", sym(o));
}

void nisoverlay_start_arrest(NISOverlayManager *o)
{
    printf("  arrest %s\n", sym(o));
}

void nisoverlay_finish(NISOverlayManager *o)
{
    printf("  finish %s\n", sym(o));
}

int32_t racecoordinator_is_replay_demo_mode(const RaceCoordinator *r)
{
    printf("  demo %s -> %d\n", sym(r), (int)demo);
    return demo;
}

void player_change_camera_mover(struct Player *p, CameraMoverType type,
                                int keep)
{
    printf("  cam %s %d %d\n", sym(p), (int)type, keep);
}

static struct NisCameraCoordinator *create_coord(NisManager *m,
                                                 int32_t view)
{
    printf("  coord %s %d -> NC\n", sym(m), (int)view);
    return (struct NisCameraCoordinator *)(void *)coord;
}

int32_t bRandomI(int32_t range, uint32_t *seed)
{
    int32_t r = 0;

    rnd = rnd * 1103515245u + 12345u;
    if (range > 0)
        r = (int32_t)((rnd >> 16) % (uint32_t)range);
    printf("  rand %d %s -> %d\n", (int)range, sym(seed), (int)r);
    return r;
}

int32_t bATan(float x, float y)
{
    int32_t r = atan_at < natan ? atans[atan_at++] : 0;

    printf("  atan %08x %08x -> %d\n", (unsigned)fb(x), (unsigned)fb(y),
           (int)r);
    return r;
}

float carstate_get_yaw_always(CarState *s)
{
    printf("  yaw %s -> %08x\n", sym(s), (unsigned)yaw_bits);
    return bf(yaw_bits);
}

tPursuit *copmanager_is_being_pursued(tCopManager *m, struct Car *c)
{
    tPursuit *r = pursued ? (tPursuit *)(void *)pursuit : NULL;

    printf("  pursued %s %s -> %s\n", sym(m), sym(c), sym(r));
    return r;
}

TrackRoute *car_get_route(Car *c, int find)
{
    TrackRoute *r = route_on ? &route : NULL;

    printf("  route %s %d -> %s\n", sym(c), find, sym(r));
    return r;
}

TrackRoutePoint *car_get_route_point(Car *c, int find)
{
    TrackRoutePoint *r = point_on ? &point : NULL;

    printf("  point %s %d -> %s\n", sym(c), find, sym(r));
    return r;
}

void average_record(Average *a, float v)
{
    printf("  record %s %08x\n", sym(a), (unsigned)fb(v));
    a->fAverage = bf(avg_next);
}

int32_t player_request_zone(struct Player *p, int32_t zone, int32_t force,
                            int32_t sound, int32_t muffle)
{
    printf("  zone %s %d %d %d %d -> %d\n", sym(p), (int)zone, (int)force,
           (int)sound, (int)muffle, (int)zone_ok);
    return zone_ok;
}

static void bust(const bVector3 *pos)
{
    printf("  bust %s\n", sym(pos));
}

static void done_cb(int32_t param)
{
    printf("  cb %d\n", (int)param);
}

// ---------------------------------------------------------------- state

static void reset(void)
{
    int k;

    memset(players, 0, sizeof players);
    memset(mgrs, 0, sizeof mgrs);
    memset(avgs, 0, sizeof avgs);
    memset(cars, 0, sizeof cars);
    memset(bodies, 0, sizeof bodies);
    memset(types, 0, sizeof types);
    memset(&rc, 0, sizeof rc);
    memset(&race, 0, sizeof race);
    memset(&route, 0, sizeof route);
    memset(&point, 0, sizeof point);
    memset(table, 0, sizeof table);
    TheRaceParameters.BeACop = 0;
    TheRaceParameters.nNumTicketsBeforeArrest = 0;
    for (k = 0; k < NPL; k++) {
        players[k].pNisManager = &mgrs[k];
        players[k].pAverageSpeedRatio = &avgs[k];
    }
    for (k = 0; k < NCARS; k++) {
        cars[k].pDynamicCollisionBody = &bodies[k];
        cars[k].pCarTypeInfo = &types[k];
    }
    NisInfoTable = table;
    NumNisInfos = 0;
    pRaceCoordinator = &rc;
    pCurrentRace = &race;
    pCopManager = (tCopManager *)(void *)cm;
    PlayerPlayersByIndex[0] = &players[0];
    PlayerPlayersByIndex[1] = &players[1];
    PlayerNumPlayers = 2;
    WorldTimer = 0;
    WorldTimeFrames = 0;
    WorldTimeElapsed = 0.0f;
    bResetGlare = 0;
    tickets = free_run = dbg_loop = demo = pursued = zone_ok = 0;
    route_on = point_on = 1;
    avg_next = yaw_bits = 0;
    rnd = 0;
    natan = atan_at = 0;
}

static void dump(void)
{
    int k, j;

    printf("G glare %d\n", (int)bResetGlare);
    for (k = 0; k < NPL; k++) {
        Player *p = &players[k];
        NisManager *m = &mgrs[k];
        const char *cb = p->NisFinishedCallback == NULL ? "0"
                         : p->NisFinishedCallback == done_cb ? "cb" : "?";

        printf("P%d cb %s par %d ai %d ti %d coord %s ww %d trouble %08x "
               "prompt %08x ts %08x tt %08x at %08x max %08x frz %08x\n",
               k, cb, (int)p->NisFinishedCallbackParam,
               (int)p->ArrestNisIndex, (int)p->TicketNisIndex,
               sym(p->pNisCameraCoordinator), (int)p->bWrongWay,
               (unsigned)p->LastTimeCarInTrouble.PackedTime,
               (unsigned)p->TimeToDisplayResetPrompt.PackedTime,
               (unsigned)fb(p->fTroubleSpeed),
               (unsigned)p->tTroubleSpeedTimer.PackedTime,
               (unsigned)p->tAverageSpeedTimer.PackedTime,
               (unsigned)fb(p->fMaxSpeedRatio),
               (unsigned)fb(p->fFreezeZoneDelayTimer));
        printf("P%d", k);
        for (j = 0; j < NA; j++)
            printf(" %d/%d/%d/%d", (int)p->TicketNisNumbers[j],
                   (int)p->TicketCameraNumbers[j],
                   (int)p->ArrestNisNumbers[j],
                   (int)p->ArrestCameraNumbers[j]);
        printf("\n");
        printf("M%d play %d end %d cam %d nis %d\n", k, (int)m->Playing,
               (int)m->EndTime, (int)m->CamNumber, (int)m->NisNumber);
    }
}

static Car *car_or_null(const char *s)
{
    int k = ix(s);

    return k >= 0 ? &cars[k] : NULL;
}

static Player *player_or_null(const char *s)
{
    int k = ix(s);

    return k >= 0 ? &players[k] : NULL;
}

static int split(char *s, char **t)
{
    int n = 0;

    t[n++] = s;
    for (; *s; s++) {
        if (*s == '|' && n < MAXT) {
            *s = 0;
            t[n++] = s + 1;
        }
    }
    return n;
}

static void run(char **t, int n)
{
    const char *o = t[0];

    if (strcmp(o, "reset") == 0) {
        reset();
        return;
    } else if (strcmp(o, "rec") == 0) {
        // rec|i|type|nisnumber|frames|cameras
        NisInfo *r = &table[ix(t[1])];

        r->Type = (int32_t)hx(t[2]);
        r->NisNumber = (int32_t)hx(t[3]);
        r->NumFrames = (int32_t)hx(t[4]);
        r->NumCameras = (int32_t)hx(t[5]);
        return;
    } else if (strcmp(o, "ntab") == 0) {
        NumNisInfos = (int32_t)hx(t[1]);
        return;
    } else if (strcmp(o, "rp") == 0) {
        if (strcmp(t[1], "beacop") == 0)
            TheRaceParameters.BeACop = (int32_t)hx(t[2]);
        else
            TheRaceParameters.nNumTicketsBeforeArrest = (int32_t)hx(t[2]);
        return;
    } else if (strcmp(o, "wt") == 0) {
        WorldTimer = (int32_t)hx(t[1]);
        WorldTimeFrames = (int32_t)hx(t[2]);
        WorldTimeElapsed = bf(hx(t[3]));
        return;
    } else if (strcmp(o, "rcs") == 0) {
        rc.CurrentRCState = (RCState)hx(t[1]);
        return;
    } else if (strcmp(o, "rtime") == 0) {
        race.RaceTime.PackedTime = hx(t[1]);
        return;
    } else if (strcmp(o, "np") == 0) {
        PlayerNumPlayers = (int32_t)hx(t[1]);
        return;
    } else if (strcmp(o, "byidx") == 0) {
        PlayerPlayersByIndex[ix(t[1])] = player_or_null(t[2]);
        return;
    } else if (strcmp(o, "pl") == 0) {
        // pl|k|car|zone|pnum|view|aidx|tidx|cb|param|ww
        Player *p = &players[ix(t[1])];

        p->MyCar = car_or_null(t[2]);
        p->nZoneCurrent = (int32_t)hx(t[3]);
        p->PlayerNumber = (int32_t)hx(t[4]);
        p->ViewID = (int32_t)hx(t[5]);
        p->ArrestNisIndex = (int32_t)hx(t[6]);
        p->TicketNisIndex = (int32_t)hx(t[7]);
        p->NisFinishedCallback = hx(t[8]) ? done_cb : NULL;
        p->NisFinishedCallbackParam = hx(t[9]);
        p->bWrongWay = (int32_t)hx(t[10]);
        return;
    } else if (strcmp(o, "pt") == 0) {
        // pt|k|frz|at|max|trouble|prompt|ts|tt
        Player *p = &players[ix(t[1])];

        p->fFreezeZoneDelayTimer = bf(hx(t[2]));
        p->tAverageSpeedTimer.PackedTime = hx(t[3]);
        p->fMaxSpeedRatio = bf(hx(t[4]));
        p->LastTimeCarInTrouble.PackedTime = hx(t[5]);
        p->TimeToDisplayResetPrompt.PackedTime = hx(t[6]);
        p->fTroubleSpeed = bf(hx(t[7]));
        p->tTroubleSpeedTimer.PackedTime = hx(t[8]);
        return;
    } else if (strcmp(o, "arr") == 0) {
        // arr|k|which|j|v: TicketNis, TicketCamera, ArrestNis, ArrestCamera
        Player *p = &players[ix(t[1])];
        int32_t *a[4] = { p->TicketNisNumbers, p->TicketCameraNumbers,
                          p->ArrestNisNumbers, p->ArrestCameraNumbers };

        a[ix(t[2])][ix(t[3])] = (int32_t)hx(t[4]);
        return;
    } else if (strcmp(o, "nm") == 0) {
        // nm|k|playing|end|cam|nis
        NisManager *m = &mgrs[ix(t[1])];

        m->Playing = (int32_t)hx(t[2]);
        m->EndTime = (int32_t)hx(t[3]);
        m->CamNumber = (int32_t)hx(t[4]);
        m->NisNumber = (int32_t)hx(t[5]);
        return;
    } else if (strcmp(o, "car") == 0) {
        // car|k|player|angle|fwd|velmag|nwheels|vx|vy|upz|pdx|pdy|class|pen
        Car *c = &cars[ix(t[1])];

        c->pPlayer = player_or_null(t[2]);
        c->State.Angle = (uint16_t)hx(t[3]);
        c->State.ForwardSpeed = bf(hx(t[4]));
        c->State.VelocityMagnitude = bf(hx(t[5]));
        c->State.nWheelsTouchingGround = (int32_t)hx(t[6]);
        c->State.Velocity.x = bf(hx(t[7]));
        c->State.Velocity.y = bf(hx(t[8]));
        c->State.BodyMatrix.v2.z = bf(hx(t[9]));
        c->TheTrackPathCoordinate.PathDirection.x = bf(hx(t[10]));
        c->TheTrackPathCoordinate.PathDirection.y = bf(hx(t[11]));
        c->pCarTypeInfo->CarClass = (int8_t)ix(t[12]);
        c->pDynamicCollisionBody->LastPenetrationTime.PackedTime = hx(t[13]);
        return;
    } else if (strcmp(o, "dl") == 0) {
        route.DrivingLineInfoTable[ix(t[1])].Flags = hx(t[2]);
        return;
    } else if (strcmp(o, "sp") == 0) {
        point.DrivingLineSpeeds[ix(t[1])] = (uint8_t)hx(t[2]);
        return;
    } else if (strcmp(o, "atan") == 0) {
        int j;

        natan = n - 1 < NATAN ? n - 1 : NATAN;
        atan_at = 0;
        for (j = 0; j < natan; j++)
            atans[j] = (int32_t)hx(t[1 + j]);
        return;
    } else if (strcmp(o, "set") == 0) {
        const char *f = t[1];
        uint32_t    v = hx(t[2]);

        if (strcmp(f, "tickets") == 0)
            tickets = (int32_t)v;
        else if (strcmp(f, "free") == 0)
            free_run = (int32_t)v;
        else if (strcmp(f, "dbg") == 0)
            dbg_loop = (int32_t)v;
        else if (strcmp(f, "demo") == 0)
            demo = (int32_t)v;
        else if (strcmp(f, "pursued") == 0)
            pursued = (int32_t)v;
        else if (strcmp(f, "zone") == 0)
            zone_ok = (int32_t)v;
        else if (strcmp(f, "route") == 0)
            route_on = (int)v;
        else if (strcmp(f, "point") == 0)
            point_on = (int)v;
        else if (strcmp(f, "avg") == 0)
            avg_next = v;
        else if (strcmp(f, "yaw") == 0)
            yaw_bits = v;
        else if (strcmp(f, "seed") == 0)
            rnd = v;
        else if (strcmp(f, "copm") == 0)
            pCopManager = v ? (tCopManager *)(void *)cm : NULL;
        else if (strcmp(f, "glare") == 0)
            bResetGlare = (int32_t)v;
        else {
            fprintf(stderr, "unknown field %s\n", f);
            exit(2);
        }
        return;
    }

    if (strcmp(o, "crna") == 0) {
        printf("crna P%s %d\n", t[1], ix(t[2]));
        player_create_random_nis_array(&players[ix(t[1])], (int32_t)hx(t[2]));
    } else if (strcmp(o, "pnn") == 0) {
        // pnn|k|car|cop|cb|param
        int32_t r;

        printf("pnn P%s A%s A%s %s %d\n", t[1], t[2], t[3],
               hx(t[4]) ? "cb" : "0", ix(t[5]));
        r = player_play_next_nis(&players[ix(t[1])], &cars[ix(t[2])],
                                 &cars[ix(t[3])], hx(t[4]) ? done_cb : NULL,
                                 (int32_t)hx(t[5]));
        printf("  -> %d\n", (int)r);
    } else if (strcmp(o, "svc") == 0) {
        printf("svc P%s\n", t[1]);
        player_service_nis(&players[ix(t[1])]);
    } else if (strcmp(o, "dww") == 0) {
        int32_t r;

        printf("dww P%s %d\n", t[1], ix(t[2]));
        r = player_detect_wrong_way(&players[ix(t[1])], (int32_t)hx(t[2]));
        printf("  -> %d\n", (int)r);
    } else if (strcmp(o, "iar") == 0) {
        int32_t r;

        printf("iar P%s\n", t[1]);
        r = player_is_allowed_to_reset(&players[ix(t[1])]);
        printf("  -> %d\n", (int)r);
    } else if (strcmp(o, "ctdr") == 0) {
        printf("ctdr P%s\n", t[1]);
        player_choose_to_display_reset(&players[ix(t[1])]);
    } else if (strcmp(o, "ugs") == 0) {
        printf("ugs P%s\n", t[1]);
        player_update_game_state(&players[ix(t[1])]);
    } else if (strcmp(o, "upgs") == 0) {
        printf("upgs\n");
        player_update_players_game_state();
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
        fprintf(stderr, "usage: playernis_test script\n");
        return 2;
    }
    f = fopen(argv[1], "r");
    if (f == NULL) {
        perror(argv[1]);
        return 2;
    }
    names();
    gRadialBlurOffFn = blur_off;
    gCollisionSoundPlayBustRoadBlockFn = bust;
    gNisCreateCameraCoordinatorFn = create_coord;
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
