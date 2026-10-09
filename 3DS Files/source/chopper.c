// chopper -- see chopper.h.

#include "chopper.h"

#include <math.h>
#include <stddef.h>

#include "acidsys.h"
#include "airoute.h"
#include "airouteplan.h"
#include "bchunk.h"
#include "bmem.h"
#include "bslotpool.h"
#include "car.h"
#include "coputil.h"
#include "eefpu.h"
#include "emath.h"
#include "helisheet.h"
#include "race.h"
#include "raceinit.h"
#include "vtable.h"
#include "world.h"

typedef void (*SoundDtorFn)(void *self, int32_t flags);
typedef void (*SoundActivateFn)(void *self, int32_t on);
typedef void (*SoundUpdateFn)(void *self, float a, uint16_t b, float c);
typedef void (*SoundMuteFn)(void *self, int32_t i);

Sound3d *(*gCreateChopperSoundFn)(struct Chopper *h);

const BombRunBehaviour BombRunBehaviours[CHOPATTACK_NUM] = {
    { CM_ROCKET,         2.0f,  20.0f, 0.0f, 1, 1,  0.0f, 0.0f },
    { CM_SMOKEBOMB,      2.0f, -10.0f, 0.0f, 1, 8, 30.0f, 0.5f },
    { CM_SMOKEBOMB,      1.5f, -10.0f, 0.0f, 2, 3,  5.0f, 0.5f },
    { CM_DROPPED_SPIKES, 2.0f, -10.0f, 0.0f, 1, 1,  0.0f, 0.0f },
    { CM_DROPPED_SPIKES, 1.0f, -10.0f, 0.0f, 1, 2,  4.0f, 1.0f },
};

// The run's least lead, 0x42c80000, and the slack under it, 0x41c00000.
#define BOMB_MIN_AHEAD     100.0f
#define BOMB_TARGET_SLACK  24.0f

// FindChopperRoutePoint's radius, 0x41c00000.
#define ROUTE_POINT_RADIUS 24.0f

// CalcMatrix's scale, gp-27984, and the height it adds, gp-27980.
#define CHOPPER_SCALE      1.1f
#define CHOPPER_RAISE      2.3f

// Car::GetRoute and GetRoutePoint's flag, and the routes' search flags.
#define FIND_ROUTE         1
#define ROUTE_FLAGS        6

// Degrees to BAM, as the image does it each time: the product truncated by
// `cvt.w.s`, then `div` by 360.
static uint16_t deg_to_bam(float deg)
{
    return (uint16_t)(ee_trunc_w(deg * 65536.0f) / 360);
}

// ------------------------------------------------------------ the sound

static const VtEntry *sound_slot(const struct Chopper *h, int slot)
{
    return vt_slot(h->pChopperSound->_vtable, slot);
}

static void sound_activate(struct Chopper *h, int32_t on)
{
    const VtEntry *e;

    if (h->pChopperSound == NULL)
        return;
    e = sound_slot(h, CHOPPERSOUND_VT_ACTIVATE);
    ((SoundActivateFn)e->fn)(vt_this(h->pChopperSound, e), on);
}

// --------------------------------------------------------------- the object

struct Chopper *chopper_construct(void *mem)
{
    struct Chopper *h = (struct Chopper *)mem;
    WorldObject *wo;

    topology_init(&h->TopologyCoord);
    h->DustEmitters.next = &h->DustEmitters;
    h->DustEmitters.prev = &h->DustEmitters;
    trackpath_coord_init(&h->TP);
    wo = (WorldObject *)bSlotOMalloc(WorldObjectSlotPool);
    h->WorldObj = worldobject_construct(wo, bchunk_hash("TRACK_HELICOPTER"),
                                        NULL, 1);
    h->pChopperSound = gCreateChopperSoundFn != NULL
        ? gCreateChopperSoundFn(h) : NULL;
    afx_get_emitters(&h->DustEmitters, bchunk_hash("XEM_HELI_DUST"));
    chopper_clear_variables(h);
    h->Plan = CHOPPLAN_EATING_DONUTS;
    if (TheRaceParameters.AIDemoMode == 0
        && TheRaceParameters.ReplayDemoMode == 0
        && gEggIsOnFn != NULL && gEggIsOnFn(EGG_HELICOPTER) != 0)
        h->New960 = 1;
    return h;
}

void chopper_destruct(struct Chopper *h, int32_t flags)
{
    afx_delete_emitters(&h->DustEmitters);
    if (h->pChopperSound != NULL) {
        const VtEntry *e = sound_slot(h, CHOPPERSOUND_VT_DTOR);

        ((SoundDtorFn)e->fn)(vt_this(h->pChopperSound, e), 3);
    }
    if (h->WorldObj != NULL)
        worldobject_destruct(h->WorldObj, 3);
    // The TP's and the TopologyCoordinate's destructors, and the list's,
    // which deletes what is left on it: afxDeleteEmitters left nothing.
    topology_destroy(&h->TopologyCoord);
    if (flags & 1)
        bFree(h);
}

void chopper_clear_variables(struct Chopper *h)
{
    h->TimeUntilThink = 0.0f;
    h->CurrentPos.x = 0.0f;
    h->CurrentCar = NULL;
    h->MoveMode = CHOPMOVE_PURSUIT;
    h->TargetRoute = NULL;
    h->TargetPoint = NULL;
    h->ChopperRoute = NULL;
    h->ChopperPoint = NULL;
    h->OldCarRoute = NULL;
    h->OldCarPoint = NULL;
    h->CurrentPos.y = 0.0f;
    h->CurrentPos.z = 0.0f;
    bIdentity(&h->Matrix);
    trackpath_coord_reset_position(&h->TP, (const bVector2 *)&h->CurrentPos);
    h->New960 = 0;
    h->Timeout = CHOPPER_TIMEOUT;
    h->Speed = 0.0f;
    h->Acceleration.x = 0.0f;
    h->Acceleration.y = 0.0f;
    h->Roll = 0.0f;
    h->DesiredRoll = 0.0f;
    h->Yaw = 0.0f;
    h->Pitch = 0.0f;
    h->DesiredPitch = 0.0f;
    h->RotRate = 0.0f;
    h->ZVelocity = 0.0f;
    h->GroundZ = 0.0f;
    h->EmitDust = 0;
    h->TargetDistance = 0.0f;
    h->BombRunType = CHOPATTACK_ROCKET;
    h->NumSalvosReleased = 0;
    h->NextLauncher = 0;
    h->TimeUntilNextSalvo = 0.0f;
    h->TotalSalvos = 0;
    h->StuckTime = 0.0f;
}

// ---------------------------------------------------- following a car

int32_t chopper_follow_this_car(struct Chopper *h, struct Car *car)
{
    // `xor` and `movz`: the player's car, whether or not it was this one.
    if (h->New960 != 0)
        car = pCurrentWorld->CarTable[0];
    if (TheHeliSheet == NULL || !signposts_present())
        return 0;
    if (car == NULL) {
        if (h->Plan == CHOPPLAN_START_CHASE
            || h->Plan == CHOPPLAN_EATING_DONUTS) {
            h->CurrentCar = NULL;
            h->Plan = CHOPPLAN_EATING_DONUTS;
        } else {
            h->Plan = CHOPPLAN_END_CHASE;
        }
    } else {
        if (h->Plan != CHOPPLAN_EATING_DONUTS
            && h->Plan != CHOPPLAN_START_CHASE)
            return 0;
        h->CurrentCar = car;
        h->Plan = CHOPPLAN_START_CHASE;
    }
    h->TimeUntilThink = 0.0f;
    return 1;
}

// ------------------------------------------------------- the bombing run

int32_t chopper_attack_car(struct Chopper *h, ChopperAttackType type)
{
    struct Car *car;
    float dx, dy;

    if (h->Plan != CHOPPLAN_PURSUIT) {
        if (h->CurrentCar != NULL)
            chopper_follow_this_car(h, h->CurrentCar);
        return 0;
    }
    h->TimeUntilNextSalvo = 0.0f;
    h->Timeout = CHOPPER_TIMEOUT;
    car = h->CurrentCar;
    dx = car->State.Position.x - h->CurrentPos.x;
    dy = car->State.Position.y - h->CurrentPos.y;
    h->Plan = CHOPPLAN_BOMBING_RUN;
    h->BombRunType = type;
    h->NumSalvosReleased = 0;
    h->TargetDistance = sqrtf(dx * dx + dy * dy);
    if (chopper_behind_car(h))
        h->TargetDistance = -h->TargetDistance;
    h->TargetRoute = h->ChopperRoute;
    h->TargetPoint = h->ChopperPoint;
    h->OldCarRoute = car_get_route(h->CurrentCar, FIND_ROUTE);
    h->OldCarPoint = car_get_route_point(h->CurrentCar, FIND_ROUTE);
    chopper_adjust_bomb_target(h);
    return 1;
}

void chopper_adjust_bomb_target(struct Chopper *h)
{
    const BombRunBehaviour *b = &BombRunBehaviours[h->BombRunType];
    float ahead = b->Ahead * h->CurrentCar->State.VelocityMagnitude;

    if (ahead < BOMB_MIN_AHEAD)
        ahead = BOMB_MIN_AHEAD;
    if (h->TargetDistance + BOMB_TARGET_SLACK < ahead) {
        chopper_shift_target(h, ahead);
        chopper_find_unobstructed_spot(h);
    }
}

void chopper_shift_target(struct Chopper *h, float dist)
{
    NearestRoutePointInfo out[5];
    TrackRoute *route = car_get_route(h->CurrentCar, FIND_ROUTE);
    TrackRoutePoint *point = car_get_route_point(h->CurrentCar, FIND_ROUTE);
    uint32_t n, i;

    n = (uint32_t)ai_guess_target_destinations(out, 5, route, point,
                                               dist + BOMB_TARGET_SLACK, 1);
    h->TargetDistance = dist;
    for (i = 0; i < n; i++) {
        if ((out[i].Point->Bits & TRP_NO_HELISHEET) == 0) {
            h->TargetPoint = out[i].Point;
            h->TargetRoute = out[i].Route;
            return;
        }
    }
}

void chopper_find_unobstructed_spot(struct Chopper *h)
{
    NearestRoutePointInfo info;
    // FindZValue leaves it alone on a miss. The image's first try then
    // reads whatever its stack held; the port's reads 0, which stops.
    uint32_t flags = 0;

    info.Route = h->TargetRoute;
    info.Point = h->TargetPoint;
    for (;;) {
        helisheet_find_z_value(TheHeliSheet,
                               (const bVector2 *)&info.Point->Position,
                               NULL, &flags);
        if ((flags & 1) == 0)
            break;
        h->TargetDistance = h->TargetDistance + info.Point->Length;
        ai_get_next_route_point(&info);
    }
    h->TargetRoute = info.Route;
    h->TargetPoint = info.Point;
}

void chopper_abort_bombing_run(struct Chopper *h)
{
    if (h->Plan == CHOPPLAN_BOMBING_RUN)
        h->Plan = CHOPPLAN_PURSUIT;
}

// -------------------------------------------------------- the world

int32_t chopper_find_ground_height(struct Chopper *h)
{
    bVector3 pt;
    int32_t terrain;

    pt.x = h->CurrentPos.x;
    pt.y = h->CurrentPos.y;
    pt.z = h->GroundZ;
    h->GroundZ = topology_get_elevation(&h->TopologyCoord, &pt, &terrain,
                                        NULL, NULL);
    return terrain;
}

void chopper_place_in_world(struct Chopper *h, const bVector2 *pos, float z)
{
    sound_activate(h, 1);
    h->CurrentPos.x = pos->x;
    h->CurrentPos.z = z;
    h->Pitch = 0.0f;
    h->DesiredPitch = 0.0f;
    h->Roll = 0.0f;
    h->DesiredRoll = 0.0f;
    h->Speed = 0.0f;
    h->CurrentPos.y = pos->y;
    // 0x3bb40000, 360 / 65536 rounded.
    h->Yaw = (float)h->CurrentCar->State.Angle * 0.0054931640625f;
    trackpath_coord_reset_position(&h->TP, (const bVector2 *)&h->CurrentPos);
    topology_set_interest_bbox(&h->TopologyCoord,
                               (const bVector2 *)&h->CurrentPos, 1.0f, NULL);
    h->GroundZ = h->CurrentCar->State.Position.z;
    chopper_find_ground_height(h);
    chopper_find_point_from_scratch(h);
    chopper_calc_matrix(h);
}

void chopper_remove_from_world(struct Chopper *h)
{
    h->WorldObj->Enabled = 0;
    sound_activate(h, 0);
    topology_clear_interest_bbox(&h->TopologyCoord);
}

int32_t chopper_behind_car(struct Chopper *h)
{
    return trackpath_compare_distances(
               &TheTrackPathManager, h->TP.DistanceAroundTrack,
               h->CurrentCar->TheTrackPathCoordinate.DistanceAroundTrack)
           <= 0.0f;
}

void chopper_rotate_to_chopper_coord(struct Chopper *h, bVector2 *out,
                                     const bVector2 *v)
{
    rotate_vector(out, v, 360.0f - h->Yaw);
}

float chopper_get_max_deceleration(const struct Chopper *h)
{
    // `addiu -1` and `sltiu 2`.
    if ((uint32_t)(h->Plan - 1) < 2u)
        return -120.0f;
    return -60.0f;
}

void chopper_mute(struct Chopper *h, int32_t i)
{
    const VtEntry *e;

    if (h->pChopperSound == NULL)
        return;
    e = sound_slot(h, CHOPPERSOUND_VT_MUTE);
    ((SoundMuteFn)e->fn)(vt_this(h->pChopperSound, e), i);
}

void chopper_update_sound(struct Chopper *h)
{
    const VtEntry *e;

    if (h->pChopperSound == NULL)
        return;
    e = sound_slot(h, CHOPPERSOUND_VT_UPDATE);
    ((SoundUpdateFn)e->fn)(vt_this(h->pChopperSound, e), 1.0f, 0, 1.0f);
}

// ------------------------------------------------------- the route points

void chopper_find_point_from_scratch(struct Chopper *h)
{
    NearestRoutePointInfo info;

    if (ai_get_nearest_route_point(&info, (const bVector2 *)&h->CurrentPos,
                                   ALL_RACING_ROUTES, ROUTE_FLAGS,
                                   0.0f)) {
        h->ChopperRoute = info.Route;
        h->ChopperPoint = info.Point;
    }
}

void chopper_find_route_point(struct Chopper *h)
{
    TrackRoute *route = h->ChopperRoute;
    TrackRoutePoint *p;

    p = troute_find_closest_point(route, (const bVector2 *)&h->CurrentPos,
                                  ROUTE_POINT_RADIUS, ROUTE_FLAGS, 0.0f);
    if (p == NULL && trpoint_has_signpost(h->ChopperPoint)) {
        route = signpost_get_new_route(trpoint_get_signpost(h->ChopperPoint));
        p = troute_find_closest_point(route,
                                      (const bVector2 *)&h->CurrentPos,
                                      ROUTE_POINT_RADIUS, ROUTE_FLAGS, 0.0f);
    }
    if (p == NULL) {
        chopper_find_point_from_scratch(h);
        return;
    }
    h->ChopperPoint = p;
    h->ChopperRoute = route;
}

// ------------------------------------------------------------ the matrix

void chopper_calc_matrix(struct Chopper *h)
{
    bMatrix4 m;
    float yaw;

    bIdentity(&m);
    yaw = 180.0f - h->Yaw;
    m.v0.x = CHOPPER_SCALE;
    m.v1.y = CHOPPER_SCALE;
    m.v2.z = CHOPPER_SCALE;
    if (yaw < 0.0f)
        yaw = yaw + 360.0f;
    eRotateX(&m, &m, deg_to_bam(h->Roll));
    eRotateY(&m, &m, deg_to_bam(360.0f - h->Pitch));
    eRotateZ(&m, &m, deg_to_bam(yaw));
    m.v3.x = h->CurrentPos.x;
    m.v3.y = h->CurrentPos.y;
    m.v3.z = h->CurrentPos.z + CHOPPER_RAISE;
    h->Matrix = m;
}

void chopper_update_world_object(struct Chopper *h)
{
    // The image tests &Matrix for NULL, which it never is.
    h->WorldObj->Matrix = h->Matrix;
    h->WorldObj->Enabled = 1;
}
