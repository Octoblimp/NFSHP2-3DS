// rcpost -- the race coordinator's pause and post-race. Step 8g; rcpost.h
// has the map and docs/formats/race-coordinator.md the decode.
#include "rcpost.h"

#include <stddef.h>

#include "bmem.h"
#include "cammover.h"
#include "player.h"
#include "playercam.h"
#include "race.h"
#include "rcstates.h"
#include "realtime.h"
#include "replay.h"
#include "world.h"

// The pool and the file every allocation here names.
#define RC_POOL 16
static const char kRCFile[] = "..\\indep\\src\\racecoordinator.cpp";
#define RC_POST_ACTIVATE_LINE     2361
#define RC_POST_TICK_LINE         2396
#define RC_POST_SKIP_REPLAY_LINE  2418

// The worst FinishPosition the post-race's search starts from.
#define RC_NO_POSITION 8

void (*gChangeToScreenFn)(const char *name, int32_t push);
void (*gPauseMenuEnterPauseFn)(struct PauseMenu *m, JoystickPort port);
void (*gPauseMenuExitPauseFn)(struct PauseMenu *m);
void (*gPlayerClearHudAnimationsFn)(struct Player *p);
void (*gFEDTheRaceWasQuitFn)(void);
void (*gFEDTheRaceWasRestartedFn)(void);
void (*gSoundMuteReplayFn)(int32_t on);
void (*gReplayBeginRaceHighlightsFn)(struct ReplayManager *rm);
void (*gReplayBeginNextRaceHighlightFn)(struct ReplayManager *rm);
int32_t (*gReplayMuteHighlightsFn)(const struct ReplayManager *rm);
int32_t (*gReplayEndCurrentHighlightTimeFn)(const struct ReplayManager *rm);
void (*gEndGameScreensResumeFn)(struct EndGameScreens *s);
void (*gEndGameScreensSuspendFn)(struct EndGameScreens *s);
const TransientStatsElement *(*gTransientStatsGetDriverFn)(
    int32_t driverNumber);
void (*gRestoreTypeChangedHandlersFn)(void);

// ---------------------------------------------------------- the helpers

static void mute(int32_t on)
{
    if (gSoundMuteFn != NULL)
        gSoundMuteFn(on);
}

static void mute_replay(int32_t on)
{
    if (gSoundMuteReplayFn != NULL)
        gSoundMuteReplayFn(on);
}

static void change_to_screen(const char *name, int32_t push)
{
    if (gChangeToScreenFn != NULL)
        gChangeToScreenFn(name, push);
}

static void delete_camera(void *coord)
{
    if (gCameraCoordinatorDeleteFn != NULL)
        gCameraCoordinatorDeleteFn(coord);
}

static void begin_next_race_highlight(struct ReplayManager *rm)
{
    if (gReplayBeginNextRaceHighlightFn != NULL)
        gReplayBeginNextRaceHighlightFn(rm);
}

// ChangeState(NONE), then the message sent on: the post-race's and the
// pause's way out of a race.
static void leave_for_none(RaceCoordinator *rc, RCMessage msg, int32_t param)
{
    racecoordinator_change_state(rc, RCSTATE_NONE);
    racecoordinator_send_message(rc, msg, param);
}

// A new demo camera on the car of the player the post-race follows, from
// the World's CarTable, at `line`. With no constructor nothing is
// allocated and the field is NULL.
static void post_race_demo_camera(RaceCoordinator *rc, int32_t line)
{
    World *w;
    void *mem;

    if (gDemoCameraCoordinatorCtorFn == NULL) {
        rc->pDemoCameraCoordinator = NULL;
        return;
    }
    mem = bMalloc(DEMO_CAMERA_COORDINATOR_SIZE, kRCFile, line, RC_POOL);
    w = pCurrentWorld;
    rc->pDemoCameraCoordinator = gDemoCameraCoordinatorCtorFn(
        mem, 1, w != NULL ? w->CarTable[rc->PostRacePlayerNumber] : NULL);
}

// The demo camera deleted, as the TICK and SKIP_REPLAY do before they make
// the next: retail leaves the field for the new camera to overwrite.
static void delete_demo_camera(RaceCoordinator *rc)
{
    if (rc->pDemoCameraCoordinator != NULL)
        delete_camera(rc->pDemoCameraCoordinator);
}

// ------------------------------------------------------- the Player calls

void player_begin_pause(struct Player *p)
{
    if (gPlayerClearHudAnimationsFn != NULL)
        gPlayerClearHudAnimationsFn(p);
}

void player_end_pause(struct Player *p)
{
    p->JoyType = GetJoystickType(p->JoyPort);
}

void tell_players_to_pause(void)
{
    int32_t i;

    for (i = 0; i < PlayerNumPlayers; i++)
        player_begin_pause(PlayerPlayersByIndex[i]);
}

void tell_players_to_unpause(void)
{
    int32_t i;

    for (i = 0; i < PlayerNumPlayers; i++)
        player_end_pause(PlayerPlayersByIndex[i]);
}

// ------------------------------------------------------------ RCSTATE_PAUSE

int32_t rc_state_pause_callback(RaceCoordinator *rc, RCMessage msg,
                                int32_t param)
{
    switch (msg) {
    case RC_ACTIVATE:
        // World::BeginPause (0x0014d668) comes first; it is empty.
        tell_players_to_pause();
        if (gPauseMenuEnterPauseFn != NULL)
            gPauseMenuEnterPauseFn(ThePauseMenu, rc->PausedJoystickPort);
        change_to_screen(RC_PAUSE_MENU_SCREEN, 1);
        mute(1);
        return 1;
    case RC_UNACTIVATE:
        change_to_screen(NULL, 0);
        if (gPauseMenuExitPauseFn != NULL)
            gPauseMenuExitPauseFn(ThePauseMenu);
        tell_players_to_unpause();
        // Then World::EndPause (0x0014d670) when there is a World; it is
        // empty.
        return 1;
    case RC_TICK:
        return 1;
    case RC_REQUEST_UNPAUSE:
        switch (param) {
        case UNPAUSE_REASON_RESUME_RACE:
            mute(0);
            racecoordinator_change_state(rc, rc->BeforePauseRCState);
            break;
        case UNPAUSE_REASON_INSTANT_REPLAY:
            racecoordinator_change_state(rc, RCSTATE_INSTANT_REPLAY);
            break;
        case UNPAUSE_REASON_QUIT_RACE:
            if (gFEDTheRaceWasQuitFn != NULL)
                gFEDTheRaceWasQuitFn();
            // Retail's active demo disc records its end reason (5) here.
            // It is never active on the retail disc.
            leave_for_none(rc, RC_QUIT_RACE, 0);
            break;
        case UNPAUSE_REASON_RESTART_RACE:
            leave_for_none(rc, RC_RESTART_RACE, 0);
            break;
        default:
            break;
        }
        return 1;
    default:
        return 0;
    }
}

// --------------------------------------------------------- RCSTATE_POSTRACE

static void post_race_activate(RaceCoordinator *rc)
{
    struct ReplayManager *rm;
    int32_t i, best;

    for (i = 0; i < PlayerNumPlayers; i++)
        player_change_camera_mover(PlayerPlayersByIndex[i], CM_NONE, 0);
    mute(0);
    if (gSpeechFlushQueueFn != NULL)
        gSpeechFlushQueueFn();
    // Retail reads the word without a ReplayManager test.
    rm = pReplayManager;
    if (rm != NULL && gReplayMuteHighlightsFn != NULL
        && gReplayMuteHighlightsFn(rm))
        mute_replay(1);
    if (gReplayBeginRaceHighlightsFn != NULL)
        gReplayBeginRaceHighlightsFn(pReplayManager);
    if (gEndGameScreensResumeFn != NULL)
        gEndGameScreensResumeFn(rc->pEndGameScreens);

    // With two players, the one who finished best; ties keep the first.
    rc->PostRacePlayerNumber = 0;
    best = RC_NO_POSITION;
    if (PlayerNumPlayers >= 2) {
        for (i = 0; i < PlayerNumPlayers; i++) {
            struct Player *p = PlayerPlayersByIndex[i];
            const TransientStatsElement *d =
                gTransientStatsGetDriverFn != NULL
                    ? gTransientStatsGetDriverFn(p->PlayerNumber) : NULL;

            if (d != NULL && d->FinishPosition < best) {
                rc->PostRacePlayerNumber = p->PlayerNumber;
                best = d->FinishPosition;
            }
        }
    }
    // Retail makes the camera over any it already has.
    post_race_demo_camera(rc, RC_POST_ACTIVATE_LINE);
}

int32_t rc_state_post_race_callback(RaceCoordinator *rc, RCMessage msg,
                                    int32_t param)
{
    switch (msg) {
    case RC_ACTIVATE:
        post_race_activate(rc);
        return 1;
    case RC_UNACTIVATE:
        if (gEndGameScreensSuspendFn != NULL)
            gEndGameScreensSuspendFn(rc->pEndGameScreens);
        delete_demo_camera(rc);
        rc->PostRacePlayerNumber = 0;
        rc->pDemoCameraCoordinator = NULL;
        if (gRestoreTypeChangedHandlersFn != NULL)
            gRestoreTypeChangedHandlersFn();
        return 1;
    case RC_TICK: {
        // Retail reads the ReplayManager here unchecked.
        struct ReplayManager *rm = pReplayManager;

        if (rm == NULL || gReplayEndCurrentHighlightTimeFn == NULL
            || WorldLoopCounter < gReplayEndCurrentHighlightTimeFn(rm))
            return 1;
        begin_next_race_highlight(rm);
        delete_demo_camera(rc);
        post_race_demo_camera(rc, RC_POST_TICK_LINE);
        return 1;
    }
    case RC_SKIP_REPLAY:
        mute_replay(1);
        begin_next_race_highlight(pReplayManager);
        delete_demo_camera(rc);
        post_race_demo_camera(rc, RC_POST_SKIP_REPLAY_LINE);
        return 1;
    case RC_START_REPLAY:
        racecoordinator_change_state(rc, RCSTATE_INSTANT_REPLAY);
        return 1;
    case RC_RESTART_RACE:
        if (gFEDTheRaceWasRestartedFn != NULL)
            gFEDTheRaceWasRestartedFn();
        leave_for_none(rc, RC_RESTART_RACE, 0);
        return 1;
    case RC_NEXT_RACE:
        leave_for_none(rc, RC_NEXT_RACE, param);
        return 1;
    case RC_QUIT_RACE:
        leave_for_none(rc, RC_QUIT_RACE, 0);
        return 1;
    case RC_TAKE_AUTOSNAPSHOT:
        return 1;
    default:
        return 0;
    }
}
