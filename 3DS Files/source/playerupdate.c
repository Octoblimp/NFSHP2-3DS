// playerupdate -- the Player's frame outside the game state. See
// playerupdate.h.

#include "playerupdate.h"

#include "bmem.h"
#include "joyevent.h"
#include "joystick.h"
#include "player.h"
#include "playercam.h"
#include "playerinit.h"
#include "race.h"
#include "rcstates.h"
#include "realtime.h"

struct CountdownCameraCoordinator *(*gCountdownCameraCoordinatorFn)(
    void *mem, int32_t viewID, struct Player *p);
void (*gPlayerUpdateHudFn)(struct Player *p);

// gp-30260: WorldTimer's tick, 1/4000 s.
#define PLAYER_TIMER_SECONDS 0.00025f

// NisManager's word at +68, which retail reads without testing the
// manager, the player's own one; the other player's manager it tests. The
// port has no manager until NisManager is ported, and reads none as not
// playing.
static int nis_playing(const struct NisManager *m)
{
    return m != NULL && gNisManagerIsPlayingFn != NULL
        && gNisManagerIsPlayingFn(m) != 0;
}

static int has_camera(const struct Player *p)
{
    return p->pCameraMover != NULL || p->pRVMCameraMover != NULL
        || p->pDemoCameraCoordinator != NULL
        || p->pCountdownCameraCoordinator != NULL
        || p->pNisCameraCoordinator != NULL;
}

// Once the line has outlived its lifetime: the elapsed WorldTimer ticks,
// unsigned, are converted signed (`cvt.s.w`).
static void retire_driving_line(struct Player *p)
{
    const VisibleDrivingLineHead *l =
        (const VisibleDrivingLineHead *)(const void *)p->pVisibleDrivingLine;
    float elapsed;

    if (l == NULL)
        return;
    elapsed = (float)(int32_t)((uint32_t)WorldTimer - (uint32_t)l->StartTime)
            * PLAYER_TIMER_SECONDS;
    if (!(l->Lifetime < elapsed))
        return;
    if (gVisibleDrivingLineDeleteFn != NULL)
        gVisibleDrivingLineDeleteFn(p->pVisibleDrivingLine);
    p->pVisibleDrivingLine = NULL;
}

// A player with no camera and no NIS playing: the countdown cameras while
// the race counts down, the drive camera after. With Be A Cop there are no
// countdown cameras, and the drive camera waits while the other player's
// NIS plays.
static void choose_camera(struct Player *p)
{
    struct Player *other = PlayerPlayersByNumber[0] == p
                         ? PlayerPlayersByNumber[1] : PlayerPlayersByNumber[0];

    if (has_camera(p) || nis_playing(p->pNisManager))
        return;
    if (race_get_race_stage(pCurrentRace) == RACE_STAGE_COUNTDOWN
        && !TheRaceParameters.BeACop) {
        player_begin_countdown_cameras(p);
        return;
    }
    if (TheRaceParameters.BeACop && other != NULL
        && nis_playing(other->pNisManager))
        return;
    player_change_camera_mover(p, CM_DRIVE, 0);
}

void player_update_non_game_state(struct Player *p)
{
    if (pRaceCoordinator->CurrentRCState == RCSTATE_RACE_IN_PROGRESS) {
        int32_t type = GetJoystickType(p->JoyPort);

        if (!IsJoystickPluggedIn(p->JoyPort) || type != p->JoyType)
            racecoordinator_request_pause(pRaceCoordinator, p->JoyPort);
    } else {
        p->JoyType = GetJoystickType(p->JoyPort);
    }

    if (pRaceCoordinator->CurrentRCState == RCSTATE_RACE_IN_PROGRESS)
        retire_driving_line(p);

    if (pRaceCoordinator->CurrentRCState == RCSTATE_RACE_IN_PROGRESS) {
        const CameraCoordinatorHead *c;

        choose_camera(p);
        c = (const CameraCoordinatorHead *)(const void *)
            p->pCountdownCameraCoordinator;
        if (c != NULL && c->pCameraMover == NULL)
            player_change_camera_mover(p, CM_DRIVE, 0);
    }

    if (gPlayerUpdateHudFn != NULL)
        gPlayerUpdateHudFn(p);
}

void update_players_non_game_state(void)
{
    int32_t i;

    for (i = 0; i < PlayerNumPlayers; i++)
        player_update_non_game_state(PlayerPlayersByIndex[i]);
}

void player_begin_countdown_cameras(struct Player *p)
{
    void *mem;

    if (p->pCountdownCameraCoordinator != NULL)
        return;
    player_change_camera_mover(p, CM_NONE, 0);
    if (gCountdownCameraCoordinatorFn == NULL)
        return;
    mem = bMalloc(36, "CountdownCameraCoordinator", 0, 16);
    p->pCountdownCameraCoordinator =
        gCountdownCameraCoordinatorFn(mem, p->ViewID, p);
}
