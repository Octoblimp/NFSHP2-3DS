// playernis -- a player's NIS and game state. See playernis.h.

#include "playernis.h"

#include <math.h>
#include <stddef.h>

#include "average.h"
#include "bmath.h"
#include "cammover.h"
#include "car.h"
#include "carstate.h"
#include "cartypeinfo.h"
#include "collisionbody.h"
#include "copmanager.h"
#include "drivecam.h"
#include "eefpu.h"
#include "hudnis.h"
#include "nisinfo.h"
#include "nisoverlay.h"
#include "player.h"
#include "playercam.h"
#include "playerzone.h"
#include "pursuit.h"
#include "race.h"
#include "racecoord.h"
#include "raceparams.h"
#include "realdriver.h"
#include "realtime.h"
#include "sundraw.h"
#include "timer.h"
#include "trackroute.h"

struct NisCameraCoordinator *(*gNisCreateCameraCoordinatorFn)(
    NisManager *m, int32_t view);

// mph a metre a second (gp-30236 and its copies), degrees a radian
// (gp-30228), seconds a tick (gp-30224 and its copies).
#define MPH_PER_MPS     2.237f
#define DEG_PER_RAD     57.2957763671875f
#define SECONDS_PER_TICK 0.00025f

// The angles DetectWrongWay folds: half a turn, and 10 and 110 degrees.
#define HALF_TURN       32768u
#define WRONG_WAY_SLACK 1820u
#define WRONG_WAY_LIMIT 20024u

// An instant or automatic replay, the post-race, or (out of line) the
// replay demo: the test PlayNextNis, ServiceNis and UpdateGameState make.
static int32_t replaying(void)
{
    RCState s = pRaceCoordinator->CurrentRCState;

    return s == RCSTATE_INSTANT_REPLAY || s == RCSTATE_POSTRACE
        || s == RCSTATE_AUTO_REPLAY
        || racecoordinator_is_replay_demo_mode(pRaceCoordinator);
}

// WorldTimer less a stamp, the words subtracted and read signed.
static int32_t ticks_since(const Timer *t)
{
    return (int32_t)((uint32_t)WorldTimer - t->PackedTime);
}

// Player::IsNisPlaying, 0x00176520: the manager's Playing, read in place.
static int32_t nis_playing(const struct Player *p)
{
    return p->pNisManager != NULL && p->pNisManager->Playing != 0;
}

void player_create_random_nis_array(struct Player *p, int32_t type)
{
    int32_t pool[32];
    int32_t *nis, *cam;
    int32_t n, i, k;

    n = get_num_nis_info(type);
    for (i = 0; i < n; i++) {
        NisInfo *info = get_nis_info_by_type(i, type);

        if (info == NULL)
            info = get_nis_info_by_type(0, NIS_TYPE_TICKET);
        pool[i] = info->NisNumber;
    }
    if (type != NIS_TYPE_TICKET) {
        nis = p->ArrestNisNumbers;
        cam = p->ArrestCameraNumbers;
    } else {
        nis = p->TicketNisNumbers;
        cam = p->TicketCameraNumbers;
    }

    for (k = 0; k < n; k++) {
        int32_t r = bRandomI(n - k, &bDefaultSeed);
        int32_t left = r + 1;
        int32_t pick = -1;

        // The r'th of the pool's numbers still there, from 0.
        for (i = 0; i < n; i++) {
            if (pool[i] != -1)
                left--;
            if (left == 0) {
                pick = i;
                break;
            }
        }
        // Retail reads the word before the pool when nothing is found,
        // which a draw under the count left cannot do.
        if (pick < 0)
            continue;
        nis[k] = pool[pick];
        pool[pick] = -1;
        cam[k] = bRandomI(get_nis_info(nis[k])->NumCameras, &bDefaultSeed);
    }
}

int32_t player_play_next_nis(struct Player *p, struct Car *car,
                             struct Car *cop, void (*done)(int32_t),
                             int32_t param)
{
    struct Player *other;
    int32_t tickets, othercam, cam, nis, ticket;

    p->NisFinishedCallback = done;
    p->NisFinishedCallbackParam = (uint32_t)param;
    tickets = copmanager_get_num_tickets(pCopManager, car);
    player_clear_zone(p, 1);
    if (cop->pPlayer != NULL && gRadialBlurOffFn != NULL)
        gRadialBlurOffFn(cop->pPlayer->PlayerNumber);
    car_stop_blinking(car);
    bResetGlare = 1;
    if (p->ArrestNisIndex < 0)
        p->ArrestNisIndex = 0;
    if (p->TicketNisIndex < 0)
        p->TicketNisIndex = 0;

    other = p != PlayerPlayersByIndex[0] ? PlayerPlayersByIndex[0]
                                          : PlayerPlayersByIndex[1];
    othercam = -1;
    if (other != NULL && other->pNisManager != NULL
        && other->pNisManager->Playing != 0)
        othercam = other->pNisManager->CamNumber;

    ticket = 1;
    if (!race_parameters_is_free_run(&TheRaceParameters)
        && tickets >= TheRaceParameters.nNumTicketsBeforeArrest) {
        ticket = 0;
        cam = p->ArrestCameraNumbers[p->TicketNisIndex];
        nis = p->ArrestNisNumbers[p->TicketNisIndex];
    } else {
        cam = p->TicketCameraNumbers[p->TicketNisIndex];
        nis = p->TicketNisNumbers[p->TicketNisIndex];
    }
    if (cam == othercam)
        cam = (cam + 1) % get_nis_info(nis)->NumCameras;

    if (p->pNisManager == NULL) {
        // The port's: nothing to play, so the NIS is over already.
        p->NisFinishedCallback = NULL;
        p->NisFinishedCallbackParam = 0;
        if (done != NULL)
            done(param);
        return 1;
    }
    nismanager_start(p->pNisManager, nis, cam, car, cop);
    if (ticket)
        nisoverlay_start_ticket(&p->mFlailerNIS);
    else
        nisoverlay_start_arrest(&p->mFlailerNIS);
    if (!replaying() && gNisCreateCameraCoordinatorFn != NULL) {
        player_change_camera_mover(p, CM_NONE, 0);
        p->pNisCameraCoordinator =
            gNisCreateCameraCoordinatorFn(p->pNisManager, p->ViewID);
    }
    return 1;
}

void player_service_nis(struct Player *p)
{
    NisManager *m = p->pNisManager;

    if (m == NULL || m->Playing == 0)
        return;
    if (nismanager_allow_debug_looping(m)) {
        player_change_camera_mover(p, CM_NONE, 0);
        p->pNisCameraCoordinator = gNisCreateCameraCoordinatorFn != NULL
            ? gNisCreateCameraCoordinatorFn(m, p->ViewID) : NULL;
    }
    m = p->pNisManager;
    if (m->Playing == 0 || WorldTimeFrames < m->EndTime)
        return;
    if (!replaying())
        player_change_camera_mover(p, CM_DRIVE, 0);
    nismanager_stop(p->pNisManager);
    if (p->NisFinishedCallback != NULL) {
        p->NisFinishedCallback((int32_t)p->NisFinishedCallbackParam);
        p->NisFinishedCallback = NULL;
        p->NisFinishedCallbackParam = 0;
    }
    nismanager_unload(p->pNisManager);
    nisoverlay_finish(&p->mFlailerNIS);
}

// The angle between two headings, folded to 0 .. HALF_TURN, and the slack
// added when the flag was up.
static uint32_t fold(uint32_t a, uint32_t b, int32_t was)
{
    uint32_t d = (a - b) & 0xffffu;

    if (d > HALF_TURN)
        d = (0u - d) & 0xffffu;
    if (was)
        d = (d + WRONG_WAY_SLACK) & 0xffffu;
    return d;
}

int32_t player_detect_wrong_way(struct Player *p, int32_t was)
{
    struct Car *car = p->MyCar;
    const bVector2 *dir = &car->TheTrackPathCoordinate.PathDirection;
    uint32_t path = (uint32_t)bATan(dir->x, dir->y) & 0xffffu;

    if (fold(path, car->State.Angle, was) < WRONG_WAY_LIMIT)
        return 0;
    if (fabsf(car->State.ForwardSpeed * MPH_PER_MPS) > 10.0f) {
        uint32_t heading = (uint32_t)bATan(car->State.Velocity.x,
                                           car->State.Velocity.y);

        if (fold(path, heading, was) < WRONG_WAY_LIMIT)
            return 0;
    } else if (!was) {
        return 0;
    }
    if (was)
        return 1;
    return car->State.nWheelsTouchingGround > 3;
}

int32_t player_is_allowed_to_reset(struct Player *p)
{
    int32_t zone = p->nZoneCurrent;
    float t;

    if (PlayerZoneBlocksRequest[zone] != 0 && zone != 6 && zone != 7)
        return 0;
    if (nis_playing(p))
        return 0;
    if (p->MyCar->State.VelocityMagnitude * MPH_PER_MPS > 60.0f)
        return 0;
    if (TheRaceParameters.BeACop == 0)
        return 1;
    t = (float)(int32_t)pCurrentRace->RaceTime.PackedTime * SECONDS_PER_TICK;
    return !(t < 5.0f);
}

void player_selected_reset(struct Player *p)
{
    CameraMover *m;

    p->TimeToDisplayResetPrompt.PackedTime = 0;
    p->LastTimeCarInTrouble.PackedTime = 0;
    m = p->pCameraMover;
    if (m != NULL) {
        m->vtbl->ResetState(m);
        m = p->pCameraMover;
        if (m != NULL && m->Type == CM_DRIVE)
            ((DriveCameraMover *)(void *)m)->DesiredLookBackParam =
                p->bLookBack ? 1.0f : 0.0f;
    }
    p->HangTime = 0.0f;
}

void player_choose_to_display_reset(struct Player *p)
{
    struct Car *car = p->MyCar;
    float speed = car->State.VelocityMagnitude * MPH_PER_MPS;
    float hit = (float)ticks_since(
                    &car->pDynamicCollisionBody->LastPenetrationTime)
                * SECONDS_PER_TICK;
    float dt;
    Timer t;

    if (speed > 60.0f && hit < 3.0f) {
        float yaw = carstate_get_yaw_always(&car->State);

        if (fabsf(yaw * DEG_PER_RAD) > 50.0f)
            p->LastTimeCarInTrouble.PackedTime = (uint32_t)WorldTimer;
    }

    dt = (float)ticks_since(&p->tTroubleSpeedTimer) * SECONDS_PER_TICK;
    if (dt > 0.5f) {
        float last = p->fTroubleSpeed;
        float rate = (speed - last) / dt;

        if (last > 60.0f && hit < 3.0f && rate < -70.0f)
            p->LastTimeCarInTrouble.PackedTime = (uint32_t)WorldTimer;
        p->tTroubleSpeedTimer.PackedTime = (uint32_t)WorldTimer;
        p->fTroubleSpeed = speed;
    }

    // Upside down: the body's up has gone below the horizon.
    if (speed < 10.0f && car->State.BodyMatrix.v2.z < 0.0f)
        p->LastTimeCarInTrouble.PackedTime = (uint32_t)WorldTimer;

    timer_set_time(&t, 5.0f);
    if ((int32_t)t.PackedTime < ticks_since(&p->LastTimeCarInTrouble))
        p->LastTimeCarInTrouble.PackedTime = 0;

    if (timer_is_valid(&p->LastTimeCarInTrouble)
        && player_is_allowed_to_reset(p)
        && (pCopManager == NULL
            || copmanager_is_being_pursued(pCopManager, car) == NULL)) {
        if (!timer_is_valid(&p->TimeToDisplayResetPrompt))
            p->LastTimeCarInTrouble.PackedTime = 0;
        return;
    }
    if (timer_is_valid(&p->TimeToDisplayResetPrompt)) {
        int32_t since = ticks_since(&p->TimeToDisplayResetPrompt);

        timer_set_time(&t, 3.0f);
        if ((int32_t)t.PackedTime < since)
            p->TimeToDisplayResetPrompt.PackedTime = 0;
    }
}

void player_update_game_state(struct Player *p)
{
    RCState s;

    player_service_nis(p);
    p->bWrongWay = player_detect_wrong_way(p, p->bWrongWay) != 0;
    player_choose_to_display_reset(p);
    // Retail then reads the racing car's word at +18 and the camera
    // mover's type, and uses neither.

    s = pRaceCoordinator->CurrentRCState;
    if (s == RCSTATE_RACE_IN_PROGRESS || replaying()) {
        Timer t;

        timer_set_time(&t, WorldTimeElapsed);
        p->tAverageSpeedTimer.PackedTime -= t.PackedTime;
        if ((float)(int32_t)p->tAverageSpeedTimer.PackedTime
            * SECONDS_PER_TICK < 0.0f) {
            struct Car *car = p->MyCar;
            TrackRoute *route = car_get_route(car, 1);

            if (route != NULL) {
                int32_t line = car->pCarTypeInfo->CarClass * 2;
                TrackRoutePoint *pt = car_get_route_point(car, 1);
                float f = 1.0f;

                if (pt != NULL
                    && (route->DrivingLineInfoTable[line].Flags
                        & (DLI_IS_VALID | DLI_IS_FAKE)) != 0) {
                    // The byte as 16.16, which is the byte.
                    float limit =
                        (float)(int32_t)((uint32_t)pt->DrivingLineSpeeds[line]
                                         << 16)
                        * (1.0f / 65536.0f);

                    f = ee_div(car->State.VelocityMagnitude, limit);
                }
                average_record(p->pAverageSpeedRatio, f);
                p->fMaxSpeedRatio = fmaxf(p->fMaxSpeedRatio,
                                          p->pAverageSpeedRatio->fAverage);
            }
            // (int)4000.5, gp-30264: a second.
            p->tAverageSpeedTimer.PackedTime = (uint32_t)ee_trunc_w(4000.5f);
        }
    }

    if (p->fFreezeZoneDelayTimer > 0.0f) {
        p->fFreezeZoneDelayTimer -= WorldTimeElapsed;
        if (p->fFreezeZoneDelayTimer <= 0.0f) {
            p->fFreezeZoneDelayTimer = 0.0f;
            if (player_request_zone(p, 1, 0, 1, 1)
                && gCollisionSoundPlayBustRoadBlockFn != NULL)
                gCollisionSoundPlayBustRoadBlockFn(
                    &p->MyCar->State.Position);
        }
    }
}

void player_update_players_game_state(void)
{
    int32_t i;

    for (i = 0; i < PlayerNumPlayers; i++)
        player_update_game_state(PlayerPlayersByIndex[i]);
}
