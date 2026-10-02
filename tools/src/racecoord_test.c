// Host harness for 3DS Files/source/racecoord.c: RaceCoordinator's
// constructor, destructor, InitForRace and the cleanups, the message queue
// and ChangeState, SetAIDriverModesFromPlayers and
// GetDriverInfoByDriverNumber. Runs the op script
// tools/racecoord_check.py writes and prints the transcript it diffs
// against the retail image, run in mipsemu over the same script.
//
// racecoord.c is the port source under test, with race.c under it
// (GetDriverInfo, GetRacingCar and TheRaceParameters). The harness owns
// everything else, and each piece prints in the model's words: bMalloc
// over a numbered arena, the message slot pool, the Player's constructor,
// destructor and CleanupAfterRace, the Race's and the World's, InitCars
// and InitPlayers, Race::Init and SetupGhostCars, GetTrackInfo, Car's and
// the Chopper's destructors, and every seam.
//
// The World's constructor builds the scenario's world: its car table, its
// CarList and its helicopter, from cars the harness owns. The Player's
// constructor gives the player the scenario's DrivingStyle for its number,
// and InitPlayers its car. The ten state callbacks print the message, the
// state and the queue, and each script reaction answers one message once
// with a message of its own.
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bmem.h"
#include "bslotpool.h"
#include "car.h"
#include "carinit.h"
#include "player.h"
#include "playercam.h"
#include "playerinit.h"
#include "race.h"
#include "racecoord.h"
#include "racecore.h"
#include "raceinit.h"
#include "racerun.h"
#include "replay.h"
#include "track.h"
#include "trackflow.h"
#include "world.h"

#define NOBJ 64                 // a0 .. a63
#define OBJ_BYTES 32768
#define NSLOT 64                // m0 .. m63
#define NCAR 10                 // c0 .. c9, each with r0 .. r9
#define NDRV 12                 // d0 .. d11
#define NREACT 32
#define PATTERN 0xa5

typedef char world_fits[(sizeof(World) <= OBJ_BYTES) ? 1 : -1];
typedef char player_fits[(sizeof(struct Player) <= OBJ_BYTES) ? 1 : -1];
typedef char race_fits[(sizeof(Race) <= OBJ_BYTES) ? 1 : -1];

// What racecoord.c reaches outside the sources linked with it.
World *pCurrentWorld;
ReplayManager *pReplayManager;
int32_t PlayerNumPlayers;
struct Player *PlayerPlayersByNumber[2];
struct Player *PlayerPlayersByIndex[2];
int (*gBCountFreeMemoryFn)(int pool);
void (*gUnloadResourceFileFn)(void *file);
const int *gPlayerCamSkipFE;
void (*gCameraCoordinatorDeleteFn)(void *coord);
RCStateCallbackFn gRCStateCallbacks[NUM_RCSTATES]; // rcstates.c's

static _Alignas(16) unsigned char arena[NOBJ][OBJ_BYTES];
static int nobj;
static RaceCoordinator rcbuf;
static int rcMade;
static RCQueuedMessage slots[NSLOT];
static int slotUsed[NSLOT];
static BSlotPool fakePool;
static DriverInfo drivers[NDRV];
static Car cars[NCAR];
static RacingCar rcars[NCAR];
static TrackInfo trackInfo;
static _Alignas(16) unsigned char fly[32], pre[32], eg[32], heli[32],
    file0[32];

static int freeMem;
static int prerace;
static int skipFE;

// The scenario's world and players.
static int tAIPos, tCopPos, tTrafficPos, tNTable,
    tTable[WORLD_MAX_CARS];
static int tNList, tList[NCAR];
static int tHeli;
static int tStyle[2], tCar[2];

static struct {
    int state, msg;
    char kind;
    int a, b;
} react[NREACT];
static int nreact;

// ------------------------------------------------------------- the names

static int index_in(const void *p, const void *base, size_t stride, int n)
{
    const unsigned char *c = p, *b = base;
    size_t off;

    if (c < b || c >= b + stride * (size_t)n)
        return -1;
    off = (size_t)(c - b);
    return off % stride ? -1 : (int)(off / stride);
}

static const char *nm(const void *p)
{
    static char b16[16][32];
    static int slot;
    char *b = b16[slot++ & 15];
    int i;

    if (p == NULL)
        return "null";
    if (p == &rcbuf)
        return "rc";
    if (p == fly)
        return "fly";
    if (p == pre)
        return "pre";
    if (p == eg)
        return "eg";
    if (p == heli)
        return "h0";
    if (p == file0)
        return "f0";
    if (p == &fakePool)
        return "pool";
    if (p == &trackInfo)
        return "ti";
    if ((i = index_in(p, arena, OBJ_BYTES, NOBJ)) >= 0)
        sprintf(b, "a%d", i);
    else if ((i = index_in(p, slots, sizeof slots[0], NSLOT)) >= 0)
        sprintf(b, "m%d", i);
    else if ((i = index_in(p, drivers, sizeof drivers[0], NDRV)) >= 0)
        sprintf(b, "d%d", i);
    else if ((i = index_in(p, cars, sizeof cars[0], NCAR)) >= 0)
        sprintf(b, "c%d", i);
    else if ((i = index_in(p, rcars, sizeof rcars[0], NCAR)) >= 0)
        sprintf(b, "r%d", i);
    else
        return "s";
    return b;
}

static const char *fx(float f)
{
    static char b16[16][12];
    static int slot;
    char *b = b16[slot++ & 15];
    uint32_t u;

    memcpy(&u, &f, 4);
    if ((u & 0x7f800000u) == 0x7f800000u && (u & 0x7fffffu))
        return "nan";
    sprintf(b, "%08lx", (unsigned long)u);
    return b;
}

// The queue both ways: each message with its RCMessage and parameter
// forward, the names back.
static const char *queue_str(const RaceCoordinator *rc)
{
    static char b[4096];
    const bNode *list = &rc->RCQueuedMessageList;
    const bNode *n;
    size_t k = 0;
    int i;

    b[0] = 0;
    for (n = list->next, i = 0; n != list && i < 80; n = n->next, i++) {
        const RCQueuedMessage *m = (const RCQueuedMessage *)(const void *)n;

        k += (size_t)sprintf(b + k, " %s:%d/%d", nm(m), (int)m->Msg,
                             (int)m->Param);
    }
    k += (size_t)sprintf(b + k, " |");
    for (n = list->prev, i = 0; n != list && i < 80; n = n->prev, i++)
        k += (size_t)sprintf(b + k, " %s", nm(n));
    return b;
}

// ---------------------------------------------------- the arena and pool

static int retail_size(int size)
{
    if (size == (int)sizeof(struct Player))
        return 2752;
    if (size == (int)sizeof(Race))
        return 1716;
    if (size == (int)sizeof(World))
        return 5936;
    if (size == (int)sizeof(RaceCoordinator))
        return 144;
    return size;
}

void *bMalloc(int size, const char *name, int flags, int pool)
{
    void *p;

    if (nobj >= NOBJ) {
        fprintf(stderr, "arena full\n");
        exit(3);
    }
    p = arena[nobj++];
    memset(p, PATTERN, OBJ_BYTES);
    printf("  malloc %d %s %d %d -> %s\n", retail_size(size), name, flags,
           pool, nm(p));
    return p;
}

void bFree(void *p)
{
    printf("  delete %s\n", nm(p));
}

BSlotPool *bNewSlotPool(int slotSize, int numSlots, const char *name,
                        int pool)
{
    printf("  newpool %d %d %s %d -> pool\n",
           slotSize == (int)sizeof(RCQueuedMessage) ? 16 : slotSize,
           numSlots, name, pool);
    return &fakePool;
}

void bDeleteSlotPool(BSlotPool *pool)
{
    printf("  delpool %s\n", nm(pool));
}

void *bSlotOMalloc(BSlotPool *pool)
{
    int i;

    for (i = 0; i < NSLOT; i++) {
        if (!slotUsed[i]) {
            slotUsed[i] = 1;
            memset(&slots[i], PATTERN, sizeof slots[i]);
            printf("  omalloc %s -> %s\n", nm(pool), nm(&slots[i]));
            return &slots[i];
        }
    }
    fprintf(stderr, "slots full\n");
    exit(3);
}

void bSlotFree(BSlotPool *pool, void *slot)
{
    int i = index_in(slot, slots, sizeof slots[0], NSLOT);

    // With the coordinator's flag, which retail clears before the free.
    printf("  free %s %s ex=%d\n", nm(pool), nm(slot),
           (int)rcbuf.RCExecutingMessage);
    if (i >= 0)
        slotUsed[i] = 0;
}

// --------------------------------------------------------- the players

struct Player *player_init(struct Player *p, JoystickPort port,
                           int32_t number)
{
    printf("  player %s %d %d\n", nm(p), (int)port, (int)number);
    if (PlayerNumPlayers < 2)
        PlayerPlayersByIndex[PlayerNumPlayers] = p;
    PlayerNumPlayers++;
    p->PlayerNumber = number;
    p->MyCar = NULL;
    if (number >= 0 && number < 2) {
        p->PlayerSettings.DrivingStyle = (int8_t)tStyle[number];
        PlayerPlayersByNumber[number] = p;
    }
    return p;
}

void player_destroy(struct Player *p, int32_t flags)
{
    printf("  player-del %s %d\n", nm(p), (int)flags);
    PlayerNumPlayers--;
    if (PlayerNumPlayers >= 0 && PlayerNumPlayers < 2)
        PlayerPlayersByIndex[PlayerNumPlayers] = NULL;
    if (p->PlayerNumber >= 0 && p->PlayerNumber < 2)
        PlayerPlayersByNumber[p->PlayerNumber] = NULL;
}

void player_cleanup_after_race(struct Player *p)
{
    printf("  player-cleanup %s\n", nm(p));
}

void racecoordinator_init_players(RaceCoordinator *rc)
{
    int i;

    printf("  initplayers %s\n", nm(rc));
    for (i = 0; i < PlayerNumPlayers && i < 2; i++) {
        struct Player *p = PlayerPlayersByIndex[i];

        if (p != NULL && p->PlayerNumber >= 0 && p->PlayerNumber < 2)
            p->MyCar = tCar[p->PlayerNumber] >= 0
                           ? &cars[tCar[p->PlayerNumber]] : NULL;
    }
}

void racecoordinator_init_cars(RaceCoordinator *rc)
{
    printf("  initcars %s\n", nm(rc));
}

// --------------------------------------------- the race and the world

Race *race_construct(Race *r)
{
    printf("  race %s\n", nm(r));
    return r;
}

void race_destroy(Race *r, int32_t flags)
{
    printf("  race-del %s %d\n", nm(r), (int)flags);
}

void race_init(Race *r, eRaceStage stage)
{
    printf("  raceinit %s %d\n", nm(r), (int)stage);
}

void race_setup_ghost_cars(Race *r)
{
    printf("  ghosts %s\n", nm(r));
}

World *world_init(World *w)
{
    int i;

    printf("  world %s\n", nm(w));
    w->CarList.next = w->CarList.prev = &w->CarList;
    w->AICarList.next = w->AICarList.prev = &w->AICarList;
    w->CollisionList.next = w->CollisionList.prev = &w->CollisionList;
    w->Helicopter = tHeli ? (struct Chopper *)(void *)heli : NULL;
    w->TotalNumCars = tNTable;
    w->AICarPos = tAIPos;
    w->CopCarPos = tCopPos;
    w->TrafficCarPos = tTrafficPos;
    for (i = 0; i < WORLD_MAX_CARS; i++)
        w->CarTable[i] = i < tNTable && tTable[i] >= 0 ? &cars[tTable[i]]
                                                        : NULL;
    for (i = 0; i < tNList; i++) {
        Car *c = &cars[tList[i]];
        CarNode *tail = (CarNode *)w->CarList.prev;

        c->Link.prev = tail;
        c->Link.next = (CarNode *)(void *)&w->CarList;
        tail->next = &c->Link;
        w->CarList.prev = c;
    }
    pCurrentWorld = w;
    return w;
}

void world_destroy(World *w, int32_t flags)
{
    printf("  world-del %s %d\n", nm(w), (int)flags);
}

void world_flush_collisions(World *w)
{
    (void)w;
}

void car_destruct(Car *c, int32_t flags)
{
    printf("  cardel %s %d\n", nm(c), (int)flags);
}

TrackInfo *track_get_info(int i)
{
    printf("  trackinfo %d\n", i);
    return &trackInfo;
}

// ------------------------------------------------------------ the seams

static int s_free(int pool)
{
    (void)pool;
    return freeMem;
}

static void s_unload(void *f)
{
    printf("  unload %s\n", nm(f));
    prerace = 0;
}

static void *s_find(const char *name)
{
    void *f = prerace ? file0 : NULL;

    printf("  find %s -> %s\n", name, nm(f));
    return f;
}

static struct PauseMenu *s_pause(void *mem)
{
    printf("  pausemenu %s\n", nm(mem));
    return mem;
}

static void s_pause_del(struct PauseMenu *m, int32_t flags)
{
    printf("  pausemenu-del %s %d\n", nm(m), (int)flags);
}

static struct ReplayManager *s_replay(void *mem)
{
    printf("  replaymgr %s\n", nm(mem));
    return mem;
}

static void s_replay_del(struct ReplayManager *rm, int32_t flags)
{
    printf("  replaymgr-del %s %d\n", nm(rm), (int)flags);
}

static void s_eggs(void)   { printf("  eggsoff\n"); }
static void s_coll(void)   { printf("  collsnd\n"); }
static void s_speech(void) { printf("  speech\n"); }
static void s_kill(void)   { printf("  effects-kill\n"); }
static void s_jb(void)     { printf("  jbstop\n"); }
static void s_oneshot(void) { printf("  oneshot-reset\n"); }

static void s_autoreplay(RaceCoordinator *rc)
{
    printf("  autoreplay-cleanup %s\n", nm(rc));
}

static void s_heli_del(struct Chopper *h, int32_t flags)
{
    printf("  heli-del %s %d\n", nm(h), (int)flags);
}

static void s_endgame_del(struct EndGameScreens *s, int32_t flags)
{
    printf("  endgame-del %s %d\n", nm(s), (int)flags);
}

static void s_ccdel(void *coord)
{
    printf("  ccdel %s 3\n", nm(coord));
}

// ------------------------------------------------------- the callbacks

static void respond(int state, RaceCoordinator *rc, RCMessage msg)
{
    int i;

    for (i = 0; i < nreact; i++) {
        if (react[i].state == state && react[i].msg == msg) {
            char kind = react[i].kind;
            int a = react[i].a, b = react[i].b;

            memmove(&react[i], &react[i + 1],
                    sizeof react[0] * (size_t)(nreact - i - 1));
            nreact--;
            if (kind == 'S')
                racecoordinator_send_message(rc, a, b);
            else if (kind == 'P')
                racecoordinator_post_message(rc, a, b);
            else if (kind == 'C')
                racecoordinator_change_state(rc, a);
            else if (kind == 'E')
                racecoordinator_execute_queued_messages(rc);
            return;
        }
    }
}

static int32_t callback(int state, RaceCoordinator *rc, RCMessage msg,
                        int32_t param)
{
    printf("  cb %d %d %d this=%s st=%d ex=%d rc=%s bp=%d cd=%d port=%d "
           "demo=%s cm=%s eye=%s w140=%d q=%s\n",
           state, (int)msg, (int)param, nm(rc), (int)rc->CurrentRCState,
           (int)rc->RCExecutingMessage, nm(pRaceCoordinator),
           (int)rc->BeforePauseRCState, (int)rc->DisplayingCountdownNumber,
           (int)rc->PausedJoystickPort, nm(rc->pDemoCameraCoordinator),
           nm(rc->mpCameraMover), nm(rc->mpEyeVerts),
           (int)rc->PostRaceWord140, queue_str(rc));
    respond(state, rc, msg);
    return 1;
}

#define CB(n)                                                              \
    static int32_t cb##n(RaceCoordinator *rc, RCMessage m, int32_t p)      \
    {                                                                      \
        return callback(n, rc, m, p);                                      \
    }
CB(0) CB(1) CB(2) CB(3) CB(4) CB(5) CB(6) CB(7) CB(8) CB(9)

// -------------------------------------------------------------- the dump

static void dump(void)
{
    const RaceCoordinator *rc = &rcbuf;
    int i;

    if (rcMade) {
        printf("  rc st=%d ex=%d cd=%d port=%d bp=%d demo=%s fly=%s pre=%s "
               "eg=%s rs=%s nr=%d cm=%s cdp=%s ip=%s\n",
               (int)rc->CurrentRCState, (int)rc->RCExecutingMessage,
               (int)rc->DisplayingCountdownNumber,
               (int)rc->PausedJoystickPort, (int)rc->BeforePauseRCState,
               nm(rc->pDemoCameraCoordinator),
               nm(rc->pFlyByCameraCoordinator),
               nm(rc->pPreRaceCameraCoordinator), nm(rc->pEndGameScreens),
               nm(rc->pReplayScreen), (int)rc->mNumRewinds,
               nm(rc->mpCameraMover), nm(rc->mpCD), nm(rc->mIncidentPoint));
        printf("  rcv %s %s %s %s | %s %s %s %s | %s %s %s %s\n",
               fx(rc->mIncidentCoord.x), fx(rc->mIncidentCoord.y),
               fx(rc->mIncidentCoord.z), fx(rc->mIncidentCoord.pad),
               fx(rc->mFinalPosition.x), fx(rc->mFinalPosition.y),
               fx(rc->mFinalPosition.z), fx(rc->mFinalPosition.pad),
               fx(rc->mStartPosition.x), fx(rc->mStartPosition.y),
               fx(rc->mStartPosition.z), fx(rc->mStartPosition.pad));
        printf("  rc3 eye=%s bank=%s fov=%s hl=%s hl2=%s view=%d route=%s "
               "w140=%d\n",
               nm(rc->mpEyeVerts), nm(rc->mpBankVerts), nm(rc->mpFOVtable),
               nm(rc->mpHighlightCar), nm(rc->mpHighlightCar2),
               (int)rc->mViewID, nm(rc->mpRoute), (int)rc->PostRaceWord140);
        printf("  q%s\n", queue_str(rc));
    }
    printf("  g rc=%s race=%s world=%s rm=%s pm=%s pool=%s np=%d idx=%s,%s "
           "num=%s,%s\n",
           nm(pRaceCoordinator), nm(pCurrentRace), nm(pCurrentWorld),
           nm(pReplayManager), nm(ThePauseMenu), nm(RCQueuedMessageSlotPool),
           (int)PlayerNumPlayers, nm(PlayerPlayersByIndex[0]),
           nm(PlayerPlayersByIndex[1]), nm(PlayerPlayersByNumber[0]),
           nm(PlayerPlayersByNumber[1]));
    for (i = 0; i < 2; i++) {
        const struct Player *p = PlayerPlayersByIndex[i];

        if (p != NULL)
            printf("  p%d %s num=%d style=%d car=%s\n", i, nm(p),
                   (int)p->PlayerNumber, (int)p->PlayerSettings.DrivingStyle,
                   nm(p->MyCar));
    }
    printf("  modes");
    for (i = 0; i < NCAR; i++)
        printf(" %d", (int)cars[i].State.DriverMode);
    printf("\n");
    if (pCurrentWorld != NULL) {
        const World *w = pCurrentWorld;
        const CarNode *n;

        printf("  w heli=%s list", nm(w->Helicopter));
        for (n = w->CarList.next, i = 0;
             n != (const void *)&w->CarList && i < 32; n = n->next, i++)
            printf(" %s", nm(n));
        printf(" |");
        for (n = w->CarList.prev, i = 0;
             n != (const void *)&w->CarList && i < 32; n = n->prev, i++)
            printf(" %s", nm(n));
        printf("\n");
    }
}

// --------------------------------------------------------------- the ops

static void reset(void)
{
    int i;

    nobj = 0;
    rcMade = 0;
    memset(&rcbuf, PATTERN, sizeof rcbuf);
    memset(slotUsed, 0, sizeof slotUsed);
    memset(drivers, PATTERN, sizeof drivers);
    memset(cars, PATTERN, sizeof cars);
    memset(rcars, PATTERN, sizeof rcars);
    for (i = 0; i < NCAR; i++)
        cars[i].pRacingCar = &rcars[i];
    RaceParametersDriverInfo = drivers;
    RaceParametersNumDriverInfo = 0;
    RaceParametersTrackNumber = 1;
    RaceParametersAIDemoMode = 0;
    RaceParametersReplayDemoMode = 0;
    RaceParametersBeACop = 0;
    RaceParametersNumPlayerCars = 1;
    RaceParametersNumAICars = 7;
    skipFE = 0;
    freeMem = 0x100000;
    prerace = 0;
    pRaceCoordinator = NULL;
    pCurrentRace = NULL;
    pCurrentWorld = NULL;
    pReplayManager = NULL;
    ThePauseMenu = NULL;
    RCQueuedMessageSlotPool = NULL;
    PlayerNumPlayers = 0;
    for (i = 0; i < 2; i++) {
        PlayerPlayersByIndex[i] = NULL;
        PlayerPlayersByNumber[i] = NULL;
        tStyle[i] = 0;
        tCar[i] = -1;
    }
    tAIPos = tCopPos = tTrafficPos = tNTable = tNList = tHeli = 0;
    nreact = 0;
}

static void set_global(const char *f, int v)
{
    if (!strcmp(f, "aidemo"))
        RaceParametersAIDemoMode = v;
    else if (!strcmp(f, "replaydemo"))
        RaceParametersReplayDemoMode = v;
    else if (!strcmp(f, "beacop"))
        RaceParametersBeACop = v;
    else if (!strcmp(f, "nplaycars"))
        RaceParametersNumPlayerCars = v;
    else if (!strcmp(f, "naicars"))
        RaceParametersNumAICars = v;
    else if (!strcmp(f, "ndrv"))
        RaceParametersNumDriverInfo = v;
    else if (!strcmp(f, "track"))
        RaceParametersTrackNumber = v;
    else if (!strcmp(f, "skipfe"))
        skipFE = v;
    else if (!strcmp(f, "free"))
        freeMem = v;
    else if (!strcmp(f, "prerace"))
        prerace = v;
    else if (!strcmp(f, "state"))
        rcbuf.CurrentRCState = v;
    else if (!strcmp(f, "exec"))
        rcbuf.RCExecutingMessage = v;
    else if (!strcmp(f, "fly"))
        rcbuf.pFlyByCameraCoordinator = v ? fly : NULL;
    else if (!strcmp(f, "pre"))
        rcbuf.pPreRaceCameraCoordinator = v ? pre : NULL;
    else if (!strcmp(f, "eg"))
        rcbuf.pEndGameScreens = v ? (struct EndGameScreens *)(void *)eg
                                  : NULL;
    else if (!strcmp(f, "world"))
        pCurrentWorld = NULL;
    else if (!strcmp(f, "race"))
        pCurrentRace = NULL;
    else {
        fprintf(stderr, "bad global %s\n", f);
        exit(2);
    }
}

static int ints(char *s, int *out, int max)
{
    int n = 0;
    char *t;

    while (n < max && (t = strtok(s, " \t\r\n")) != NULL) {
        out[n++] = (int)strtol(t, NULL, 0);
        s = NULL;
    }
    return n;
}

static void op(char *line)
{
    char c[8] = {0}, f[32] = {0};
    int n[32], k;
    char *rest;

    if (sscanf(line, "%7s", c) != 1)
        return;
    rest = line + strlen(c);
    if (!strcmp(c, "S")) {
        int v;

        if (sscanf(rest, "%31s %i", f, &v) != 2) {
            fprintf(stderr, "bad S\n");
            exit(2);
        }
        set_global(f, v);
        return;
    }
    if (!strcmp(c, "R")) {
        char kind;

        if (nreact >= NREACT) {
            fprintf(stderr, "reactions full\n");
            exit(2);
        }
        if (sscanf(rest, "%d %d %c %d %d", &react[nreact].state,
                   &react[nreact].msg, &kind, &react[nreact].a,
                   &react[nreact].b) != 5) {
            fprintf(stderr, "bad R\n");
            exit(2);
        }
        react[nreact++].kind = kind;
        return;
    }
    k = ints(rest, n, 32);
    if (!strcmp(c, "D")) {
        drivers[n[0]].EliminatedRank = (int8_t)n[1];
        drivers[n[0]].UniqueDriverNumber = (int8_t)n[2];
        return;
    }
    if (!strcmp(c, "Y")) {
        tStyle[n[0]] = n[1];
        tCar[n[0]] = n[2];
        return;
    }
    if (!strcmp(c, "Q")) {
        if (PlayerPlayersByNumber[n[0]] != NULL)
            PlayerPlayersByNumber[n[0]]->PlayerSettings.DrivingStyle =
                (int8_t)n[1];
        return;
    }
    if (!strcmp(c, "K")) {
        rcars[n[0]].RacePosition = (int8_t)n[1];
        return;
    }
    if (!strcmp(c, "Wt")) {
        int i;

        tAIPos = n[0];
        tCopPos = n[1];
        tTrafficPos = n[2];
        tNTable = k - 3;
        for (i = 0; i < tNTable; i++)
            tTable[i] = n[3 + i];
        return;
    }
    if (!strcmp(c, "Wl")) {
        int i;

        tNList = k;
        for (i = 0; i < k; i++)
            tList[i] = n[i];
        return;
    }
    if (!strcmp(c, "Wh")) {
        tHeli = n[0];
        return;
    }

    if (!strcmp(c, "N")) {
        memset(&rcbuf, PATTERN, sizeof rcbuf);
        rcMade = 1;
        racecoordinator_construct(&rcbuf);
    } else if (!strcmp(c, "X")) {
        racecoordinator_destroy(&rcbuf, n[0]);
    } else if (!strcmp(c, "G")) {
        racecoordinator_init_for_race(&rcbuf);
    } else if (!strcmp(c, "U")) {
        racecoordinator_cleanup_after_race(&rcbuf);
    } else if (!strcmp(c, "CP")) {
        racecoordinator_cleanup_players(&rcbuf);
    } else if (!strcmp(c, "CC")) {
        racecoordinator_cleanup_cars(&rcbuf);
    } else if (!strcmp(c, "T")) {
        racecoordinator_change_state(&rcbuf, n[0]);
    } else if (!strcmp(c, "M")) {
        racecoordinator_send_message(&rcbuf, n[0], n[1]);
    } else if (!strcmp(c, "P")) {
        racecoordinator_post_message(&rcbuf, n[0], n[1]);
    } else if (!strcmp(c, "E")) {
        racecoordinator_execute_queued_messages(&rcbuf);
    } else if (!strcmp(c, "A")) {
        set_ai_driver_modes_from_players();
    } else if (!strcmp(c, "F")) {
        DriverInfo *d = race_parameters_get_driver_info_by_driver_number(n[0]);

        printf("  driver %d -> %s\n", n[0], nm(d));
    } else {
        fprintf(stderr, "bad op %s\n", c);
        exit(2);
    }
    dump();
}

int main(int argc, char **argv)
{
    static char line[512];
    FILE *fp;
    int sizes[6], i, j;

    if (argc < 2) {
        fprintf(stderr, "usage: racecoord_test SCRIPT\n");
        return 2;
    }
    // Retail's sizes are printed for the port's, so no two may match.
    sizes[0] = (int)sizeof(struct Player);
    sizes[1] = (int)sizeof(Race);
    sizes[2] = (int)sizeof(World);
    sizes[3] = (int)sizeof(RaceCoordinator);
    sizes[4] = PAUSE_MENU_SIZE;
    sizes[5] = REPLAY_MANAGER_SIZE;
    for (i = 0; i < 6; i++)
        for (j = i + 1; j < 6; j++)
            if (sizes[i] == sizes[j]) {
                fprintf(stderr, "sizes %d and %d match\n", i, j);
                return 4;
            }

    gBCountFreeMemoryFn = s_free;
    gUnloadResourceFileFn = s_unload;
    gFindResourceFileByNameFn = s_find;
    gPauseMenuCtorFn = s_pause;
    gPauseMenuDestroyFn = s_pause_del;
    gReplayManagerCtorFn = s_replay;
    gReplayManagerDestroyFn = s_replay_del;
    gDisableRenderEggsFn = s_eggs;
    gCollisionSoundResetFn = s_coll;
    gSpeechFlushQueueFn = s_speech;
    gRCCleanUpAutoReplayFn = s_autoreplay;
    gChopperDestroyFn = s_heli_del;
    gKillAllActiveEffectsFn = s_kill;
    gJukeboxStopFn = s_jb;
    gSound3dOneshotResetFn = s_oneshot;
    gEndGameScreensDestroyFn = s_endgame_del;
    gCameraCoordinatorDeleteFn = s_ccdel;
    gPlayerCamSkipFE = &skipFE;
    {
        static const RCStateCallbackFn cbs[NUM_RCSTATES] = {
            cb0, cb1, cb2, cb3, cb4, cb5, cb6, cb7, cb8, cb9};

        memcpy(gRCStateCallbacks, cbs, sizeof cbs);
    }

    fp = fopen(argv[1], "r");
    if (fp == NULL) {
        perror(argv[1]);
        return 2;
    }
    while (fgets(line, sizeof line, fp)) {
        size_t len = strlen(line);

        while (len && (line[len - 1] == '\n' || line[len - 1] == '\r'))
            line[--len] = 0;
        if (!len)
            continue;
        if (line[0] == 'B' && line[1] == ' ') {
            printf("%s\n", line);
            reset();
            continue;
        }
        printf("> %.40s\n", line);
        op(line);
    }
    fclose(fp);
    return 0;
}
