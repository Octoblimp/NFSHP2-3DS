// cop -- tCop, tPlayerCop and tAICop. See cop.h.

#include "cop.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bmath.h"
#include "bmem.h"
#include "bslotpool.h"
#include "car.h"
#include "cardriver.h"
#include "carinit.h"
#include "carmodes.h"
#include "cartypeinfo.h"
#include "collisionbody.h"
#include "copdriver.h"
#include "copmgr.h"
#include "drivetarget.h"
#include "drivetargetrenderer.h"
#include "drivetrain.h"
#include "eefpu.h"
#include "realtime.h"
#include "trackroute.h"
#include "vtable.h"
#include "world.h"

int32_t nZonePermissionTable[36];
float   fCopMassTable[3] = { 1.5f, 1.75f, 2.0f };

void (*gPursuitRemoveCopFromPursuitFn)(tPursuit *p, tCop *c);
void (*gPursuitRemovePrimarySpeakerFn)(tPursuit *p, int32_t b);
void (*gCarDamageWreckFn)(void *damage);

static void unported(const char *name)
{
    fprintf(stderr, "cop: %s is not ported\n", name);
    abort();
}

// ----------------------------------------------------------------- tCop

tCop *tcop_construct(tCop *c, int32_t n)
{
    c->nCopNumber = n;
    c->pMyPursuit = NULL;
    c->vptr = TCOP_VTABLE;
    c->LogicState = LS_INVALID;
    return c;
}

void tcop_destruct(tCop *c, int32_t flags)
{
    c->vptr = TCOP_VTABLE;
    if (flags & 1)
        bFree(c);
}

void tcop_set_pursuit(tCop *c, tPursuit *p)
{
    c->pMyPursuit = p;
}

void tcop_set_desired_logic_state(tCop *c, eLogicState s)
{
    c->DesiredLogicState = s;
}

void tcop_set_desired_logic_sub_state(tCop *c, eLogicSubState s)
{
    c->DesiredLogicSubState = s;
}

// ----------------------------------------------------------- tPlayerCop

tPlayerCop *tplayercop_construct(tPlayerCop *c, struct Car *car, int32_t n)
{
    tcop_construct(&c->Base, n);
    c->Base.vptr = TPLAYERCOP_VTABLE;
    c->Base.pMyCar = car;
    c->nPrevSelection[0] = -1;
    c->fPrevSelectionTimer[0] = 0.0f;
    c->nPrevSelection[1] = -1;
    c->fPrevSelectionTimer[1] = 0.0f;
    c->bPrevCopLightState = 0;
    c->Base.DesiredLogicState = LS_INVALID;
    return c;
}

void tplayercop_destruct(tPlayerCop *c, int32_t flags)
{
    c->Base.vptr = TPLAYERCOP_VTABLE;
    tcop_destruct(&c->Base, flags);
}

// --------------------------------------------------------------- tAICop

void *taicop_new(void)
{
    return bSlotOMalloc(CopSlotPool);
}

void taicop_delete(void *p)
{
    bSlotFree(CopSlotPool, p);
}

tAICop *taicop_construct(tAICop *c, struct DriverInfo *info, int32_t n)
{
    static const bVector3 origin;
    Car          *car;
    CarTypeInfo  *type;
    World        *w;
    Car          *tail;
    CopDriver    *drv;
    float         scale;

    tcop_construct(&c->Base, n);
    c->nMyRoadBlockIndex = 0;
    c->RouteInfo.Route = NULL;
    c->RouteInfo.Point = NULL;
    c->fSubStateTimer = 0.0f;
    c->Base.vptr = TAICOP_VTABLE;

    car = (Car *)bMalloc((int)sizeof(Car), "Car (cop)", 0, CAR_MEMORY_POOL);
    car = car_construct(car, info, &origin, 0, -1.0f);
    type = car->pCarTypeInfo;
    c->Base.pMyCar = car;
    scale = fCopMassTable[pCopManager->nDifficultyLevel] / type->Body.Mass;

    // On the end of the world's CarList.
    w = pCurrentWorld;
    tail = w->CarList.prev;
    tail->Link.next = &car->Link;
    w->CarList.prev = car;
    car->Link.prev = &tail->Link;
    car->Link.next = (CarNode *)(void *)&w->CarList;

    // The mass to the table's, and the inertia with it, all four lanes of
    // the first three rows (`vmulx.xyzw`). The type is shared, so a second
    // cop of the same type finds the mass already there and scales by 1.
    type->Body.Mass = type->Body.Mass * scale;
    {
        bVector4 *rows[3] = { &type->Body.InertiaTensor.v0,
                              &type->Body.InertiaTensor.v1,
                              &type->Body.InertiaTensor.v2 };
        int k;

        for (k = 0; k < 3; k++) {
            rows[k]->x *= scale;
            rows[k]->y *= scale;
            rows[k]->z *= scale;
            rows[k]->w *= scale;
        }
    }

    car_set_control_mode(car, COP_CONTROL);
    drv = (CopDriver *)(void *)car->pCarController;
    drv->State = eCDS_PARKED;
    drv->nCopIndex = c->Base.nCopNumber;
    car_set_movement_mode(car, eNO_MOVEMENT);
    car->RenderingEnabled = 0;

    c->fSecondsInPhysicsMode = 0.0f;
    c->Base.DesiredLogicState = LS_LIMBO;
    c->New48.y = 0.0f;
    c->New48.x = 0.0f;
    c->MyDLOffset.y = 0.0f;
    c->MyDLOffset.x = 0.0f;
    c->fFlankSide = 0.0f;
    c->fMovementModeSwitchDelay = 0.0f;
    c->nDrivingLineIndex = 0;
    c->New64 = 6.0f;
    c->New68 = 3.0f;
    car->bVisibleOnTrackMap = 0;
    car->TheSirenMode = 0;
    // `sw zero,2056`: CopLights as a word, as Car's constructor stores it.
    car->CopLights = 0;
    memset(car->_hole2025, 0, sizeof car->_hole2025);
    init_zone_permission_table();
    c->New32 = 0.0f;
    return c;
}

void taicop_destruct(tAICop *c, int32_t flags)
{
    c->Base.vptr = TAICOP_VTABLE;
    tcop_destruct(&c->Base, 0);
    if (flags & 1)
        taicop_delete(c);
}

void taicop_clear_pursuit(tAICop *c)
{
    if (c->Base.pMyPursuit != NULL) {
        if (gPursuitRemoveCopFromPursuitFn == NULL)
            unported("tPursuit::RemoveCopFromPursuit");
        gPursuitRemoveCopFromPursuitFn(c->Base.pMyPursuit, &c->Base);
        tcop_set_pursuit(&c->Base, NULL);
    }
}

void taicop_clear_speed_trap(tAICop *c)
{
    if (c->pMySpeedTrap != NULL) {
        c->pMySpeedTrap->cop = NULL;
        c->pMySpeedTrap = NULL;
    }
}

void taicop_disable_my_car(tAICop *c, int32_t b)
{
    Car      *mine = c->Base.pMyCar;
    tPursuit *pu;

    if (c->Base.LogicState == LS_LIMBO || c->Base.LogicState == LS_DISABLED)
        return;
    if (mine->pCarDamage != NULL) {
        if (gCarDamageWreckFn == NULL)
            unported("CarDamage's wreck (0x001b5bc8)");
        gCarDamageWreckFn(mine->pCarDamage);
    }
    pu = c->Base.pMyPursuit;
    if (pu == NULL) {
        tcop_set_desired_logic_state(&c->Base, LS_DISABLED);
        return;
    }
    // Retail reads the chased car with no test of NULL.
    if (pu->pChasedCar->pPlayer != NULL) {
        Car  *ch = pu->pChasedCar;
        float dy = ch->State.Position.y - mine->State.Position.y;
        float dx = ch->State.Position.x - mine->State.Position.x;

        if (sqrtf(dx * dx + dy * dy) < 75.0f) {
            if (gPursuitRemovePrimarySpeakerFn == NULL)
                unported("tPursuit::RemovePrimarySpeaker");
            gPursuitRemovePrimarySpeakerFn(pu, b);
            pu = c->Base.pMyPursuit;
        }
    }
    {
        Car *ch = pu->pChasedCar;

        if (ch != NULL && ch->pPlayer != NULL)
            pCopManager->fSpeedTrapSpawnTimer[ch->CarIndex] += 10.0f;
    }
    taicop_clear_pursuit(c);
    tcop_set_desired_logic_state(&c->Base, LS_DISABLED);
}

void cop_disable_my_car(tCop *c, int32_t b)
{
    taicop_disable_my_car((tAICop *)(void *)c, b);
}

// ---------------------------------------------------- the drive target

int32_t taicop_is_near_pursuit_target(const tAICop *c)
{
    const tPursuit *p = c->Base.pMyPursuit;
    const Car      *ch, *mine;
    float           dx, dy;

    if (p == NULL)
        return 0;
    ch = p->pChasedCar;
    mine = c->Base.pMyCar;
    dy = ch->State.Position.y - mine->State.Position.y;
    dx = ch->State.Position.x - mine->State.Position.x;
    return sqrtf(dx * dx + dy * dy) < 20.0f;
}

void taicop_initialize_drive_target(tAICop *c)
{
    bVector2 *pos = (bVector2 *)(void *)&c->Base.pMyCar->State.Position;
    int32_t   ok = 0;

    c->RouteInfo.Point = NULL;
    c->RouteInfo.Route = NULL;

    if (c->Base.DesiredLogicState == LS_DRIVING_ON_PATROL) {
        if (c->Base.LogicSubState == LSS_PATROL_ONCOMING)
            ok = ai_get_nearest_route_point(&c->RouteInfo, pos,
                                            ONCOMING_TRAFFIC_ROUTES, 2, 0.0f);
        if (ok) {
            const TrackRoutePoint *rp = car_get_route_point(c->Base.pMyCar, 1);
            const TrackRoutePoint *pt = c->RouteInfo.Point;
            float lat = (pt->Position.x - rp->Position.x) * rp->Direction.y
                      - (pt->Position.y - rp->Position.y) * rp->Direction.x;
            float w;

            if (lat < 0.0f) {
                lat = -lat;
                w = rp->LeftWidth;
            } else {
                w = rp->RightWidth;
            }
            if (w < lat)
                ok = 0;
            if (ok)
                return;
        }
        ai_get_nearest_route_point(&c->RouteInfo, pos, ALL_RACING_ROUTES, 2,
                                   0.0f);
    } else if (c->Base.DesiredLogicState == LS_HOT_PURSUIT) {
        Car *car;

        switch (c->Base.LogicSubState) {
        case LSS_BLOCK:
        case LSS_GET_AHEAD:
            c->RouteInfo.Route = car_get_route(c->Base.pMyPursuit->pChasedCar,
                                               1);
            car = c->Base.pMyPursuit->pChasedCar;
            break;
        case LSS_ACQUIRE:
            c->RouteInfo.Route = car_get_route(c->Base.pMyCar, 1);
            car = c->Base.pMyCar;
            break;
        default:
            return;
        }
        c->RouteInfo.Point = car_get_route_point(car, 1);
    }
}

// (pos - pt) . pt's direction: above 0 once pos is past pt.
static float past_point(const bVector2 *pos, const TrackRoutePoint *pt)
{
    return (pos->x - pt->Position.x) * pt->Direction.x
         + (pos->y - pt->Position.y) * pt->Direction.y;
}

void taicop_update_drive_target(tAICop *c, const bVector2 *pos,
                                int32_t keep)
{
    DriveTarget          *t = &c->Base.pMyCar->pCarDriver->MyDriveTarget;
    NearestRoutePointInfo info;
    int32_t               i;

    if (keep == 0) {
        int32_t again = 0;
        int32_t n = 0;

        // n counts the tests passed, one past the steps taken. Exactly ten
        // (the tenth step and then no further) starts again, once; more
        // (stuck on a route's last point) does not.
        for (;;) {
            if (n == 10) {
                taicop_initialize_drive_target(c);
                again = 1;
                n = 0;
            }
            if (0.0f < past_point(pos, c->RouteInfo.Point) && n++ < 10) {
                do {
                    info = c->RouteInfo;
                    ai_get_next_route_point(&info);
                    if (info.Point != NULL)
                        c->RouteInfo = info;
                } while (0.0f < past_point(pos, c->RouteInfo.Point)
                         && n++ < 10);
            }
            if (n != 10 || again)
                break;
        }
    }

    drivetarget_clear(t, NULL, 0.0f);
    info = c->RouteInfo;
    for (i = 0; i < 20; ) {
        bVector3 v;
        float    l = c->MyDLOffset.y;

        if (c->nDrivingLineIndex != -1)
            l += trpoint_get_driving_line_offset(info.Point,
                                                 c->nDrivingLineIndex);
        trpoint_get_position3(info.Point, &v, c->MyDLOffset.x, l);
        drivetarget_add_point3(t, &v, (int8_t)info.Route->RouteNumber,
                               (int16_t)troute_get_point_number(info.Route,
                                                                info.Point),
                               0, 0, NULL);
        ai_get_next_route_point(&info);
        i++;
        if (info.Point == NULL)
            break;
    }

    if (keep == 0) {
        t->Points[0].y = pos->y;
        t->Points[0].x = pos->x;
    }
}

// ---------------------------------------------------------------- Think

void (*gAICopInitSpeedTrapLogicFn)(tAICop *c);
void (*gAICopInitRoadBlockLogicFn)(tAICop *c);
void (*gAICopDoSpeedTrapLogicFn)(tAICop *c);
void (*gAICopDoRoadBlockLogicFn)(tAICop *c);
void (*gAICopDoDrivingOnPatrolLogicFn)(tAICop *c);
void (*gAICopDoHotPursuitLogicFn)(tAICop *c);
void (*gAICopDoCaughtSpeederLogicFn)(tAICop *c);
void (*gPlayerCopThinkFn)(tPlayerCop *c);

#define COP_UPRIGHT_Z        0.1f        // 3dcccccd, gp-26932
#define COP_MPS_TO_MPH       2.237f      // 400f2b02, gp-26928
#define COP_UPSET_MPH        10.0f       // 41200000
#define COP_DISABLED_BRAKE   0.3f        // 3e99999a, gp-26924
#define COP_SKID_SPEED       17.88109f   // 418f0c79, gp-26920
#define COP_SPIN_RATE        1.0f        // 3f800000
#define COP_SWITCH_DELAY     0.1f        // 3dcccccd, gp-26916 and gp-26912
#define COP_AIRBORNE_MAX_Z   2.0f        // 40000000
#define COP_OFFSET_RATE_X    6.0f        // 40c00000, gp-15536
#define COP_OFFSET_RATE_Y    3.0f        // 40400000, gp-15532
#define COP_FAR_FROM_PLAYERS 250.0f      // 437a0000

// gp-13336, a u16 that _GLOBAL_$I$fNearFollowDistances (0x00230d00) sets
// at start-up to 1820, 10 degrees as a BAM: how far the car's velocity
// may point off its heading before a car going fast is taken to be
// skidding. It is 0 in the image itself.
#define COP_SKID_ANGLE       1820

typedef void (*DriverDesiredSpeedFn)(void *self, float speed, float time,
                                     float tolerance, int32_t allowed);

// The car's driver's SetDesiredSpeed, through its table, allowed.
static void set_desired_speed(CarDriver *d, float speed, float time,
                              float tolerance)
{
    const VtEntry *e = vt_slot(d->_vtable, CARDRIVER_VT_SET_DESIRED_SPEED);

    ((DriverDesiredSpeedFn)e->fn)(vt_this(d, e), speed, time, tolerance, 1);
}

// `sw` to retail's 2056: CopLights as a word, which zeroes the three bytes
// after it as well.
static void set_cop_lights(Car *car, int8_t v)
{
    car->CopLights = v;
    memset(car->_hole2025, 0, sizeof car->_hole2025);
}

// GetNumWheelsOnGround, 0x001cad80: how many of the four
// WheelTouchingGround bytes are not 0.
static int32_t num_wheels_on_ground(const Car *car)
{
    int32_t n = 0;
    int     i;

    for (i = 0; i < 4; i++)
        if (car->State.WheelTouchingGround[i] != 0)
            n++;
    return n;
}

void taicop_hold_position(tAICop *c)
{
    Car       *car = c->Base.pMyCar;
    CarDriver *d = car->pCarDriver;

    if (d != NULL)
        drivetarget_clear((DriveTarget *)(void *)d, NULL, 0.0f);
    // Retail adds the point with no test of the driver.
    drivetarget_add_point3((DriveTarget *)(void *)d, &car->State.Position, -1,
                           -1, -1, 0, NULL);
}

void taicop_do_limbo_logic(tAICop *c)
{
    taicop_hold_position(c);
    if (c->Base.LogicSubState == LSS_LIMBO_DISABLED
        && c->fSubStateTimer == 0.0f)
        c->Base.LogicSubState = LSS_LIMBO_READY;
}

void taicop_do_disabled_logic(tAICop *c)
{
    taicop_hold_position(c);
    if (!(world_get_distance_to_closest_player_2d(pCurrentWorld,
              (const bVector2 *)(const void *)&c->Base.pMyCar->State.Position)
          < COP_FAR_FROM_PLAYERS))
        tcop_set_desired_logic_state(&c->Base, LS_LIMBO);
}

void taicop_do_guard_location_logic(tAICop *c)
{
    taicop_hold_position(c);
}

void taicop_movement_mode_transitions(tAICop *c)
{
    Car         *car = c->Base.pMyCar;
    MovementMode mode = car->TheMovementMode;

    if (mode == eNO_MOVEMENT || c->Base.DesiredLogicState == LS_DISABLED)
        return;

    if (mode != COP_MOVEMENT) {
        float t = c->fSecondsInPhysicsMode + WorldTimeElapsed;
        int   reset = 0;

        c->fSecondsInPhysicsMode = t;
        if (!(0.0f <= t))
            return;
        if (num_wheels_on_ground(car) < 4) {
            reset = 1;
        } else {
            const bVector3 *w = &car->State.AngularVelocity;
            bPolar          pol;
            int32_t         off;

            bToPolar(&pol, (const bVector2 *)(const void *)&car->State.Velocity);
            off = (int16_t)(uint16_t)(pol.a - car->State.Angle);
            if (off < 0)
                off = -off;
            if (COP_SKID_ANGLE < (uint16_t)off
                && COP_SKID_SPEED < car->State.VelocityMagnitude)
                reset = 1;
            else if (COP_SPIN_RATE
                     < sqrtf((w->x * w->x + w->y * w->y) + w->z * w->z))
                reset = 1;
        }
        if (reset)
            c->fMovementModeSwitchDelay = COP_SWITCH_DELAY;
        t = c->fMovementModeSwitchDelay - WorldTimeElapsed;
        c->fMovementModeSwitchDelay = t;
        if (t <= 0.0f) {
            c->fMovementModeSwitchDelay = 0.0f;
            car_set_movement_mode(car, COP_MOVEMENT);
        }
        return;
    }

    c->fSecondsInPhysicsMode = 0.0f;
    if (((CopMover *)(void *)car->pCarMover)->bIsAirborne == 0)
        return;
    {
        bVector3  *v = &car->State.Velocity;
        CarDriver *d;

        if (COP_AIRBORNE_MAX_Z < v->z)
            v->z = COP_AIRBORNE_MAX_Z;
        car->State.VelocityMagnitude =
            sqrtf((v->x * v->x + v->y * v->y) + v->z * v->z);
        car->State.MatrixValid = 0;
        c->fMovementModeSwitchDelay = COP_SWITCH_DELAY;
        car_set_movement_mode(car, MELLOW_MOVEMENT);
        d = car->pCarDriver;
        d->DesiredGear = AUTOMATIC;
        d->Brake = 0.0f;
        d->Throttle = 1.0f;
        d->EBrake = 0.0f;
        d->Steering = 0;
        set_desired_speed(d, car->State.ForwardSpeed, 0.5f, d->Brake);
    }
}

void taicop_handle_state_transitions(tAICop *c, eLogicState from,
                                     eLogicState to)
{
    Car       *car = c->Base.pMyCar;
    CopDriver *drv = (CopDriver *)(void *)car->pCarController;

    c->fSubStateTimer = 0.0f;

    // Leaving.
    if (from == LS_DISABLED) {
        copmanager_reset_all_damage(pCopManager, car);
    } else if (from == LS_LIMBO) {
        collisionbody_enable_collisions(&car->pDynamicCollisionBody->Dynamic.Body);
        car->RenderingEnabled = 1;
        car_set_movement_mode(car, COP_MOVEMENT);
        copmanager_reset_all_damage(pCopManager, car);
    } else if (from == LS_SPEED_TRAP) {
        taicop_clear_speed_trap(c);
    }

    // Entering.
    switch (to) {
    case LS_LIMBO:
        taicop_clear_pursuit(c);
        car->bVisibleOnTrackMap = 0;
        car->TheSirenMode = SIREN_MODE_NONE;
        set_cop_lights(car, 0);
        car_set_movement_mode(car, eNO_MOVEMENT);
        drv->State = eCDS_PARKED;
        collisionbody_disable_collisions(
            &car->pDynamicCollisionBody->Dynamic.Body);
        car->RenderingEnabled = 0;
        if (from == LS_DISABLED) {
            c->Base.LogicSubState = LSS_LIMBO_DISABLED;
            c->fSubStateTimer = 1.0f;
        } else {
            c->Base.LogicSubState = LSS_LIMBO_READY;
        }
        break;
    case LS_DISABLED: {
        CarDriver *d;

        taicop_clear_speed_trap(c);
        taicop_clear_pursuit(c);
        drv->State = eCDS_DISABLED;
        c->Base.LogicSubState = LSS_NONE;
        car->TheSirenMode = SIREN_MODE_BROKEN;
        set_cop_lights(car, 1);
        car->bVisibleOnTrackMap = 0;
        car_set_movement_mode(car, MELLOW_MOVEMENT);
        d = car->pCarDriver;
        d->Throttle = 0.0f;
        d->Brake = COP_DISABLED_BRAKE;
        d->EBrake = 1.0f;
        d->SportGear = AUTOMATIC;
        d->Steering = 0;
        d->DesiredGear = AUTOMATIC;
        set_desired_speed(d, d->Throttle, 10.0f, d->Throttle);
        break;
    }
    case LS_SPEED_TRAP:
        copmanager_reset_all_damage(pCopManager, car);
        if (gAICopInitSpeedTrapLogicFn != NULL)
            gAICopInitSpeedTrapLogicFn(c);
        break;
    case LS_ROAD_BLOCK:
        copmanager_reset_all_damage(pCopManager, car);
        if (gAICopInitRoadBlockLogicFn != NULL)
            gAICopInitRoadBlockLogicFn(c);
        break;
    case LS_DRIVING_ON_PATROL:
        taicop_clear_pursuit(c);
        car->bVisibleOnTrackMap = 0;
        taicop_initialize_drive_target(c);
        taicop_update_drive_target(
            c, (const bVector2 *)(const void *)&car->State.Position, 0);
        drv->State = eCDS_PATROLLING;
        set_cop_lights(car, 0);
        car->TheSirenMode = SIREN_MODE_NONE;
        break;
    case LS_HOT_PURSUIT:
        set_cop_lights(car, 2);
        drv->State = eCDS_PURSUIT;
        c->Base.DesiredLogicSubState = LSS_PURSUIT_FOLLOW;
        car->TheSirenMode = SIREN_MODE_01;
        car->bVisibleOnTrackMap = 1;
        c->Base.LogicSubState = LSS_NONE;
        break;
    case LS_CAUGHT_SPEEDER:
        tcop_set_pursuit(&c->Base, NULL);
        drv->State = eCDS_PARKED;
        c->Base.LogicSubState = LSS_CAUGHTSPEEDER_TICKETING;
        set_cop_lights(car, 1);
        car->bVisibleOnTrackMap = 1;
        car->TheSirenMode = SIREN_MODE_NONE;
        break;
    case LS_GUARD_LOCATION:
        taicop_clear_speed_trap(c);
        taicop_clear_pursuit(c);
        copmanager_reset_all_damage(pCopManager, car);
        drv->State = eCDS_PARKED;
        set_cop_lights(car, 0);
        c->Base.LogicSubState = LSS_NONE;
        car->bVisibleOnTrackMap = 0;
        car->TheSirenMode = SIREN_MODE_NONE;
        break;
    default:
        break;
    }
}

static void run_logic(void (*fn)(tAICop *c), tAICop *c)
{
    if (fn != NULL)
        fn(c);
}

void taicop_think(tAICop *c)
{
    Car  *car;
    float t, dx, dy, sx, sy;

    if (0.0f < c->New32)
        c->New32 = c->New32 - WorldTimeElapsed;
    car = c->Base.pMyCar;
    if (CameraFollowThisCarInstead == car->DriverNumber)
        drivetargetrenderer_set_target_to_render(
            &TheDriveTargetRenderer, (DriveTarget *)(void *)car->pCarDriver);
    taicop_movement_mode_transitions(c);

    // On its side or its roof, and all but stopped; or a tire blown.
    car = c->Base.pMyCar;
    if (car->State.BodyMatrix.v2.z <= COP_UPRIGHT_Z
        && car->State.VelocityMagnitude * COP_MPS_TO_MPH < COP_UPSET_MPH)
        taicop_disable_my_car(c, 1);
    if (c->Base.pMyCar->BlownTireBits != 0)
        taicop_disable_my_car(c, 0);

    t = c->fSubStateTimer - WorldTimeElapsed;
    c->fSubStateTimer = t;
    if (t < 0.0f)
        c->fSubStateTimer = 0.0f;

    if (c->Base.LogicState != c->Base.DesiredLogicState) {
        taicop_handle_state_transitions(c, c->Base.LogicState,
                                        c->Base.DesiredLogicState);
        c->Base.LogicState = c->Base.DesiredLogicState;
    }
    switch (c->Base.LogicState) {
    case LS_LIMBO:
        taicop_do_limbo_logic(c);
        break;
    case LS_DISABLED:
        taicop_do_disabled_logic(c);
        break;
    case LS_SPEED_TRAP:
        run_logic(gAICopDoSpeedTrapLogicFn, c);
        break;
    case LS_ROAD_BLOCK:
        run_logic(gAICopDoRoadBlockLogicFn, c);
        break;
    case LS_DRIVING_ON_PATROL:
        run_logic(gAICopDoDrivingOnPatrolLogicFn, c);
        break;
    case LS_HOT_PURSUIT:
        run_logic(gAICopDoHotPursuitLogicFn, c);
        break;
    case LS_CAUGHT_SPEEDER:
        run_logic(gAICopDoCaughtSpeederLogicFn, c);
        break;
    case LS_GUARD_LOCATION:
        taicop_do_guard_location_logic(c);
        break;
    default:
        break;
    }

    // New48 eases toward MyDLOffset, each part by its sign at its own rate
    // (6 and 3 a second, set again every frame), or the rest of the way
    // when that is nearer. A part already there divides 0 by 0: the EE's
    // FLT_MAX, which leaves it there whatever the frame's time.
    dx = c->MyDLOffset.x - c->New48.x;
    dy = c->MyDLOffset.y - c->New48.y;
    sx = ee_mul(ee_mul(ee_div(dx, fabsf(dx)), c->New64), WorldTimeElapsed);
    sy = ee_mul(ee_mul(ee_div(dy, fabsf(dy)), c->New68), WorldTimeElapsed);
    if (fabsf(dx) < fabsf(sx))
        c->New48.x = c->New48.x + dx;
    else
        c->New48.x = c->New48.x + sx;
    if (fabsf(dy) < fabsf(sy))
        c->New48.y = c->New48.y + dy;
    else
        c->New48.y = c->New48.y + sy;
    c->New64 = COP_OFFSET_RATE_X;
    c->New68 = COP_OFFSET_RATE_Y;
}

// ------------------------------------------------------------ the zones

void init_zone_permission_table(void)
{
    static const int32_t init[36] = {
        0, 0, 0, 0, 1, 0,
        1, 0, 1, 0, 1, 1,
        1, 1, 0, 1, 1, 0,
        1, 0, 1, 0, 1, 1,
        1, 1, 1, 1, 0, 1,
        1, 1, 0, 1, 1, 0,
    };

    memcpy(nZonePermissionTable, init, sizeof init);
}

int32_t request_zone_permission(int32_t a, int32_t b)
{
    if (a == 6 || b == 6)
        return 1;
    return nZonePermissionTable[a + b * 6];
}

int32_t get_zone_from_sub_state(eLogicSubState s, float side)
{
    switch (s) {
    case LSS_PURSUIT_FOLLOW:
        return 4;
    case LSS_FOLLOW_OFFSET:
        return side < 0.0f ? 3 : 5;
    case LSS_FLANK:
    case LSS_BUMP:
    case LSS_GET_AHEAD:
        return side < 0.0f ? 1 : 2;
    case LSS_BLOCK:
        return 0;
    default:
        // LOW_SPEED_CLOSE_FOLLOW, FOLLOW_BACKWARDS, ACQUIRE, STOP, the rest.
        return 6;
    }
}

// ----------------------------------------------------------- the tables

typedef void (*DtorFn)(void *self, int32_t flags);

static void tcop_dtor_entry(void *self, int32_t flags)
{
    tcop_destruct((tCop *)self, flags);
}

static void tplayercop_dtor_entry(void *self, int32_t flags)
{
    tplayercop_destruct((tPlayerCop *)self, flags);
}

static void taicop_dtor_entry(void *self, int32_t flags)
{
    taicop_destruct((tAICop *)self, flags);
}

static int32_t taicop_is_ai_controlled(void *self)
{
    (void)self;
    return 1;                                   // 0x00230d60
}

static int32_t tplayercop_is_ai_controlled(void *self)
{
    (void)self;
    return 0;                                   // 0x00230d98
}

static void pure_virtual(void *self)
{
    (void)self;
    unported("tCop's pure virtual");            // __pure_virtual, 0x002a0550
}

static void taicop_think_entry(void *self)
{
    taicop_think((tAICop *)self);
}

static void tplayercop_think_entry(void *self)
{
    if (gPlayerCopThinkFn != NULL)
        gPlayerCopThinkFn((tPlayerCop *)self);
}

static void taicop_snapshot_entry(void *self)
{
    (void)self;
    unported("tAICop::DoSnapshot (0x0022dd20)");
}

static void tplayercop_snapshot_entry(void *self)
{
    (void)self;
    unported("tPlayerCop::DoSnapshot (0x0022d7e8)");
}

static const VtEntry tcop_vt[] = {
    { 0, 0, NULL },
    { 0, 0, (VtFn)tcop_dtor_entry },            //  8  0x0022d418
    { 0, 0, (VtFn)pure_virtual },               // 16
    { 0, 0, (VtFn)pure_virtual },               // 24
    { 0, 0, (VtFn)pure_virtual },               // 32
};

static const VtEntry tplayercop_vt[] = {
    { 0, 0, NULL },
    { 0, 0, (VtFn)tplayercop_dtor_entry },      //  8  0x0022d5b0
    { 0, 0, (VtFn)tplayercop_is_ai_controlled },// 16  0x00230d98
    { 0, 0, (VtFn)tplayercop_think_entry },     // 24  0x0022d5c8
    { 0, 0, (VtFn)tplayercop_snapshot_entry },  // 32  0x0022d7e8
};

static const VtEntry taicop_vt[] = {
    { 0, 0, NULL },
    { 0, 0, (VtFn)taicop_dtor_entry },          //  8  0x0022dcc0
    { 0, 0, (VtFn)taicop_is_ai_controlled },    // 16  0x00230d60
    { 0, 0, (VtFn)taicop_think_entry },         // 24  0x0022df88
    { 0, 0, (VtFn)taicop_snapshot_entry },      // 32  0x0022dd20
};

void cop_install_vtables(void)
{
    vt_install(TCOP_VTABLE, tcop_vt,
               (int)(sizeof tcop_vt / sizeof tcop_vt[0]));
    vt_install(TPLAYERCOP_VTABLE, tplayercop_vt,
               (int)(sizeof tplayercop_vt / sizeof tplayercop_vt[0]));
    vt_install(TAICOP_VTABLE, taicop_vt,
               (int)(sizeof taicop_vt / sizeof taicop_vt[0]));
}
