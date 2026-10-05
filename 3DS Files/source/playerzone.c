// playerzone -- see playerzone.h.

#include "playerzone.h"

#include <stddef.h>
#include <string.h>

#include "bmem.h"
#include "cammover.h"
#include "car.h"
#include "carinit.h"
#include "hudanim.h"
#include "player.h"
#include "playercam.h"
#include "playerhud.h"
#include "playerinit.h"
#include "playerinput.h"
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

// The allocation's file name, as retail's bMalloc gives it.
#define PLAYER_CPP "..\\indep\\src\\player.cpp"

// gp-30472 and the lui 0xc45d beside it.
const bVector2 PlayerNoJumpCamPlace = { 1646.0f, -884.0f };

const int8_t PlayerZoneClearedByRequest[PLAYER_ZONE_COUNT] = {
    0, 1, 1, 0, 0, 0, 0, 0,
};
const int8_t PlayerZoneBlocksRequest[PLAYER_ZONE_COUNT] = {
    0, 0, 0, 1, 1, 1, 1, 1,
};

float (*gZoneFreezeDurationFn)(void);
struct PreviewRoute *(*gZonePreviewFindRouteFn)(struct Car *car);
int32_t (*gZonePreviewViolatesTopologyFn)(struct CameraMover *m);
float (*gZonePreviewDurationFn)(struct CameraMover *m);
float (*gSoundGetCategoryVolumeFn)(uint32_t category);
struct bSample *(*gNewSampleFn)(void);
void (*gSampleInitializeFn)(struct bSample *s, struct bSample *from);
void (*gSampleSetCategoryFn)(struct bSample *s, uint32_t category);
struct bSample *(*gCommonRegionSampleFn)(const char *name);

// A zone's time limits: how soon one may start again without force, and
// with it, after the last freeze or preview. Timer ticks are 0.00025 s.
#define ZONE_TICK        0.00025f
#define ZONE_REPEAT      5.0f
#define ZONE_FORCE_GAP   0.1f

// The zones' world speeds and how long they last, the jump cam's pitch.
#define ZONE_SLOMO_SCALE 0.333f
#define ZONE_JUMP_SCALE  0.4f
#define ZONE_JUMP_PITCH  0.9f

// --------------------------------------------------------------- the jump cam

int32_t player_is_jump_cam_available(struct Player *p)
{
    struct Car *car;
    void *mem;

    player_clean_up_jump_cam(p);
    car = p->MyCar;
    if (CurrentTrackInfo->SameAsTrackNumber == PLAYER_NO_JUMP_CAM_TRACK
        && bEqual2((const bVector2 *)&car->State.Position,
                   &PlayerNoJumpCamPlace, PLAYER_NO_JUMP_CAM_RADIUS))
        return 0;
    mem = bMalloc((int)sizeof(PreviewRoute), PLAYER_CPP, 1245, 16);
    p->pJumpCamRoute = preview_route_init((PreviewRoute *)mem, car, 50.0f,
                                          75.0f);
    if (p->pJumpCamRoute->nPoints < 5) {
        player_clean_up_jump_cam(p);
        return 0;
    }
    return 1;
}

// The car's progress round the track, 0 to 1 the race's way.
static float progress(const struct Player *p)
{
    float ratio = p->MyCar->TheTrackPathCoordinate.RatioAroundTrack;

    if (RaceParametersTrackDirection == 0)
        return ratio * 100.0f * 0.01f;
    return (100.0f - ratio * 100.0f) * 0.01f;
}

// Both movers' last step: a shake of nothing with two points, and the
// mover on myCD.
static struct CameraMover *jump_cam_mover(struct Player *p, struct Car *car,
                                          int focusEffects)
{
    CameraShake shake;
    void *mem;

    memset(&shake, 0, sizeof shake);
    shake.NumCVs = 2;
    mem = bMalloc((int)sizeof(TrackCarCameraMover), "TrackCarCameraMover",
                  0, 16);
    return &track_car_camera_mover_init((TrackCarCameraMover *)mem,
                                        p->ViewID, car, p->myCD, &shake,
                                        focusEffects)->base;
}

static float dot_velocity(const bVector3 *a, const bVector3 *b,
                          const bVector3 *v)
{
    float x = a->x - b->x, y = a->y - b->y, z = a->z - b->z;

    return (x * v->x + y * v->y) + z * v->z;
}

// Type 15. The pad lanes of the eye points and the tables are the stack's
// in retail; here they are 0.
static struct CameraMover *jump_cam_first(struct Player *p, struct Car *car)
{
    PreviewRoute *r = p->pJumpCamRoute;
    CameraDataItems *cd = p->myCD;
    const PreviewRoutePoint *pt;
    TrackPathCoordinate tpc;
    TopologyCoordinate tc;
    bVector3 target = {0.0f, 0.0f, 0.0f, 0.0f};
    bVector3 left = {0.0f, 0.0f, 0.0f, 0.0f};
    bVector3 right = {0.0f, 0.0f, 0.0f, 0.0f};
    bVector3 other = {0.0f, 0.0f, 0.0f, 0.0f};
    bVector3 eye;
    struct CameraMover *m;
    int32_t n, i;
    float pct, elev;

    n = r->nPoints - 1;
    if (5 <= n)
        n = r->nPoints - 3;
    cd->IsFOVIso = 0;
    cd->Type = 0;
    cd->Name = NULL;
    preview_route_point_get_position_at(&r->pPoints[n], &target, 0.0f,
                                        0.0f);
    trackpath_coord_init_at(&tpc, (const bVector2 *)&target);
    pct = progress(p);
    cd->MinAreaPercent = pct;
    cd->MinPercent = pct;
    if (RaceParametersTrackDirection == 0)
        pct = tpc.RatioAroundTrack;
    else
        pct = 1.0f - tpc.RatioAroundTrack;
    cd->MaxAreaPercent = pct;
    cd->MaxPercent = pct;

    cd->LockEyeSpeedToCar = 1;
    cd->FOVTable = p->FOVtable;
    cd->NearClip = 0.5f;
    cd->FarClip = 10000.0f;
    cd->EyeSplineSpeed = 0.0f;
    cd->LookSplineSpeed = 0.0f;
    cd->FOVSplineSpeed = 0.0f;
    cd->LockLookSpeedToCar = 0;
    cd->Backwards = 0;
    for (i = 0; i < 32; i++) {
        p->FOVtable[i].x = 20.0f;
        p->FOVtable[i].y = 0.0f;
        p->FOVtable[i].z = 0.0f;
        p->FOVtable[i].pad = 0.0f;
    }
    cd->BankVerts = p->BankVerts;
    cd->NumEyeVerts = 2;
    cd->EyeVerts = p->EyeVerts;
    for (i = 0; i < 3; i++) {
        p->BankVerts[i].x = 0.0f;
        p->BankVerts[i].y = 0.0f;
        p->BankVerts[i].z = 0.0f;
        p->BankVerts[i].pad = 0.0f;
    }
    cd->SpringXVel = 0.0f;
    cd->EnterVertComp = 0.2f;
    cd->SpringYVel = 0.0f;
    cd->SpringZVel = 0.0f;
    cd->SpringDamp = 0.0f;
    cd->SpringConst = 0.0f;
    cd->LookOffsetX = 0.0f;
    cd->LookOffsetY = 0.0f;
    cd->LookOffsetZ = 0.0f;
    cd->LeaveVertComp = 0.0f;
    cd->LeaveHorizComp = 0.0f;
    cd->WipeDistance = 0.0f;
    cd->WipeAutoDisable = 0;
    cd->NumLookVerts = 0;
    cd->LookVerts = NULL;
    cd->IsLeaveSet = 0;

    // The edges of the road at that point, and the one whose way from the
    // car runs least with it.
    pt = &r->pPoints[n];
    eye = car->State.Position;
    preview_route_point_get_position_at(pt, &right, 0.0f,
                                        pt->pPoint->RightWidth);
    preview_route_point_get_position_at(pt, &left, 0.0f,
                                        -pt->pPoint->LeftWidth);
    pt = &r->pPoints[2];
    if (dot_velocity(&left, &eye, &car->State.Velocity)
        < dot_velocity(&right, &eye, &car->State.Velocity)) {
        eye = left;
        preview_route_point_get_position_at(pt, &other, 0.0f,
                                            pt->pPoint->RightWidth);
        cd->EnterHorizComp = 0.4f;
    } else {
        eye = right;
        preview_route_point_get_position_at(pt, &other, 0.0f,
                                            -pt->pPoint->LeftWidth);
        cd->EnterHorizComp = -0.4f;
    }
    eye.z = eye.z + 1.0f;
    other.z = other.z + 1.0f;
    topology_init(&tc);
    elev = topology_get_elevation(&tc, &eye, NULL, NULL, NULL);
    if (eye.z < elev)
        eye.z = elev + 1.0f;
    p->EyeVerts[0] = eye;
    p->EyeVerts[1] = eye;
    p->EyeVerts[2] = other;

    m = jump_cam_mover(p, car, 0);
    topology_destroy(&tc);
    return m;
}

// Type 16, on what 15 left.
static struct CameraMover *jump_cam_second(struct Player *p,
                                           struct Car *car)
{
    CameraDataItems *cd = p->myCD;
    TopologyCoordinate tc;
    struct CameraMover *m;
    bVector3 *top = &p->EyeVerts[2];
    float pct, elev, z;
    int32_t i;

    pct = progress(p);
    cd->MinAreaPercent = pct;
    cd->MinPercent = pct;
    z = p->MyCar->State.Position.z;
    if (top->z < z)
        top->z = z;
    topology_init(&tc);
    elev = topology_get_elevation(&tc, top, NULL, NULL, NULL);
    if (top->z < elev)
        top->z = elev + 1.0f;
    p->EyeVerts[0] = *top;
    p->EyeVerts[1] = *top;
    cd->EnterHorizComp = -cd->EnterHorizComp;
    for (i = 0; i < 32; i++) {
        p->FOVtable[i].x = 20.0f - (float)i * 0.25f;
        p->FOVtable[i].y = 0.0f;
        p->FOVtable[i].z = 0.0f;
        p->FOVtable[i].pad = 0.0f;
    }

    m = jump_cam_mover(p, car, 1);
    topology_destroy(&tc);
    return m;
}

struct CameraMover *player_jump_cam_mover(struct Player *p, struct Car *car,
                                          int second)
{
    if (second)
        return jump_cam_second(p, car);
    return jump_cam_first(p, car);
}

// ------------------------------------------------------------------ the zones

// RaceCoordinator's replay states, as retail tests them inline.
static int in_replay(void)
{
    RCState s = racecoordinator_get_current_state(pRaceCoordinator);

    return s == RCSTATE_INSTANT_REPLAY || s == RCSTATE_POSTRACE
           || s == RCSTATE_AUTO_REPLAY
           || racecoordinator_is_replay_demo_mode(pRaceCoordinator);
}

// "How long since", in seconds, for a stamp that is set.
static float since(const Timer *t)
{
    return (float)(int32_t)((uint32_t)WorldTimer - t->PackedTime)
           * ZONE_TICK;
}

static void play_menu_wrong(void)
{
    struct bSample *s;

    if (!SoundEnabled || gCommonRegionSampleFn == NULL)
        return;
    s = gCommonRegionSampleFn("MenuWrong");
    if (gSamplePlayFn != NULL)
        gSamplePlayFn(s, 1.0f, 0.0f, 0.0f);
}

static void delete_zone_sample(struct Player *p)
{
    if (gSampleDeleteFn != NULL)
        gSampleDeleteFn(p->pZoneSample);
}

// The port's dead button: see player_request_zone.
static int zone_ported(int32_t zone)
{
    if (zone == PLAYER_ZONE_FREEZE)
        return gZoneFreezeCameraMoverFn != NULL
               && gZoneFreezeDurationFn != NULL;
    if (zone == PLAYER_ZONE_PREVIEW)
        return gZonePreviewCameraMoverFn != NULL
               && gZonePreviewFindRouteFn != NULL
               && gZonePreviewViolatesTopologyFn != NULL
               && gZonePreviewDurationFn != NULL;
    return 1;
}

int32_t player_request_zone(struct Player *p, int32_t zone, int32_t force,
                            int32_t sound, int32_t muffle)
{
    const char *name = "Wind";
    float volume = 1.0f, pitch = 1.0f;
    int32_t param = (int32_t)(intptr_t)p;
    const Timer *t;
    int32_t i;

    if (!zone_ported(zone))
        return 0;
    if (player_is_nis_playing(p))
        return 0;
    if (racecoordinator_get_current_state(pRaceCoordinator)
        == RCSTATE_AI_DEMO_MODE)
        return 0;
    t = &p->tAutoZoneTimers[force ? 0 : zone];
    if (timer_is_valid(t)) {
        if (!force && since(t) < ZONE_REPEAT)
            return 0;
        if (force && since(t) < ZONE_FORCE_GAP)
            return 0;
    }
    if (race_get_race_stage(pCurrentRace) != RACE_STAGE_RACING)
        return 0;
    if ((uint32_t)zone >= PLAYER_ZONE_COUNT || PlayerNumPlayers == 2)
        return 0;
    if ((uint32_t)(zone - PLAYER_ZONE_JUMP_CAM) < 2
        && !TheRaceParameters.GlobalDisplaySettings.JumpCams)
        return 0;
    if ((uint32_t)(zone - PLAYER_ZONE_FREEZE) < 5
        && !TheRaceParameters.GlobalDisplaySettings.ZoneCams)
        return 0;
    if (PlayerZoneClearedByRequest[p->nZoneCurrent])
        player_clear_zone(p, 0);
    for (i = 0; i < PlayerNumPlayers; i++)
        if (PlayerZoneBlocksRequest[PlayerPlayersByIndex[i]->nZoneCurrent])
            return 0;
    p->tIgnoreNextPovChange.PackedTime = (uint32_t)RealTimer;
    if (!force)
        p->tAutoZoneTimers[zone].PackedTime = (uint32_t)WorldTimer;
    player_clear_hud_animations(p);

    switch (zone) {
    case PLAYER_ZONE_FREEZE:
        if (in_replay())
            return 0;
        player_change_camera_mover(p, CM_ZONE_FREEZE, 1);
        world_set_world_paused(pCurrentWorld,
                               gZoneFreezeDurationFn() - WorldTimeElapsed,
                               player_clear_zone_callback, param);
        break;

    case PLAYER_ZONE_PREVIEW: {
        struct CameraMover *m;

        if (in_replay())
            return 0;
        if (p->bWrongWay) {
            play_menu_wrong();
            return 0;
        }
        p->pRoute = gZonePreviewFindRouteFn(p->MyCar);
        if (p->pRoute == NULL) {
            play_menu_wrong();
            return 0;
        }
        player_change_camera_mover(p, CM_ZONE_PREVIEW, 1);
        m = p->pCameraMover;
        if (gZonePreviewViolatesTopologyFn(m)) {
            play_menu_wrong();
            player_restore_camera_mover(p);
            return 0;
        }
        volume = 0.0f;
        world_set_world_paused(pCurrentWorld,
                               gZonePreviewDurationFn(m) - WorldTimeElapsed,
                               player_clear_zone_callback, param);
        name = "PreviewZone";
        break;
    }

    case PLAYER_ZONE_SLOMO:
        world_set_time_scale(pCurrentWorld, ZONE_SLOMO_SCALE, 8.0f,
                             player_clear_zone_callback, param);
        name = "SlomoZone";
        break;

    case PLAYER_ZONE_SLOMO_SHORT:
        world_set_time_scale(pCurrentWorld, ZONE_SLOMO_SCALE, 2.0f,
                             player_clear_zone_callback, param);
        name = "SlomoZone";
        break;

    case PLAYER_ZONE_FAST:
        world_set_time_scale(pCurrentWorld, 2.0f, 4.0f,
                             player_clear_zone_callback, param);
        break;

    case PLAYER_ZONE_JUMP_CAM:
        world_set_time_scale(pCurrentWorld, ZONE_JUMP_SCALE, 8.0f,
                             player_clear_zone_callback, param);
        pitch = ZONE_JUMP_PITCH;
        name = "SlomoZone";
        if (!in_replay())
            player_change_camera_mover(p, CM_ZONE_JUMPER, 1);
        player_clean_up_jump_cam(p);
        break;

    case PLAYER_ZONE_AFTER_JUMP:
        world_set_time_scale(pCurrentWorld, ZONE_JUMP_SCALE, 8.0f,
                             player_clear_zone_callback, param);
        pitch = ZONE_JUMP_PITCH;
        name = "SlomoZone";
        if (!in_replay())
            player_change_camera_mover(p, CM_ZONE_JUMPER2, 1);
        break;

    default:
        break;
    }

    if (gRadialBlurOnFn != NULL)
        gRadialBlurOnFn(p->PlayerNumber);
    p->nZoneCurrent = zone;
    p->bZoneMuffleSound = muffle;
    p->fZoneMuffleVolume = muffle ? 0.0f : 1.0f;
    if (SoundEnabled && sound && gSoundGetCategoryVolumeFn != NULL
        && 0.0f < gSoundGetCategoryVolumeFn(0)) {
        struct bSample *from;

        if (p->pZoneSample != NULL)
            delete_zone_sample(p);
        p->pZoneSample = gNewSampleFn != NULL ? gNewSampleFn() : NULL;
        from = gGetInGameSampleFn != NULL ? gGetInGameSampleFn(name) : NULL;
        if (gSampleInitializeFn != NULL)
            gSampleInitializeFn(p->pZoneSample, from);
        if (gSampleSetCategoryFn != NULL)
            gSampleSetCategoryFn(p->pZoneSample, 0xffffffffu);
        if (gSamplePlayFn != NULL)
            gSamplePlayFn(p->pZoneSample, volume, 0.0f, pitch - 1.0f);
    }
    return 1;
}

void player_clear_zone(struct Player *p, int32_t sound)
{
    int32_t zone;

    if (p->nZoneCurrent == 0)
        return;
    if (gRadialBlurOffFn != NULL)
        gRadialBlurOffFn(p->PlayerNumber);
    zone = p->nZoneCurrent;
    if (0 < zone && zone < 3) {
        if (TweakerPauseWorld == 0)
            p->tAutoZoneTimers[0].PackedTime = (uint32_t)WorldTimer;
        if (!in_replay())
            player_restore_camera_mover(p);
    } else if (PLAYER_ZONE_JUMP_CAM <= zone && zone < PLAYER_ZONE_COUNT) {
        if (!in_replay())
            player_restore_camera_mover(p);
    }
    world_reset_time_scale(pCurrentWorld);
    p->nZonePrevious = p->nZoneCurrent;
    p->nZoneCurrent = 0;
    p->bZoneMuffleSound = 0;
    p->fZoneMuffleVolume = 0.0f;
    if (sound)
        player_clear_zone_sound(p);
    player_determine_input_mode(p);
}

void player_clear_zone_sound(struct Player *p)
{
    if (SoundEnabled && p->pZoneSample != NULL) {
        delete_zone_sample(p);
        p->pZoneSample = NULL;
    }
}

void player_clear_zone_callback(int32_t param)
{
    player_clear_zone((struct Player *)(intptr_t)param, 1);
}
