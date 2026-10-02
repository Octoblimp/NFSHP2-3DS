// racecoord -- RaceCoordinator.obj from retail: the coordinator's lifetime
// and the message queue its states run on. Step 8e; racecoord.h has the
// map and docs/formats/race-coordinator.md the decode.
#include "racecoord.h"

#include <stddef.h>

#include "bmem.h"
#include "bslotpool.h"
#include "car.h"
#include "carinit.h"
#include "player.h"
#include "playercam.h"
#include "playerinit.h"
#include "racecore.h"
#include "raceinit.h"
#include "racerun.h"
#include "replay.h"
#include "track.h"
#include "trackflow.h"
#include "world.h"

// The pool every allocation here names, as retail's `new`s give it.
#define RC_POOL 16

// The queue's sixteen-byte slots, eight to a block.
#define RC_QUEUE_SLOTS 8

// Below this much free in pool 16 the constructor drops the prerace
// animation (`lui 0x0007; ori 0xcfff; slt`: unloaded at 0x7cfff and under).
#define RC_PRERACE_MIN_FREE 0x7d000

static const char kPreRaceAnim[] = "GLOBAL\\PRERACEANIM.LZC";

BSlotPool *RCQueuedMessageSlotPool;     // retail gp-22192, 0x00330240
struct PauseMenu *ThePauseMenu;         // retail gp-21064, 0x003306a8

void *(*gFindResourceFileByNameFn)(const char *name);
struct PauseMenu *(*gPauseMenuCtorFn)(void *mem);
void (*gPauseMenuDestroyFn)(struct PauseMenu *m, int32_t flags);
struct ReplayManager *(*gReplayManagerCtorFn)(void *mem);
void (*gReplayManagerDestroyFn)(struct ReplayManager *rm, int32_t flags);
void (*gDisableRenderEggsFn)(void);
void (*gCollisionSoundResetFn)(void);
void (*gSpeechFlushQueueFn)(void);
void (*gRCCleanUpAutoReplayFn)(RaceCoordinator *rc);
void (*gChopperDestroyFn)(struct Chopper *h, int32_t flags);
void (*gKillAllActiveEffectsFn)(void);
void (*gJukeboxStopFn)(void);
void (*gSound3dOneshotResetFn)(void);
void (*gEndGameScreensDestroyFn)(struct EndGameScreens *s, int32_t flags);

static void *find_prerace_anim(void)
{
    return gFindResourceFileByNameFn != NULL
               ? gFindResourceFileByNameFn(kPreRaceAnim) : NULL;
}

// ------------------------------------------------------------- the queue

// RCQueuedMessage's deleting destructor (0x0014cc28): ~bTNode does
// nothing, and operator delete (0x0014cd10) is bFree on the pool.
static void rc_message_delete(RCQueuedMessage *m)
{
    bSlotFree(RCQueuedMessageSlotPool, m);
}

// SendMessage and PostMessage's shared start: a slot from the pool, filled
// and put on the end of the list.
static void rc_message_append(RaceCoordinator *rc, RCMessage msg,
                              int32_t param)
{
    RCQueuedMessage *m = bSlotOMalloc(RCQueuedMessageSlotPool);
    bNode *list = &rc->RCQueuedMessageList;
    bNode *tail = list->prev;

    m->Param = param;
    tail->next = &m->Node;
    list->prev = &m->Node;
    m->Node.next = list;
    m->Msg = msg;
    m->Node.prev = tail;
}

void racecoordinator_send_message(RaceCoordinator *rc, RCMessage msg,
                                  int32_t param)
{
    rc_message_append(rc, msg, param);
    if (!rc->RCExecutingMessage)
        racecoordinator_execute_queued_messages(rc);
}

void racecoordinator_post_message(RaceCoordinator *rc, RCMessage msg,
                                  int32_t param)
{
    rc_message_append(rc, msg, param);
}

void racecoordinator_execute_queued_messages(RaceCoordinator *rc)
{
    bNode *list = &rc->RCQueuedMessageList;
    bNode *n = list->next;

    while (n != list) {
        RCQueuedMessage *m = (RCQueuedMessage *)(void *)n;
        RCStateCallbackFn cb;

        n->prev->next = n->next;
        n->next->prev = n->prev;
        rc->RCExecutingMessage = 1;
        if (m->Msg == RC_ACTIVATE)
            rc->CurrentRCState = m->Param;
        // Retail indexes its ten-entry table unchecked; a state past the
        // end runs nothing here.
        cb = (uint32_t)rc->CurrentRCState < (uint32_t)NUM_RCSTATES
                 ? gRCStateCallbacks[rc->CurrentRCState] : NULL;
        if (cb != NULL)
            cb(rc, m->Msg, m->Param);
        if (m->Msg == RC_UNACTIVATE)
            rc->CurrentRCState = RCSTATE_NONE;
        rc->RCExecutingMessage = 0;
        rc_message_delete(m);
        n = list->next;
    }
}

void racecoordinator_change_state(RaceCoordinator *rc, RCState state)
{
    racecoordinator_send_message(rc, RC_UNACTIVATE, rc->CurrentRCState);
    racecoordinator_send_message(rc, RC_ACTIVATE, state);
    racecoordinator_send_message(rc, RC_TICK, 0);
}

// ---------------------------------------------------------- the lifetime

RaceCoordinator *racecoordinator_construct(RaceCoordinator *rc)
{
    void *mem;

    rc->RCExecutingMessage = 0;
    rc->RCQueuedMessageList.next = &rc->RCQueuedMessageList;
    rc->CurrentRCState = RCSTATE_NONE;
    rc->BeforePauseRCState = RCSTATE_NONE;
    rc->DisplayingCountdownNumber = 0;
    rc->RCQueuedMessageList.prev = &rc->RCQueuedMessageList;

    if (gBCountFreeMemoryFn != NULL
        && gBCountFreeMemoryFn(RC_POOL) < RC_PRERACE_MIN_FREE) {
        void *f = find_prerace_anim();

        if (f != NULL && gUnloadResourceFileFn != NULL)
            gUnloadResourceFileFn(f);
    }

    RCQueuedMessageSlotPool = bNewSlotPool((int)sizeof(RCQueuedMessage),
                                           RC_QUEUE_SLOTS,
                                           "RCQueuedMessageSlotPool",
                                           RC_POOL);
    rc->pDemoCameraCoordinator = NULL;
    rc->pFlyByCameraCoordinator = NULL;
    rc->pPreRaceCameraCoordinator = NULL;
    rc->pEndGameScreens = NULL;
    rc->pReplayScreen = NULL;
    if (gPauseMenuCtorFn != NULL) {
        mem = bMalloc(PAUSE_MENU_SIZE, "PauseMenu", 0, RC_POOL);
        ThePauseMenu = gPauseMenuCtorFn(mem);
    }
    rc->PausedJoystickPort = -1;
    // RaceParameters::Print (0x001edf88) is empty in retail.
    racecoordinator_init_for_race(rc);
    rc->mpCameraMover = NULL;
    rc->mpCD = NULL;
    rc->mpFOVtable = NULL;
    rc->mpRoute = NULL;
    rc->mpBankVerts = NULL;
    rc->mpEyeVerts = NULL;
    rc->PostRaceWord140 = 0;
    return rc;
}

RaceCoordinator *racecoordinator_new(void)
{
    void *mem = bMalloc((int)sizeof(RaceCoordinator), "RaceCoordinator", 0,
                        RC_POOL);

    return racecoordinator_construct((RaceCoordinator *)mem);
}

void racecoordinator_destroy(RaceCoordinator *rc, int32_t flags)
{
    if (rc->CurrentRCState != RCSTATE_NONE)
        racecoordinator_change_state(rc, RCSTATE_NONE);
    racecoordinator_cleanup_after_race(rc);
    if (gRCCleanUpAutoReplayFn != NULL)
        gRCCleanUpAutoReplayFn(rc);
    if (ThePauseMenu != NULL && gPauseMenuDestroyFn != NULL)
        gPauseMenuDestroyFn(ThePauseMenu, 3);
    ThePauseMenu = NULL;
    bDeleteSlotPool(RCQueuedMessageSlotPool);
    // Retail's ~bTList then frees what is left on the list into the pool
    // it has just deleted. The slots went with the pool, so the port only
    // empties the list.
    rc->RCQueuedMessageList.next = &rc->RCQueuedMessageList;
    rc->RCQueuedMessageList.prev = &rc->RCQueuedMessageList;
    if (flags & 1)
        bFree(rc);
}

void racecoordinator_init_for_race(RaceCoordinator *rc)
{
    struct DriverInfo *d;
    void *mem;
    RCState state;
    eRaceStage stage;

    d = race_parameters_get_driver_info_by_driver_number(0);
    if ((d != NULL && d->EliminatedRank <= 0) || RaceParametersAIDemoMode) {
        mem = bMalloc((int)sizeof(struct Player), "Player1", 0, RC_POOL);
        player_init((struct Player *)mem, 0, 0);
    }
    d = race_parameters_get_driver_info_by_driver_number(1);
    if (d != NULL && d->EliminatedRank <= 0) {
        mem = bMalloc((int)sizeof(struct Player), "Player2", 0, RC_POOL);
        player_init((struct Player *)mem, 1, 1);
    }
    (void)track_get_info(RaceParametersTrackNumber);

    if (gReplayManagerCtorFn != NULL) {
        mem = bMalloc(REPLAY_MANAGER_SIZE, "ReplayManager", 0, RC_POOL);
        pReplayManager = gReplayManagerCtorFn(mem);
    }
    mem = bMalloc((int)sizeof(Race), "Race", 0, RC_POOL);
    pCurrentRace = race_construct((Race *)mem);
    // World's constructor sets pCurrentWorld itself.
    mem = bMalloc((int)sizeof(World), "World", 0, RC_POOL);
    world_init((World *)mem);
    racecoordinator_init_cars(rc);
    racecoordinator_init_players(rc);

    if (RaceParametersAIDemoMode) {
        state = RCSTATE_AI_DEMO_MODE;
        if (gDisableRenderEggsFn != NULL)
            gDisableRenderEggsFn();
        stage = RACE_STAGE_RACING;
    } else if (RaceParametersReplayDemoMode) {
        state = RCSTATE_REPLAY_DEMO_MODE;
        stage = RACE_STAGE_RACING;
    } else if (gPlayerCamSkipFE != NULL && *gPlayerCamSkipFE) {
        state = RCSTATE_RACE_IN_PROGRESS;
        stage = RACE_STAGE_RACING;
    } else if (RaceParametersBeACop || find_prerace_anim() != NULL) {
        state = RCSTATE_CAMERA_FLYBY;
        stage = RACE_STAGE_FLYBY;
    } else {
        state = RCSTATE_RACE_IN_PROGRESS;
        stage = RACE_STAGE_COUNTDOWN;
    }

    race_init(pCurrentRace, stage);
    race_setup_ghost_cars(pCurrentRace);
    set_ai_driver_modes_from_players();
    if (gCollisionSoundResetFn != NULL)
        gCollisionSoundResetFn();
    if (gSpeechFlushQueueFn != NULL)
        gSpeechFlushQueueFn();
    pRaceCoordinator = rc;
    racecoordinator_change_state(rc, state);
}

void racecoordinator_cleanup_after_race(RaceCoordinator *rc)
{
    if (rc->pPreRaceCameraCoordinator != NULL) {
        if (gCameraCoordinatorDeleteFn != NULL)
            gCameraCoordinatorDeleteFn(rc->pPreRaceCameraCoordinator);
        rc->pPreRaceCameraCoordinator = NULL;
    }
    if (rc->pFlyByCameraCoordinator != NULL) {
        if (gCameraCoordinatorDeleteFn != NULL)
            gCameraCoordinatorDeleteFn(rc->pFlyByCameraCoordinator);
        rc->pFlyByCameraCoordinator = NULL;
    }
    world_flush_collisions(pCurrentWorld);
    racecoordinator_cleanup_players(rc);
    racecoordinator_cleanup_cars(rc);
    if (gKillAllActiveEffectsFn != NULL)
        gKillAllActiveEffectsFn();
    if (pCurrentRace != NULL)
        race_destroy(pCurrentRace, 3);
    pCurrentRace = NULL;
    if (pCurrentWorld != NULL)
        world_destroy(pCurrentWorld, 3);
    pCurrentWorld = NULL;
    if (gJukeboxStopFn != NULL)
        gJukeboxStopFn();
    if (gSound3dOneshotResetFn != NULL)
        gSound3dOneshotResetFn();
    if (pReplayManager != NULL && gReplayManagerDestroyFn != NULL)
        gReplayManagerDestroyFn(pReplayManager, 3);
    pReplayManager = NULL;
    if (rc->pEndGameScreens != NULL) {
        if (gEndGameScreensDestroyFn != NULL)
            gEndGameScreensDestroyFn(rc->pEndGameScreens, 3);
        rc->pEndGameScreens = NULL;
    }
    // Last to first, the count re-read after each: the destructor takes
    // the player out of the tables. Retail re-reads it only after a
    // player it destroyed, so a NULL entry would spin there.
    {
        int32_t n = PlayerNumPlayers;

        while (n != 0) {
            struct Player *p = PlayerPlayersByIndex[n - 1];

            if (p != NULL) {
                player_destroy(p, 3);
                n = PlayerNumPlayers;
            }
        }
    }
}

void racecoordinator_cleanup_players(RaceCoordinator *rc)
{
    int32_t i;

    (void)rc;
    for (i = 0; i < PlayerNumPlayers; i++)
        player_cleanup_after_race(PlayerPlayersByIndex[i]);
}

void racecoordinator_cleanup_cars(RaceCoordinator *rc)
{
    World *w = pCurrentWorld;

    (void)rc;
    while (w->CarList.next != (void *)&w->CarList) {
        Car *c = (Car *)w->CarList.next;

        c->Link.next->prev = c->Link.prev;
        c->Link.prev->next = c->Link.next;
        car_destruct(c, 3);
        w = pCurrentWorld;
    }
    if (w->Helicopter != NULL) {
        if (gChopperDestroyFn != NULL)
            gChopperDestroyFn(w->Helicopter, 3);
        pCurrentWorld->Helicopter = NULL;
    }
}

// ------------------------------------------------- the drivers and styles

struct DriverInfo *race_parameters_get_driver_info_by_driver_number(
    int32_t number)
{
    int32_t i;

    for (i = 0; i < RaceParametersNumDriverInfo; i++) {
        if (race_parameters_get_driver_info(i)->UniqueDriverNumber == number)
            return &RaceParametersDriverInfo[i];
    }
    return NULL;
}

void set_ai_driver_modes_from_players(void)
{
    World *w;
    int32_t i;

    if (pCurrentWorld == NULL || pCurrentRace == NULL)
        return;
    if (RaceParametersNumPlayerCars == 2) {
        struct Player *a = PlayerPlayersByNumber[0];
        struct Player *b = PlayerPlayersByNumber[1];
        int32_t posA = race_get_racing_car(pCurrentRace, a->MyCar)->RacePosition;
        int32_t posB = race_get_racing_car(pCurrentRace, b->MyCar)->RacePosition;
        int32_t leader = a->PlayerSettings.DrivingStyle;
        int32_t trailer = b->PlayerSettings.DrivingStyle;
        int32_t half;

        if (posB < posA) {
            int32_t t = leader;

            leader = trailer;
            trailer = t;
        }
        // The middle of the AI field, moved one back for each player at or
        // ahead of it.
        half = RaceParametersNumAICars / 2;
        if (!(half < posA))
            half++;
        if (!(half < posB))
            half++;
        w = pCurrentWorld;
        for (i = 0; i < w->CopCarPos - w->AICarPos; i++) {
            Car *c = w->CarTable[w->AICarPos + i];

            if (half < race_get_racing_car(pCurrentRace, c)->RacePosition)
                c->State.DriverMode = trailer;
            else
                c->State.DriverMode = leader;
            w = pCurrentWorld;
        }
    } else {
        int32_t style = PlayerPlayersByIndex[0]->PlayerSettings.DrivingStyle;

        w = pCurrentWorld;
        for (i = 0; i < w->CopCarPos - w->AICarPos; i++)
            w->CarTable[w->AICarPos + i]->State.DriverMode = style;
    }
}
