// chopper -- see chopper.h.

#include "chopper.h"

#include <float.h>
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
