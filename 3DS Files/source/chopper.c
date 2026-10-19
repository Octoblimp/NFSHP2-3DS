// chopper -- see chopper.h.

#include "chopper.h"

#include <float.h>
#include <math.h>
#include <stddef.h>

#include "acidsys.h"
#include "airoute.h"
#include "airouteplan.h"
#include "bchunk.h"
#include "bmath.h"
#include "bmem.h"
#include "bslotpool.h"
#include "bvector.h"
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

void chopper_honk_attack(void)
{
    struct Chopper *h;

    if (pCurrentWorld == NULL)
        return;
    h = pCurrentWorld->Helicopter;
    if (h == NULL || h->New960 == 0)
        return;
    chopper_attack_car(h, CHOPATTACK_SMOKE_BOMB_1);
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

// -------------------------------------------------------- the chase logic

// The height over the sheet the chase starts and ends at, 0x43160000; the
// drop and the climb, 0xc1c80000 and 0x41c80000.
#define CHASE_HEIGHT       150.0f
#define CHASE_DROP         -25.0f
#define CHASE_CLIMB        25.0f

// EndChaseLogic's walk: its reach, 0x41f00000, and speed, 0x42480000.
#define END_CHASE_REACH    30.0f
#define END_CHASE_SPEED    50.0f

// SetFollowSpeed's lead on the car, 0x41f00000.
#define FOLLOW_LEAD        30.0f

// CalcMinRouteFollowDistance: Speed times gp-28044, at least 0x41f00000.
#define FOLLOW_SCALE       0.1f
#define FOLLOW_MIN         30.0f

// FollowRoute's points.
#define FOLLOW_POINTS      5

// BeginStakeout's search radius, 0x43c80000, and timeout, 0x42700000.
#define STAKEOUT_RADIUS    400.0f
#define STAKEOUT_TIMEOUT   60.0f

// HangoutNearHere's shrink, gp-28048.
#define HANGOUT_SHRINK     0.7f

// AdjustTargetInBounds: the probes' reach, 0x40900000, the step,
// 0x3fc00000, and the tries.
#define BOUNDS_PROBE       4.5f
#define BOUNDS_STEP        1.5f
#define BOUNDS_TRIES       3u

// AdjustByThinkTime's scale, 0x42c80000.
#define THINK_SCALE        100.0f

// A point's index in `r`'s table, the image's way (airoute.c's
// point_index).
static int32_t point_index(const TrackRoute *r, const TrackRoutePoint *p)
{
    uint32_t d = (uint32_t)((uintptr_t)p
                            - (uintptr_t)r->TrackRoutePointTable);

    return (int32_t)(d * 0xb6db6db7u) >> 4;
}

// How far `p` is from the helicopter on the ground, as every caller works
// it out: x's square plus y's, then the root.
static float distance_to(const struct Chopper *h, const bVector2 *p)
{
    float dx = p->x - h->CurrentPos.x;
    float dy = p->y - h->CurrentPos.y;

    return sqrtf(dx * dx + dy * dy);
}

int32_t chopper_start_chase_logic(struct Chopper *h, ChopperTarget *t,
                                  int32_t on_sheet, uint32_t flags, float z)
{
    if (!on_sheet || (flags & 2))
        return 1;
    chopper_place_in_world(h, &t->Location, z + CHASE_HEIGHT);
    h->Plan = CHOPPLAN_PURSUIT;
    h->EmitDust = (int32_t)((flags ^ 1) & 1);
    h->ZVelocity = CHASE_DROP;
    return 0;
}

int32_t chopper_end_chase_logic(struct Chopper *h, ChopperTarget *t)
{
    NearestRoutePointInfo last, next;
    float z;
    uint32_t flags;

    if (helisheet_find_z_value(TheHeliSheet, (const bVector2 *)&h->CurrentPos,
                               &z, &flags)) {
        if (z + CHASE_HEIGHT <= h->CurrentPos.z) {
            chopper_remove_from_world(h);
            h->Plan = CHOPPLAN_EATING_DONUTS;
            return 1;
        }
        if (!((flags & 2) && h->ZVelocity == 0.0f)) {
            h->ZVelocity = CHASE_CLIMB;
            t->Location.x = h->CurrentPos.x;
            t->Location.y = h->CurrentPos.y;
            return 0;
        }
    }
    last.Route = h->ChopperRoute;
    last.Point = h->ChopperPoint;
    next = last;
    for (;;) {
        ai_get_next_route_point(&next);
        if (next.Point == NULL)
            break;
        last = next;
        if (END_CHASE_REACH < distance_to(h, &last.Point->Position))
            break;
    }
    t->DesiredSpeed = END_CHASE_SPEED;
    t->Location.x = last.Point->Position.x;
    t->Location.y = last.Point->Position.y;
    return 0;
}

void chopper_set_follow_speed(struct Chopper *h, ChopperTarget *t)
{
    t->DesiredSpeed = h->CurrentCar->State.VelocityMagnitude + FOLLOW_LEAD;
}

int32_t chopper_find_previous_fork(struct Chopper *h,
                                   NearestRoutePointInfo *info, int b)
{
    int back = b ^ 1;
    uint32_t count = 0;
    int32_t n;
    Signpost *s;

    (void)h;
    for (;;) {
        n = ai_find_nearby_signpost(info, back);
        if (n == 0)
            return 0;
        count += (uint32_t)n;
        s = trpoint_get_signpost(info->Point);
        info->Route = signpost_get_new_route(s);
        info->Point = signpost_get_new_route_point(s);
        if ((s->Flags & SIGNPOST_SIGN_MASK) != SIGN_ALWAYS_TAKE)
            return (int32_t)count;
        info->Point = troute_get_relative_point(info->Route, info->Point,
                                                back);
        count++;
    }
}

int32_t chopper_switch_to_nearby_fork(struct Chopper *h,
                                      NearestRoutePointInfo *out,
                                      const NearestRoutePointInfo *in, int b,
                                      float maxd)
{
    uint32_t k;

    *out = *in;
    k = (uint32_t)chopper_find_previous_fork(h, out, b);
    if (k == 0)
        return 0;
    // `sll` by one, tested again: zero only for a count of 2^31.
    for (k <<= 1; k != 0; k--) {
        if (distance_to(h, &out->Point->Position) < maxd)
            return 1;
        out->Point = troute_get_relative_point(out->Route, out->Point, b);
        if (out->Point == NULL)
            return 0;
    }
    return 0;
}

void chopper_target_chopper_point(struct Chopper *h, ChopperTarget *t)
{
    t->Location.x = h->ChopperPoint->Position.x;
    t->Location.y = h->ChopperPoint->Position.y;
}

void chopper_follow_route(struct Chopper *h, ChopperTarget *t,
                          TrackRoute *route, TrackRoutePoint *point, int fwd)
{
    NearestRoutePointInfo out[FOLLOW_POINTS], start, target, fork;
    float mind = chopper_calc_min_route_follow_distance(h, t);
    int far = mind < distance_to(h, &h->ChopperPoint->Position);
    uint32_t n, i;

    if (h->ChopperPoint == point || far) {
        if (far)
            chopper_set_follow_speed(h, t);
        chopper_target_chopper_point(h, t);
        return;
    }
    start.Route = h->ChopperRoute;
    start.Point = h->ChopperPoint;
    target.Route = route;
    target.Point = point;
    n = ai_find_points_to_target(&start, &target, out, FOLLOW_POINTS, fwd, 1);
    if (n == 0 && chopper_switch_to_nearby_fork(h, &fork, &start, fwd, mind))
        n = ai_find_points_to_target(&fork, &target, out, FOLLOW_POINTS, fwd,
                                     1);
    if (n == 0)
        return;
    for (i = 0; i < n; i++)
        if (out[i].Point == point
            || mind < distance_to(h, &out[i].Point->Position))
            break;
    if (i == n)
        i = n - 1;
    if (out[i].Point != point)
        chopper_set_follow_speed(h, t);
    t->Location.x = out[i].Point->Position.x;
    t->Location.y = out[i].Point->Position.y;
}

void chopper_begin_stakeout(struct Chopper *h, ChopperTarget *t,
                            TrackRoute *route, TrackRoutePoint *point)
{
    NearestRoutePointInfo info;
    TrackRoutePoint *c;
    Signpost *s;

    info.Route = route;
    info.Point = point;
    for (;; ai_get_next_route_point(&info)) {
        if (info.Point == NULL) {
            chopper_bail_to_point_near_chopper(h, t);
            return;
        }
        if ((info.Point->Bits & TRP_NO_HELISHEET)
            || !trpoint_has_signpost(info.Point))
            continue;
        s = trpoint_get_signpost(info.Point);
        if (s->Flags & SIGNPOST_NO_STAKEOUT)
            continue;
        break;
    }
    if (s->Flags & SIGNPOST_BACKWARDS) {
        h->TargetRoute = info.Route;
        h->TargetPoint = info.Point;
    } else {
        h->TargetRoute = signpost_get_new_route(s);
        h->TargetPoint = signpost_get_new_route_point(s);
    }
    c = troute_find_closest_point(h->TargetRoute,
                                  (const bVector2 *)&h->CurrentPos,
                                  STAKEOUT_RADIUS, 0, 0.0f);
    if (c != NULL && point_index(h->TargetRoute, h->TargetPoint)
                         < point_index(h->TargetRoute, c)) {
        h->TargetRoute = h->ChopperRoute;
        h->TargetPoint = h->ChopperPoint;
        chopper_target_chopper_point(h, t);
        return;
    }
    h->Plan = CHOPPLAN_HEAD_TO_STAKEOUT;
    h->Timeout = STAKEOUT_TIMEOUT;
    chopper_follow_route(h, t, h->TargetRoute, h->TargetPoint, 1);
}

void chopper_hangout_near_here(struct Chopper *h, ChopperTarget *t,
                               TrackRoute *route, TrackRoutePoint *point)
{
    float dx = t->Location.x - point->Position.x;
    float dy = t->Location.y - point->Position.y;
    float along = dx * point->Direction.x + dy * point->Direction.y;
    float across = (dx * point->Direction.y - dy * point->Direction.x)
                   * HANGOUT_SHRINK;

    (void)h, (void)route;
    for (;;) {
        along = along * HANGOUT_SHRINK;
        trpoint_get_position2(point, &t->Location, along, across);
        if (helisheet_find_z_value(TheHeliSheet, &t->Location, NULL, NULL))
            return;
        // The port's: both below the least normal float, where the EE has
        // flushed them to zero and every try from here on is at the point
        // itself. (An IEEE float shrinks to the least denormal and stays.)
        if (!(fabsf(along) >= FLT_MIN) && !(fabsf(across) >= FLT_MIN))
            return;
        across = across * HANGOUT_SHRINK;
    }
}

void chopper_bail_to_point_near_chopper(struct Chopper *h, ChopperTarget *t)
{
    chopper_hangout_near_here(h, t, h->ChopperRoute, h->ChopperPoint);
}

float chopper_calc_min_route_follow_distance(struct Chopper *h,
                                             ChopperTarget *t)
{
    float d = h->Speed * FOLLOW_SCALE;

    (void)t;
    if (d < FOLLOW_MIN)
        d = FOLLOW_MIN;
    return d;
}

int32_t chopper_adjust_target_in_bounds(struct Chopper *h, ChopperTarget *t)
{
    uint32_t tries;
    int32_t xm, xp, yp, ym;
    int moved;

    for (tries = 0; tries < BOUNDS_TRIES; tries++) {
        xm = chopper_test_location(h, t->Location.x - BOUNDS_PROBE,
                                   t->Location.y);
        xp = chopper_test_location(h, t->Location.x + BOUNDS_PROBE,
                                   t->Location.y);
        yp = chopper_test_location(h, t->Location.x,
                                   t->Location.y + BOUNDS_PROBE);
        ym = chopper_test_location(h, t->Location.x,
                                   t->Location.y - BOUNDS_PROBE);
        moved = 0;
        if (xm && !xp) {
            t->Location.x = t->Location.x - BOUNDS_STEP;
            moved = 1;
        } else if (!xm && xp) {
            t->Location.x = t->Location.x + BOUNDS_STEP;
            moved = 1;
        }
        if (yp && !ym) {
            t->Location.y = t->Location.y + BOUNDS_STEP;
            moved = 1;
        } else if (!yp && ym) {
            t->Location.y = t->Location.y - BOUNDS_STEP;
            moved = 1;
        }
        if (!moved)
            return 1;
    }
    return 0;
}

int32_t chopper_on_different_fork(struct Chopper *h, TrackRoute *route,
                                  TrackRoutePoint *point)
{
    NearestRoutePointInfo info;

    (void)point;
    if (route == h->ChopperRoute)
        return 0;
    info.Route = h->ChopperRoute;
    info.Point = h->ChopperPoint;
    if (chopper_find_previous_fork(h, &info, 1) == 0)
        return 0;
    return info.Route == route;
}

void chopper_adjust_target_local(struct Chopper *h, ChopperTarget *t)
{
    t->Location.x = t->Location.x - h->CurrentPos.x;
    t->Location.y = t->Location.y - h->CurrentPos.y;
    chopper_rotate_to_chopper_coord(h, &t->Location, &t->Location);
}

int32_t chopper_test_location(struct Chopper *h, float x, float y)
{
    bVector2 v;

    v.x = x;
    v.y = y;
    rotate_vector(&v, &v, h->Yaw);
    v.x = v.x + h->CurrentPos.x;
    v.y = v.y + h->CurrentPos.y;
    return helisheet_find_z_value(TheHeliSheet, &v, NULL, NULL);
}

float chopper_adjust_by_think_time(struct Chopper *h, float f)
{
    (void)h;
    return f * THINK_SCALE;
}

// -------------------------------------------------------------- the plans

// HighLevelPlanning: what it takes off Timeout each time, gp-28036, and how
// far ahead of the car it looks, in seconds of its velocity, gp-28032.
#define PLAN_TICK          0.1f
#define PLAN_LEAD          0.3f

// The stakeout: given up within 0x42700000 of the car's spot, reached
// within 0x41f00000 of its point, and waited at for 0x42340000.
#define STAKEOUT_GIVE_UP   60.0f
#define STAKEOUT_REACH     30.0f
#define STAKEOUT_WAIT      45.0f

// CleverPursuitPlan's speed above which it leads the car, 0x41a00000.
#define PURSUIT_LEAD_SPEED 20.0f

// BombRunLogic: the salvos' clock, gp-28040; the reach to the target,
// 0x41f00000; and the most the helicopter may be over the ground to fire,
// 0x41200000.
#define SALVO_TICK         0.1f
#define BOMB_REACH         30.0f
#define BOMB_HEIGHT        10.0f

void chopper_clever_pursuit_plan(struct Chopper *h, ChopperTarget *t,
                                 int32_t on_sheet, uint32_t flags)
{
    TrackRoute *route;
    TrackRoutePoint *point, *ahead;
    float along;
    int near;

    if (!(h->ZVelocity == 0.0f) && ((flags & 2) || !on_sheet)) {
        t->Location.y = h->CurrentPos.y;
        t->Location.x = h->CurrentPos.x;
        return;
    }
    near = distance_to(h, &t->Location)
           < chopper_calc_min_route_follow_distance(h, t);
    route = car_get_route(h->CurrentCar, FIND_ROUTE);
    point = car_get_route_point(h->CurrentCar, FIND_ROUTE);
    if (route == NULL || point == NULL) {
        chopper_bail_to_point_near_chopper(h, t);
        return;
    }
    ahead = troute_find_closest_point_ahead(route, &t->Location, point);
    if (ahead != NULL)
        point = ahead;
    if (on_sheet) {
        if (near) {
            if (PURSUIT_LEAD_SPEED < h->Speed) {
                along = (t->Location.x - point->Position.x)
                            * point->Direction.x
                        + (t->Location.y - point->Position.y)
                              * point->Direction.y;
                trpoint_get_position2(point, &t->Location, along, 0.0f);
            }
            return;
        }
    } else if (point->Bits & TRP_NO_HELISHEET) {
        chopper_begin_stakeout(h, t, route, point);
        return;
    }
    if (chopper_on_different_fork(h, route, point)) {
        chopper_begin_stakeout(h, t, route, point);
        return;
    }
    if (near)
        chopper_hangout_near_here(h, t, route, point);
    else
        chopper_follow_route(h, t, route, point, chopper_behind_car(h));
}

void chopper_bomb_run_logic(struct Chopper *h, ChopperTarget *t)
{
    const BombRunBehaviour *b;
    TrackRoutePoint *point, *cp;
    TrackRoute *route;
    float d, across, z;
    int fire = 0;

    point = car_get_route_point(h->CurrentCar, FIND_ROUTE);
    // The port's: the image reads address 0 for a NULL point.
    if (point != h->OldCarPoint && point != NULL && h->OldCarPoint != NULL) {
        route = car_get_route(h->CurrentCar, FIND_ROUTE);
        d = point->Position.x - h->OldCarPoint->Position.x;
        across = point->Position.y - h->OldCarPoint->Position.y;
        d = sqrtf(d * d + across * across);
        if (route != h->OldCarRoute
            || point_index(route, h->OldCarPoint) < point_index(route, point))
            d = -d;
        h->OldCarPoint = point;
        h->TargetDistance = h->TargetDistance + d;
        h->OldCarRoute = route;
    }
    chopper_adjust_bomb_target(h);
    if (h->NumSalvosReleased > 0) {
        h->TimeUntilNextSalvo = h->TimeUntilNextSalvo - SALVO_TICK;
        fire = h->TimeUntilNextSalvo < 0.0f;
    } else if (distance_to(h, &h->TargetPoint->Position) < BOMB_REACH) {
        // Within the road at the helicopter's point.
        cp = h->ChopperPoint;
        across = (h->CurrentPos.x - cp->Position.x) * cp->Direction.y
                 - (h->CurrentPos.y - cp->Position.y) * cp->Direction.x;
        if (0.0f < across)
            across = across - cp->RightWidth;
        else
            across = -(across + cp->LeftWidth);
        fire = across < 0.0f;
    }
    if (fire && helisheet_find_z_value(TheHeliSheet,
                                       (const bVector2 *)&h->CurrentPos, &z,
                                       NULL)) {
        chopper_find_ground_height(h);
        if (h->CurrentPos.z - h->GroundZ <= BOMB_HEIGHT) {
            chopper_fire_salvo(h);
            h->NumSalvosReleased++;
            h->TotalSalvos++;
            b = &BombRunBehaviours[h->BombRunType];
            h->Timeout = CHOPPER_TIMEOUT;
            h->TimeUntilNextSalvo = b->SalvoDelay;
            if (!(h->NumSalvosReleased < b->NumSalvos)) {
                h->Plan = CHOPPLAN_PURSUIT;
                return;
            }
        }
    }
    if (h->Timeout == 0.0f) {
        h->Plan = CHOPPLAN_PURSUIT;
        return;
    }
    chopper_follow_route(h, t, h->TargetRoute, h->TargetPoint, 1);
}

int32_t chopper_high_level_planning(struct Chopper *h, ChopperTarget *t)
{
    int32_t on_sheet = 0;
    uint32_t flags = 0;
    float z = 0.0f;

    h->Timeout = h->Timeout - PLAN_TICK;
    if (h->Timeout < 0.0f)
        h->Timeout = 0.0f;
    if (h->Plan != CHOPPLAN_END_CHASE) {
        bScaleAdd2(&t->Location,
                   (const bVector2 *)&h->CurrentCar->State.Position,
                   (const bVector2 *)&h->CurrentCar->State.Velocity,
                   PLAN_LEAD);
        on_sheet = helisheet_find_z_value(TheHeliSheet, &t->Location, &z,
                                          &flags);
    }
    if (h->Plan != CHOPPLAN_START_CHASE)
        chopper_find_route_point(h);
    t->DesiredSpeed = -1.0f;
    switch (h->Plan) {
    case CHOPPLAN_BOMBING_RUN:
        chopper_bomb_run_logic(h, t);
        break;
    case CHOPPLAN_HEAD_TO_STAKEOUT:
    case CHOPPLAN_AT_STAKEOUT:
        if (on_sheet && (distance_to(h, &t->Location) < STAKEOUT_GIVE_UP
                         || h->Timeout == 0.0f)) {
            h->Plan = CHOPPLAN_PURSUIT;
            break;
        }
        if (h->Plan != CHOPPLAN_HEAD_TO_STAKEOUT)
            break;
        if (distance_to(h, &h->TargetPoint->Position) < STAKEOUT_REACH) {
            h->Plan = CHOPPLAN_AT_STAKEOUT;
            h->Timeout = STAKEOUT_WAIT;
            t->Location.x = h->TargetPoint->Position.x;
            t->Location.y = h->TargetPoint->Position.y;
        } else {
            chopper_follow_route(h, t, h->TargetRoute, h->TargetPoint, 1);
        }
        break;
    case CHOPPLAN_START_CHASE:
        if (chopper_start_chase_logic(h, t, on_sheet, flags, z))
            return 1;
        break;
    case CHOPPLAN_END_CHASE:
        if (chopper_end_chase_logic(h, t))
            return 1;
        break;
    default:
        break;
    }
    if (h->Plan == CHOPPLAN_PURSUIT)
        chopper_clever_pursuit_plan(h, t, on_sheet, flags);
    chopper_adjust_target_in_bounds(h, t);
    chopper_adjust_target_local(h, t);
    return 0;
}

// ----------------------------------------------------------------- flying

// SetXAccel: the gain toward DesiredSpeed, 0x41200000; the share of the
// speed taken off the target's x, gp-28028; and the most it speeds up,
// 0x41a00000.
#define SPEED_GAIN         10.0f
#define SPEED_DAMP         0.1f
#define MAX_ACCEL          20.0f

// SetYAccel: no sideways acceleration from 0x42b40000 off the nose; the
// roll starts past 0x40a00000 of it, and stops at 0x41a00000.
#define SIDE_LIMIT         90.0f
#define ROLL_START         5.0f
#define ROLL_MAX           20.0f

// SetRotateTarget's degrees a second for a scale of 1, 0x42b40000.
#define ROTATE_RATE        90.0f

// HoverTime: still is at most gp-28024 in speed, near is within 0x40a00000
// of the target, and not speeding up is below gp-28020. It turns at
// SetRotateTarget's scale 1.
#define HOVER_STILL        0.001f
#define HOVER_NEAR         5.0f
#define HOVER_ACCEL        0.1f
#define HOVER_TURN         1.0f

// BAM to degrees, 0x3bb40000, and a turn, 0x43b40000.
#define BAM_TO_DEG         (360.0f / 65536.0f)
#define FULL_TURN          360.0f

// CheckMomentumWithinBounds: the acceleration's share, gp-28016; the
// look ahead, gp-28012; and the share of the speed it pushes back by,
// gp-28008, whose bits are 0x3e999999, one below 0.3f's. Its probe is
// AdjustTargetInBounds's 4.5.
#define MOMENTUM_ACCEL     0.05f
#define MOMENTUM_AHEAD     0.1f
#define MOMENTUM_PUSH      0.29999998f

// Think turns on the spot at most gp-28004 in speed and more than
// 0x41a00000 off the nose, at SetRotateTarget's scale 2.
#define TURN_STILL         0.001f
#define TURN_ANGLE         20.0f
#define TURN_SCALE         2.0f

void chopper_set_x_accel(struct Chopper *h, ChopperTarget *t)
{
    if (0.0f < t->DesiredSpeed && 0.0f < t->Location.x)
        h->Acceleration.x = (t->DesiredSpeed - h->Speed) * SPEED_GAIN;
    else
        h->Acceleration.x = chopper_adjust_by_think_time(
            h, t->Location.x - h->Speed * SPEED_DAMP);
    if (h->Acceleration.x < chopper_get_max_deceleration(h))
        h->Acceleration.x = chopper_get_max_deceleration(h);
    else if (MAX_ACCEL < h->Acceleration.x)
        h->Acceleration.x = MAX_ACCEL;
}

void chopper_set_y_accel(struct Chopper *h, ChopperTarget *t, float angle)
{
    float a;

    if (SIDE_LIMIT <= fabsf(angle))
        h->Acceleration.y = 0.0f;
    else
        h->Acceleration.y = chopper_adjust_by_think_time(h, t->Location.y);
    a = fabsf(h->Acceleration.y);
    h->DesiredRoll = 0.0f;
    if (!(ROLL_START < a))
        return;
    h->DesiredRoll = a - ROLL_START;
    if (ROLL_MAX < h->DesiredRoll)
        h->DesiredRoll = ROLL_MAX;
    if (h->Acceleration.y < 0.0f)
        h->DesiredRoll = -h->DesiredRoll;
}

void chopper_set_rotate_target(struct Chopper *h, float rot, float scale)
{
    float lim = scale * ROTATE_RATE;

    h->RotRate = rot;
    if (rot < -lim)
        h->RotRate = -lim;
    else if (lim < rot)
        h->RotRate = lim;
    h->DesiredRoll = 0.0f;
}

int32_t chopper_hover_time(struct Chopper *h, ChopperTarget *t)
{
    float d = sqrtf(t->Location.x * t->Location.x
                    + t->Location.y * t->Location.y);
    struct Car *car;
    float f;

    if (!(fabsf(h->Speed) <= HOVER_STILL) || !(d < HOVER_NEAR)
        || !(h->Acceleration.x < HOVER_ACCEL))
        return 0;
    h->MoveMode = CHOPMOVE_ROTATE;
    car = h->CurrentCar;
    if (h->Plan == CHOPPLAN_PURSUIT)
        f = BAM_TO_DEG * (float)car->State.Angle;
    else
        f = (float)bATan(car->State.Position.x - h->CurrentPos.x,
                         car->State.Position.y - h->CurrentPos.y)
            * BAM_TO_DEG;
    chopper_set_rotate_target(
        h, make_relative_angle(h->Yaw - (FULL_TURN - f)), HOVER_TURN);
    return 1;
}

void chopper_check_momentum_within_bounds(struct Chopper *h)
{
    float ay = h->Acceleration.y * MOMENTUM_ACCEL;
    float x = (h->Speed + h->Acceleration.x * MOMENTUM_ACCEL) * MOMENTUM_AHEAD;
    float push = h->Speed * MOMENTUM_PUSH;

    if (!chopper_test_location(h, x, ay + BOUNDS_PROBE))
        h->Acceleration.y = h->Acceleration.y - push;
    else if (!chopper_test_location(h, x, ay - BOUNDS_PROBE))
        h->Acceleration.y = h->Acceleration.y + push;
    if (!chopper_test_location(h, x + BOUNDS_PROBE, ay))
        h->Acceleration.x = h->Acceleration.x - push;
}

void chopper_think(struct Chopper *h)
{
    ChopperTarget t;
    float a;

    h->MoveMode = CHOPMOVE_PURSUIT;
    if (chopper_high_level_planning(h, &t))
        return;
    if (chopper_hover_time(h, &t))
        return;
    a = make_relative_angle((float)bATan(t.Location.x, t.Location.y)
                            * BAM_TO_DEG);
    if (fabsf(h->Speed) <= TURN_STILL && TURN_ANGLE < fabsf(a)) {
        h->MoveMode = CHOPMOVE_ROTATE;
        chopper_set_rotate_target(h, a, TURN_SCALE);
        return;
    }
    chopper_set_y_accel(h, &t, a);
    chopper_set_x_accel(h, &t);
    chopper_check_momentum_within_bounds(h);
}

void chopper_calc_chopper_rotation(struct Chopper *h, float step,
                                   const float *target, float *cur)
{
    float to = *target, from = *cur;
    float d = fabsf(to - from);

    (void)h;
    if (d < step)
        step = d;
    if (to < from)
        step = -step;
    *cur = from + step;
}

void chopper_subtract_from_yaw(struct Chopper *h, float f)
{
    float y = h->Yaw - f;

    h->Yaw = y;
    if (y < 0.0f)
        h->Yaw = y + FULL_TURN;
    else if (FULL_TURN < y)
        h->Yaw = y - FULL_TURN;
}

// ------------------------------------------------------------------ moving

// MoveChopper: still in z is at most gp-28000 (turning) or gp-27988
// (flying); the top speed, 0x42c80000; the pitch, gp-27996 of the speed
// and at most 0x41a00000; no yaw from the sideways step at most gp-27992,
// or at a speed of 0x3f800000 or less; a miss turns 0x40a00000, and the
// fourth gives up; the interest box's 1; the ease, 0x41a00000 a second.
#define ROTATE_STILL       0.001f
#define FLY_STILL          0.001f
#define TOP_SPEED          100.0f
#define PITCH_SCALE        0.15f
#define PITCH_MAX          20.0f
#define YAW_STEP_MIN       0.001f
#define YAW_SPEED_MIN      1.0f
#define MISS_TURN          5.0f
#define MOVE_TRIES         4
#define INTEREST_RADIUS    1.0f
#define EASE_RATE          20.0f

// TriggerDustEmitter: the dust's height, 0x41300000, and its share a unit
// below it, gp-27976.
#define DUST_HEIGHT        11.0f
#define DUST_SCALE         0.1f

// Fly: Think's period, gp-27972, and StuckTime's limit, 0x3f000000.
#define THINK_PERIOD       0.1f
#define STUCK_LIMIT        0.5f

void (*gMunitionEffectsDoTimestepFn)(float dt);

int32_t chopper_move(struct Chopper *h, float dt)
{
    bVector2 acc, d, v, vel, pos;
    float z, zv, step;
    uint32_t flags;
    int32_t side, tries = 0;

    if (h->MoveMode == CHOPMOVE_ROTATE) {
        chopper_subtract_from_yaw(h, h->RotRate * dt);
        zv = h->ZVelocity;
        if (!(fabsf(zv) <= ROTATE_STILL)) {
            h->CurrentPos.z = h->CurrentPos.z + zv * dt;
            if (zv < 0.0f
                && helisheet_find_z_value(TheHeliSheet,
                                          (const bVector2 *)&h->CurrentPos,
                                          &z, NULL)
                && h->CurrentPos.z < z) {
                h->CurrentPos.z = z;
                h->ZVelocity = 0.0f;
            }
        }
    } else {
        acc.x = dt * h->Acceleration.x;
        acc.y = dt * h->Acceleration.y;
        h->Speed = h->Speed + acc.x;
        if (h->Speed < 0.0f)
            h->Speed = 0.0f;
        else if (TOP_SPEED < h->Speed)
            h->Speed = TOP_SPEED;
        h->DesiredPitch = h->Speed * PITCH_SCALE;
        if (PITCH_MAX < h->DesiredPitch)
            h->DesiredPitch = PITCH_MAX;
        if (!(fabsf(acc.y) <= YAW_STEP_MIN) && YAW_SPEED_MIN < h->Speed) {
            float deg = (float)bATan(h->Speed, acc.y) * BAM_TO_DEG;

            if (FULL_TURN / 2.0f <= deg)
                deg = deg - FULL_TURN;
            chopper_subtract_from_yaw(h, deg * dt);
        }
        // Which side of the helicopter its route point is. The image reads
        // the point unguarded; the port takes a NULL one as on neither.
        side = 0;
        if (h->ChopperPoint != NULL) {
            d.x = h->ChopperPoint->Position.x - h->CurrentPos.x;
            d.y = h->ChopperPoint->Position.y - h->CurrentPos.y;
            chopper_rotate_to_chopper_coord(h, &d, &d);
            side = 0.0f < d.y;
        }
        for (;;) {
            v.x = h->Speed;
            v.y = 0.0f;
            rotate_vector(&vel, &v, h->Yaw);
            vel.x = vel.x * dt;
            vel.y = vel.y * dt;
            pos.x = h->CurrentPos.x + vel.x;
            pos.y = h->CurrentPos.y + vel.y;
            if (helisheet_find_z_value(TheHeliSheet, &pos, &z, &flags))
                break;
            if (++tries == MOVE_TRIES) {
                pos.x = h->CurrentPos.x;
                pos.y = h->CurrentPos.y;
                z = h->CurrentPos.z;
                flags = 0;
                break;
            }
            h->TimeUntilThink = 0.0f;
            chopper_subtract_from_yaw(h, side ? MISS_TURN : -MISS_TURN);
        }
        h->CurrentPos.x = pos.x;
        h->CurrentPos.y = pos.y;
        zv = h->ZVelocity;
        if (fabsf(zv) <= FLY_STILL) {
            h->CurrentPos.z = z;
        } else {
            h->CurrentPos.z = h->CurrentPos.z + zv * dt;
            if (zv < 0.0f && h->CurrentPos.z < z) {
                h->CurrentPos.z = z;
                h->ZVelocity = 0.0f;
            }
        }
        h->EmitDust = (int32_t)((flags ^ 1) & 1);
        topology_set_interest_bbox(&h->TopologyCoord,
                                   (const bVector2 *)&h->CurrentPos,
                                   INTEREST_RADIUS, &vel);
        chopper_find_ground_height(h);
        trackpath_coord_update_position(&h->TP,
                                        (const bVector2 *)&h->CurrentPos);
    }
    step = dt * EASE_RATE;
    chopper_calc_chopper_rotation(h, step, &h->DesiredPitch, &h->Pitch);
    chopper_calc_chopper_rotation(h, step, &h->DesiredRoll, &h->Roll);
    chopper_calc_matrix(h);
    return tries != MOVE_TRIES;
}

void chopper_trigger_dust_emitter(struct Chopper *h, float dt)
{
    bMatrix4 m;
    bNode *n;
    float s;

    bIdentity(&m);
    s = (DUST_HEIGHT - (h->CurrentPos.z - h->GroundZ)) * DUST_SCALE;
    m.v3.x = h->CurrentPos.x;
    m.v3.y = h->CurrentPos.y;
    m.v3.z = h->GroundZ;
    if (!(0.0f < s))
        return;
    if (1.0f < s)
        s = 1.0f;
    for (n = h->DustEmitters.next; n != &h->DustEmitters; n = n->next) {
        AcidEmitter *e = (AcidEmitter *)n;

        e->LocalWorld = m;
        acid_system_trigger_emitter(&WorldEffects, e, -s * dt, NULL);
    }
}

void chopper_draw(struct Chopper *h, float dt)
{
    chopper_update_world_object(h);
    if (h->EmitDust != 0)
        chopper_trigger_dust_emitter(h, dt);
}

void chopper_do_tweaker_triggers(struct Chopper *h)
{
    struct Car *car = pCurrentWorld->CarTable[0];

    if (h->New960 != 0 && h->CurrentCar != car)
        chopper_follow_this_car(h, car);
}

void chopper_fly(struct Chopper *h, float dt)
{
    int32_t moved;

    chopper_do_tweaker_triggers(h);
    if (gMunitionEffectsDoTimestepFn != NULL)
        gMunitionEffectsDoTimestepFn(dt);
    if (h->Plan == CHOPPLAN_EATING_DONUTS)
        return;
    h->TimeUntilThink = h->TimeUntilThink - dt;
    if (h->TimeUntilThink < 0.0f) {
        h->TimeUntilThink = h->TimeUntilThink + THINK_PERIOD;
        chopper_think(h);
    }
    if (h->Plan == CHOPPLAN_START_CHASE)
        return;
    moved = chopper_move(h, dt);
    chopper_draw(h, dt);
    if (moved) {
        h->StuckTime = 0.0f;
        return;
    }
    h->StuckTime = h->StuckTime + dt;
    if (STUCK_LIMIT <= h->StuckTime) {
        h->StuckTime = 0.0f;
        h->Plan = CHOPPLAN_END_CHASE;
    }
}
