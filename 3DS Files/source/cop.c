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
#include "coputil.h"
#include "drivetarget.h"
#include "drivetargetrenderer.h"
#include "drivetrain.h"
#include "eefpu.h"
#include "race.h"
#include "realtime.h"
#include "trackroute.h"
#include "vtable.h"
#include "world.h"

int32_t nZonePermissionTable[36];
float   fCopMassTable[3] = { 1.5f, 1.75f, 2.0f };

void (*gPursuitRemoveCopFromPursuitFn)(tPursuit *p, tCop *c);
void (*gPursuitRemovePrimarySpeakerFn)(tPursuit *p, int32_t b);
void (*gCarDamageWreckFn)(void *damage);
int32_t (*gCopManagerRequestPursuitFn)(tCopManager *m, tCop *c, Car *car);

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
#define COP_TRAP_WAIT        15.0f       // 41700000
#define COP_OFF_SPOT         0.01f       // 3c23d70a, gp-26908 and gp-26900
#define COP_OFF_HEADING      100.0f      // 42c80000, in BAM
#define COP_SEARCH_XY        45.0f       // 42340000
#define COP_SEARCH_Z         2.5f        // 40200000
#define COP_FAST_MPH         80.0f       // 42a00000, by gp-26904's 2.237
#define COP_ROADBLOCK_GRACE  3.0f        // 40400000
#define COP_SIGHT_RANGE      50.0f       // 42480000
#define COP_SIGHT_AHEAD      20.0f       // 41a00000

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

// ------------------------------------- radar traps, roadblocks, patrols

void taicop_teleport(tAICop *c, const bVector2 *pos, uint16_t ang)
{
    Car     *car = c->Base.pMyCar;
    bVector3 v;

    if (car == NULL)
        return;
    car_set_movement_mode(car, COP_MOVEMENT);
    // Retail's stack vector: x, y and 0; its w is left as it was.
    memset(&v, 0, sizeof v);
    v.x = pos->x;
    v.y = pos->y;
    v.z = 0.0f;
    car_reset_to_position(car, &v, 0.0f, ang);
}

void taicop_set_speed_trap(tAICop *c, tSpeedTrap *t)
{
    c->pMySpeedTrap = t;
    t->cop = &c->Base;
    taicop_teleport(c, &t->v2Position, t->ang);
    tcop_set_desired_logic_state(&c->Base, LS_SPEED_TRAP);
}

void taicop_set_road_block(tAICop *c, tRoadBlock *rb, tPursuit *p,
                           int32_t i)
{
    tcop_set_pursuit(&c->Base, p);
    c->nMyRoadBlockIndex = i;
    taicop_teleport(c, &rb->CopPos[i], rb->CopAng[i]);
    tcop_set_desired_logic_state(&c->Base, LS_ROAD_BLOCK);
}

int32_t taicop_is_valid_pursuit_target(tAICop *c, Car *car, int32_t b)
{
    tCopManager            *m = pCopManager;
    const tCarPulloverInfo *pl = (const tCarPulloverInfo *)(const void *)
        ((const uint8_t *)m + COPMANAGER_PULLOVERS);
    int16_t                 idx = car->CarIndex;
    Car                    *pcar = NULL;

    (void)c;
    if (m->nPlayerCopIndex != -1 && m->Cops[m->nPlayerCopIndex] != NULL)
        pcar = m->Cops[m->nPlayerCopIndex]->pMyCar;
    if (car == pcar)
        return 0;
    if (pl[idx].bActive != 0)
        return 0;
    if (0.0f < m->fPursuableTimer[idx])
        return 0;
    if (car_caused_recent_collision(car) != NULL)
        return 1;
    if (!b)
        return 0;
    if (COP_FAST_MPH < fabsf(car->State.ForwardSpeed * COP_MPS_TO_MPH))
        return 1;
    return copmanager_is_being_pursued(m, car) != NULL;
}

int32_t taicop_can_patroller_see_this_car(const tAICop *c, const Car *car)
{
    const Car *mine = c->Base.pMyCar;
    float      vx = car->State.Velocity.x, vy = car->State.Velocity.y;
    float      dy = car->State.Position.y - mine->State.Position.y;
    float      dx = car->State.Position.x - mine->State.Position.x;
    float      s, inv;

    if (!(sqrtf(dx * dx + dy * dy) < COP_SIGHT_RANGE))
        return 0;
    s = sqrtf(vx * vx + vy * vy);
    if (!(0.0f < s))
        return 0;
    inv = 1.0f / s;
    return COP_SIGHT_AHEAD <= vx * inv * dx + vy * inv * dy;
}

// What the two Init logics share: no sub-state, off the map, stopped and
// parked. Retail's `sqc2` of the zero velocity takes its w from the
// stack; the port's is left as it was.
static void park(tAICop *c)
{
    Car *car = c->Base.pMyCar;

    c->Base.LogicSubState = LSS_NONE;
    car->bVisibleOnTrackMap = 0;
    car->State.ForwardSpeed = 0.0f;
    ((CopDriver *)(void *)car->pCarController)->State = eCDS_PARKED;
    car->State.Velocity.x = 0.0f;
    car->State.Velocity.y = 0.0f;
    car->State.Velocity.z = 0.0f;
    car->State.VelocityMagnitude = 0.0f;
}

void taicop_init_speed_trap_logic(tAICop *c)
{
    Car *car;

    taicop_clear_pursuit(c);
    park(c);
    c->fSubStateTimer = COP_TRAP_WAIT;
    car = c->Base.pMyCar;
    car->State.MatrixValid = 0;
    set_cop_lights(car, 0);
    car->TheSirenMode = SIREN_MODE_NONE;
}

void taicop_init_road_block_logic(tAICop *c)
{
    Car *car;

    park(c);
    car = c->Base.pMyCar;
    set_cop_lights(car, 1);
    car->State.MatrixValid = 0;
    car->TheSirenMode = SIREN_MODE_NONE;
}

// A car more than 1 cm or 100 BAM off its spot, with CanTeleport's leave
// to go back to it.
static int should_return(const tAICop *c, const bVector2 *spot,
                         uint16_t ang)
{
    Car  *car = c->Base.pMyCar;
    float dx = spot->x - car->State.Position.x;
    float dy = spot->y - car->State.Position.y;
    float da = fabsf((float)(int16_t)(uint16_t)(ang - car->State.Angle));

    if (!(COP_OFF_SPOT < sqrtf(dx * dx + dy * dy) || COP_OFF_HEADING < da))
        return 0;
    return can_teleport(car, spot);
}

// The racers' and players' cars, CarTable up to CopCarPos (read once),
// within 45 m of the cop's car in x and y and 2.5 m in z: each that
// IsValidPursuitTarget and RequestPursuit allow asks for a chase. `see`
// gives the target test's flag through CanPatrollerSeeThisCar, else 1.
static void search(tAICop *c, int see)
{
    int32_t n = pCurrentWorld->CopCarPos;
    int32_t i;

    for (i = 0; i < n; i++) {
        Car  *mine = c->Base.pMyCar;
        Car  *o = pCurrentWorld->CarTable[i];
        float dx = o->State.Position.x - mine->State.Position.x;
        float dy = o->State.Position.y - mine->State.Position.y;
        int32_t b;

        if (!(sqrtf(dx * dx + dy * dy) < COP_SEARCH_XY))
            continue;
        if (!(fabsf(o->State.Position.z - mine->State.Position.z)
              < COP_SEARCH_Z))
            continue;
        b = see ? taicop_can_patroller_see_this_car(c, o) : 1;
        if (taicop_is_valid_pursuit_target(c, o, b)
            && gCopManagerRequestPursuitFn != NULL
            && gCopManagerRequestPursuitFn(pCopManager, &c->Base, o))
            tcop_set_desired_logic_state(&c->Base, LS_HOT_PURSUIT);
    }
}

void taicop_do_speed_trap_logic(tAICop *c)
{
    const tSpeedTrap *t;

    taicop_hold_position(c);
    if (c->fSubStateTimer <= 0.0f
        && !(world_get_distance_to_closest_player_2d(pCurrentWorld,
                 (const bVector2 *)(const void *)
                 &c->Base.pMyCar->State.Position) < COP_FAR_FROM_PLAYERS)) {
        tcop_set_desired_logic_state(&c->Base, LS_LIMBO);
        return;
    }
    t = c->pMySpeedTrap;
    if (should_return(c, &t->v2Position, t->ang))
        taicop_teleport(c, &c->pMySpeedTrap->v2Position,
                        c->pMySpeedTrap->ang);
    search(c, 0);
}

void taicop_do_road_block_logic(tAICop *c)
{
    const tPursuit *p;

    taicop_hold_position(c);
    p = c->Base.pMyPursuit;
    if (p != NULL && p->pRoadBlock != NULL) {
        const tRoadBlock *rb = p->pRoadBlock;
        int32_t           i = c->nMyRoadBlockIndex;

        if (should_return(c, &rb->CopPos[i], rb->CopAng[i]))
            taicop_teleport(c, &rb->CopPos[c->nMyRoadBlockIndex],
                            rb->CopAng[c->nMyRoadBlockIndex]);
    }
    c->New32 = COP_ROADBLOCK_GRACE;
}

void taicop_do_driving_on_patrol_logic(tAICop *c)
{
    c->MyDLOffset.x = 0.0f;
    c->New48.y = 0.0f;
    c->New48.x = 0.0f;
    c->MyDLOffset.y = 0.0f;
    taicop_update_drive_target(
        c, (const bVector2 *)(const void *)&c->Base.pMyCar->State.Position,
        0);
    if (!(world_get_distance_to_closest_player_2d(pCurrentWorld,
              (const bVector2 *)(const void *)&c->Base.pMyCar->State.Position)
          < COP_FAR_FROM_PLAYERS)) {
        tcop_set_desired_logic_state(&c->Base, LS_LIMBO);
        return;
    }
    search(c, 1);
}

// ------------------------------------------------------------- the chase

#define COP_PATROL_RACING    13.410818f  // 415692b6, gp-26860: 30 mph
#define COP_GIVE_UP          450.0f      // 43e10000
#define COP_FAR_BEHIND       -180.0f     // c3340000
#define COP_AHEAD            6.0f        // 40c00000
#define COP_CHASE_MPH        20.0f       // 41a00000
#define COP_SLOW_MPH         5.0f        // 40a00000
#define COP_FOLLOW_RANGE     21.0f       // 41a80000
#define COP_CLOSE_RANGE      20.0f       // 41a00000
#define COP_STOP_RANGE       10.0f       // 41200000, gp-15592
#define COP_FOLLOW_PRIMARY   6.5f        // 40d00000, gp-15544
#define COP_FOLLOW_OTHER     13.0f       // 41500000, gp-15540
#define COP_FOLLOW_SIDE      2.5f        // 40200000
#define COP_LOW_SPEED_X      6.0f        // 40c00000
#define COP_LANE             3.0f        // 40400000
#define COP_AT_OFFSET        0.01f       // 3c23d70a, gp-26892 and gp-26888
#define COP_DRAW_UP          15.0f       // 41700000
#define COP_ITS_WAY          1.0f        // 3f800000
#define COP_FOLLOW_TIME      3.0f        // 40400000
#define COP_OFFSET_TIME      2.0f        // 40000000
#define COP_FLANK_TIME       2.25f       // 40100000
#define COP_BUMP_TIME        1.75f       // 3fe00000
#define COP_BUMP_MID         0.875f      // 3f600000
#define COP_BUMP_HIT         0.4375f     // 3ee00000
#define COP_BACK_OFF_TIME    1.25f       // 3fa00000
#define COP_STOP_TIME        0.5f        // 3f000000
#define COP_PULL_RATE        100.0f      // 42c80000
#define COP_FRONT_ARC        16384       // 90 degrees as a BAM
#define COP_SIDE_ARC         24576       // 135 degrees

// The three tables the sub-logics copy to the stack and index: by
// World::Random(3), the share of the flank side FOLLOW_BACKWARDS sidles to
// (0x002bd5a0); by the chase's level, BUMP's push (0x002bd5f0) and the
// range of PURSUIT_FOLLOW's draw for a flank (0x002bd628).
static const float kBackOffShare[3] = { 1.0f, 0.5f, 0.25f };
static const float kBumpPush[3] = { 7.0f, 10.0f, 15.0f };
static const float kFlankDraw[3] = { 3.0f, 2.0f, 1.0f };

void taicop_return_to_patrol(tAICop *c)
{
    tcop_set_desired_logic_state(&c->Base, LS_DRIVING_ON_PATROL);
    c->Base.LogicSubState =
        COP_PATROL_RACING < c->Base.pMyCar->State.ForwardSpeed
            ? LSS_PATROL_RACING : LSS_PATROL_ONCOMING;
}

float taicop_get_best_flank_side(tAICop *c, Car *ch)
{
    const TrackRoutePoint *rp;
    bVector2               local;
    float                  lat;
    int                    left, right, level;

    // GetRoute's answer goes unused.
    car_get_route(ch, 1);
    rp = car_get_route_point(ch, 1);
    lat = (ch->State.Position.x - rp->Position.x) * rp->Direction.y
        - (ch->State.Position.y - rp->Position.y) * rp->Direction.x;
    left = -rp->LeftWidth - lat <= -COP_LANE;
    right = COP_LANE <= rp->RightWidth - lat;
    carstate_world_to_car2(&ch->State, &local,
                           (const bVector2 *)(const void *)
                           &c->Base.pMyCar->State.Position);
    level = fabsf(local.y) < COP_FOLLOW_SIDE;
    if (local.x < 0.0f) {
        if (left)
            return -1.0f;
    } else if (right) {
        return 1.0f;
    }
    if (level)
        return 0.0f;
    if (right)
        return 1.0f;
    if (left)
        return -1.0f;
    return 0.0f;
}

// The chased car's distance from the cop's in x and y.
static float chase_distance(const tAICop *c, const Car *ch)
{
    const Car *mine = c->Base.pMyCar;
    float      dx = ch->State.Position.x - mine->State.Position.x;
    float      dy = ch->State.Position.y - mine->State.Position.y;

    return sqrtf(dx * dx + dy * dy);
}

// The cop's car against the chased car round the track, CompareDistances
// of their DistanceAroundTracks: above 0 with the cop ahead.
static float track_gap(const tAICop *c, const Car *ch)
{
    return trackpath_compare_distances(
        &TheTrackPathManager,
        c->Base.pMyCar->TheTrackPathCoordinate.DistanceAroundTrack,
        ch->TheTrackPathCoordinate.DistanceAroundTrack);
}

// The chased car's speed, in mph and not made positive.
static float chased_mph(const Car *ch)
{
    return ch->State.ForwardSpeed * COP_MPS_TO_MPH;
}

// Whether the cop is its chase's primary, Cops[0].
static int is_primary(const tAICop *c)
{
    return c->Base.pMyPursuit->Cops[0] == &c->Base;
}

static float follow_distance(const tAICop *c)
{
    return is_primary(c) ? COP_FOLLOW_PRIMARY : COP_FOLLOW_OTHER;
}

// tCopManager's level for a player's car, else 2, the hardest.
static int32_t chase_level(const Car *ch)
{
    return ch->pPlayer != NULL ? pCopManager->nDifficultyLevel : 2;
}

// New48 within 1 cm of MyDLOffset, x and then y.
static int at_offset(const tAICop *c)
{
    return fabsf(c->New48.x - c->MyDLOffset.x) <= COP_AT_OFFSET
        && fabsf(c->New48.y - c->MyDLOffset.y) <= COP_AT_OFFSET;
}

// A car's velocity along its route point's way.
static float along_route(const Car *car, const TrackRoutePoint *rp)
{
    return car->State.Velocity.x * rp->Direction.x
         + car->State.Velocity.y * rp->Direction.y;
}

// How far round from the chased car's heading the cop's car is, seen from
// the chased car: 0 dead ahead, 32768 dead behind. `r` gets the distance.
static uint32_t angle_off(const tAICop *c, const Car *ch, float *r)
{
    const Car *mine = c->Base.pMyCar;
    bVector2   v;
    bPolar     p;
    int32_t    d;

    v.x = mine->State.Position.x - ch->State.Position.x;
    v.y = mine->State.Position.y - ch->State.Position.y;
    bToPolar(&p, &v);
    d = (int16_t)(uint16_t)(p.a - ch->State.Angle);
    *r = p.r;
    return (uint16_t)(d < 0 ? -d : d);
}

// The zone the chase's other cop holds. Retail reads the flank side at
// +72 whatever the cop, which for a 52-byte tPlayerCop is past its end;
// the port reads it from tAICops only, and takes 0 for Be A Cop's.
static int32_t other_zone(const tCop *o)
{
    float side = 0.0f;

    if (o->vptr == TAICOP_VTABLE)
        side = ((const tAICop *)(const void *)o)->fFlankSide;
    return get_zone_from_sub_state(o->LogicSubState, side);
}

typedef void (*BodyOtherFn)(void *self, CollisionBody *other);
typedef void (*BodyImpulseFn)(void *self, bVector3 *j, bVector3 *at);

// 0x0022f8d8. Behind the chased car, 6.5 m for the primary and 13 m for
// the other cop. Further than 21 m, the other cop keeps 2.5 m to the
// side. Closer, a draw under 1 from World::Random(3, 2 or 1) with the
// timer run out, no knock between the two cars, a side to flank on and
// the other cop's zone allowing it asks for FOLLOW_OFFSET on that side;
// and a chased car under 20 mph either way, for LOW_SPEED_CLOSE_FOLLOW.
static void follow(tAICop *c, eLogicSubState old, Car *ch)
{
    float side;

    if (old != c->Base.LogicSubState) {
        c->fSubStateTimer = COP_FOLLOW_TIME;
        c->MyDLOffset.x = follow_distance(c);
        c->MyDLOffset.y = 0.0f;
    }
    if (!(chase_distance(c, ch) < COP_FOLLOW_RANGE)) {
        c->fSubStateTimer = COP_FOLLOW_TIME;
        c->MyDLOffset.x = follow_distance(c);
        c->MyDLOffset.y = is_primary(c) ? 0.0f : COP_FOLLOW_SIDE;
        return;
    }
    if (c->MyDLOffset.x == 0.0f)
        c->MyDLOffset.x = follow_distance(c);
    if (world_random_f(pCurrentWorld, kFlankDraw[chase_level(ch)]) < 1.0f
        && c->fSubStateTimer == 0.0f
        && !did_these_cars_collide(c->Base.pMyCar, ch)
        && (side = taicop_get_best_flank_side(c, ch)) != 0.0f) {
        tPursuit *p = c->Base.pMyPursuit;
        tCop     *o = p->Cops[0] == &c->Base ? p->Cops[1] : p->Cops[0];

        if (o == NULL || o->pMyCar == NULL
            || request_zone_permission(
                   get_zone_from_sub_state(LSS_FOLLOW_OFFSET, side),
                   other_zone(o))) {
            c->fFlankSide = side;
            c->Base.DesiredLogicSubState = LSS_FOLLOW_OFFSET;
        }
    }
    if (fabsf(chased_mph(ch)) < COP_CHASE_MPH)
        c->Base.DesiredLogicSubState = LSS_LOW_SPEED_CLOSE_FOLLOW;
}

// 0x0022f1d8. 6.5 m behind and 3 m out on the flank side. A side no
// longer best goes back to PURSUIT_FOLLOW. With the timer run out and the
// offset reached: a knock starts the timer again; otherwise a cop within
// 135 degrees of the chased car's nose, or 15 m of it, asks for FLANK,
// and one further back for PURSUIT_FOLLOW.
static void follow_offset(tAICop *c, eLogicSubState old, Car *ch)
{
    uint32_t da;
    float    r;

    if (old != c->Base.LogicSubState)
        c->fSubStateTimer = COP_OFFSET_TIME;
    c->MyDLOffset.x = COP_FOLLOW_PRIMARY;
    c->MyDLOffset.y = c->fFlankSide * COP_LANE;
    if (taicop_get_best_flank_side(c, ch) != c->fFlankSide) {
        c->Base.DesiredLogicSubState = LSS_PURSUIT_FOLLOW;
        return;
    }
    if (c->fSubStateTimer != 0.0f || !at_offset(c))
        return;
    if (did_these_cars_collide(c->Base.pMyCar, ch)) {
        c->fSubStateTimer = COP_OFFSET_TIME;
        return;
    }
    da = angle_off(c, ch, &r);
    if (da < COP_SIDE_ARC || !(COP_DRAW_UP < r))
        c->Base.DesiredLogicSubState = LSS_FLANK;
    else
        c->Base.DesiredLogicSubState = LSS_PURSUIT_FOLLOW;
}

// 0x0022fb68. 6 m behind, in line. Above 20 mph the chased car is
// followed again; under 5 mph and within 10 m, the cop asks for STOP.
static void low_speed_close_follow(tAICop *c, eLogicSubState old, Car *ch)
{
    float s;

    if (old != c->Base.LogicSubState) {
        c->MyDLOffset.y = 0.0f;
        c->MyDLOffset.x = COP_LOW_SPEED_X;
    }
    s = fabsf(chased_mph(ch));
    if (COP_CHASE_MPH < s)
        c->Base.DesiredLogicSubState = LSS_PURSUIT_FOLLOW;
    if (s < COP_SLOW_MPH && chase_distance(c, ch) < COP_STOP_RANGE)
        c->Base.DesiredLogicSubState = LSS_STOP;
}

// 0x0022f000, a chased car going against its route. Within 20 m the
// primary keeps 6.5 m back, and with its timer run out sidles a share
// (World::Random(3) of 1, 0.5 or 0.25) toward the best flank side for
// 1.25 s; further off it drops the offsets. The other cop keeps 13 m back
// within 20 m, else 0, and 2.5 m to the side. Under 5 mph and within 10 m
// asks for STOP; a chased car back on its way, above 1 m/s along its
// route, for PURSUIT_FOLLOW.
static void follow_backwards(tAICop *c, eLogicSubState old, Car *ch)
{
    float d = chase_distance(c, ch);

    (void)old;
    if (is_primary(c)) {
        if (d < COP_CLOSE_RANGE) {
            c->MyDLOffset.x = COP_FOLLOW_PRIMARY;
            if (c->fSubStateTimer == 0.0f) {
                float   side = taicop_get_best_flank_side(c, ch);
                int32_t i = world_random_i(pCurrentWorld, 3);

                c->fSubStateTimer = COP_BACK_OFF_TIME;
                c->MyDLOffset.y = kBackOffShare[i] * side;
            }
        } else {
            c->MyDLOffset.x = 0.0f;
            c->MyDLOffset.y = 0.0f;
        }
    } else {
        c->MyDLOffset.x = d < COP_CLOSE_RANGE ? COP_FOLLOW_OTHER : 0.0f;
        c->MyDLOffset.y = COP_FOLLOW_SIDE;
    }
    if (fabsf(chased_mph(ch)) < COP_SLOW_MPH && d < COP_STOP_RANGE)
        c->Base.DesiredLogicSubState = LSS_STOP;
    if (COP_ITS_WAY < along_route(ch, car_get_route_point(ch, 1)))
        c->Base.DesiredLogicSubState = LSS_PURSUIT_FOLLOW;
}

// 0x0022f398. Level with the chased car, 3 m out on the flank side, for
// 2.25 s at a time. A side no longer best goes back to FOLLOW_OFFSET. A
// cop in front of the chased car's flank (within 90 degrees of its nose)
// picks the next move by the chase's behaviour bit 4: a player's car
// without it is got ahead of, and with it bumped, but for a 2-in-15 draw
// that sends the primary ahead; another car is left alone without it,
// and with it bumped but for the same draw. With the timer run out and
// the offset reached, the timer starts again, and a cop fallen back past
// 135 degrees asks for FOLLOW_OFFSET.
static void flank(tAICop *c, eLogicSubState old, Car *ch)
{
    uint32_t da;
    float    r;
    int      front;

    if (old != c->Base.LogicSubState) {
        c->MyDLOffset.x = 0.0f;
        c->fSubStateTimer = COP_FLANK_TIME;
        c->MyDLOffset.y = c->fFlankSide * COP_LANE;
    }
    if (taicop_get_best_flank_side(c, ch) != c->fFlankSide) {
        c->Base.DesiredLogicSubState = LSS_FOLLOW_OFFSET;
        return;
    }
    da = angle_off(c, ch, &r);
    front = da < COP_FRONT_ARC;
    if (front) {
        uint32_t f = c->Base.pMyPursuit->BehaviourFlags;

        if (ch->pPlayer != NULL) {
            if (!(f & 4))
                c->Base.DesiredLogicSubState = LSS_GET_AHEAD;
            else if ((uint32_t)world_random_i(pCurrentWorld, 15) < 2
                     && is_primary(c))
                c->Base.DesiredLogicSubState = LSS_GET_AHEAD;
            else
                c->Base.DesiredLogicSubState = LSS_BUMP;
        } else if (f & 4) {
            c->Base.DesiredLogicSubState =
                (uint32_t)world_random_i(pCurrentWorld, 15) < 2
                    ? LSS_GET_AHEAD : LSS_BUMP;
        }
    }
    if (c->fSubStateTimer != 0.0f || !at_offset(c))
        return;
    c->fSubStateTimer = COP_FLANK_TIME;
    if (!front && !(da < COP_SIDE_ARC))
        c->Base.DesiredLogicSubState = LSS_FOLLOW_OFFSET;
}

// 0x0022f598. Swings in at the chased car's flank over 1.75 s, the side
// offset going from 3 m in to 0 at half time and back out, pulled 100 a
// second. Time up, back to FLANK. With CopStrength not 2 and a knock
// between the two cars, a knock in the last quarter shoves the chased car
// away from the cop, by 7, 10 or 15 for the chase's level -- the car in
// physics mode first, and not at all with it not moving -- and either way
// sends the cop back to FLANK.
static void bump(tAICop *c, eLogicSubState old, Car *ch)
{
    int32_t   lvl = chase_level(ch);
    float     t, s;
    Car      *mine;
    bVector3  j, at;
    float     q, k;

    if (old != c->Base.LogicSubState)
        c->fSubStateTimer = COP_BUMP_TIME;
    t = c->fSubStateTimer;
    c->MyDLOffset.x = 0.0f;
    c->New68 = COP_PULL_RATE;
    c->New64 = COP_PULL_RATE;
    s = fabsf(t - COP_BUMP_MID);
    c->MyDLOffset.y = ((s + s) / COP_BUMP_TIME) * (c->fFlankSide * COP_LANE);
    if (t == 0.0f) {
        c->Base.DesiredLogicSubState = LSS_FLANK;
        return;
    }
    if (TheRaceParameters.CopStrength == 2
        || !did_these_cars_collide(c->Base.pMyCar, ch))
        return;
    if (!(c->fSubStateTimer < COP_BUMP_HIT)) {
        c->Base.DesiredLogicSubState = LSS_FLANK;
        return;
    }

    // The VU0's normalise of the way from the cop to the chased car, all
    // four lanes, then times the push; the point of the impulse is 0.
    mine = c->Base.pMyCar;
    j.x = ch->State.Position.x - mine->State.Position.x;
    j.y = ch->State.Position.y - mine->State.Position.y;
    j.z = ch->State.Position.z - mine->State.Position.z;
    j.pad = ch->State.Position.pad - mine->State.Position.pad;
    q = ee_div(1.0f, sqrtf((j.x * j.x + j.y * j.y) + j.z * j.z));
    k = kBumpPush[lvl];
    j.x = j.x * q * k;
    j.y = j.y * q * k;
    j.z = j.z * q * k;
    j.pad = j.pad * q * k;
    at.x = 0.0f;
    at.y = 0.0f;
    at.z = 0.0f;
    at.pad = 0.0f;
    if (ch->TheMovementMode != eNO_MOVEMENT) {
        CollisionBody *b = &ch->pDynamicCollisionBody->Dynamic.Body;
        const VtEntry *e;

        e = vt_slot(b->_vtable, COLLISIONBODY_VT_SET_TO_PHYSICS_MODE);
        ((BodyOtherFn)e->fn)(vt_this(b, e), NULL);
        e = vt_slot(b->_vtable, COLLISIONBODY_VT_APPLY_IMPULSE);
        ((BodyImpulseFn)e->fn)(vt_this(b, e), &j, &at);
    }
    c->Base.DesiredLogicSubState = LSS_FLANK;
}

// 0x0022fc20. In line ahead of the chased car, on no driving line, pulled
// 100 a second. A cop fallen behind follows again. One still ahead, with
// the chased car above 20 mph by its VelocityMagnitude, going against its
// route and over 20 m off, asks for FOLLOW_BACKWARDS. Either way a chased
// car under 20 mph more than 10 m off asks for LOW_SPEED_CLOSE_FOLLOW.
static void block(tAICop *c, eLogicSubState old, Car *ch)
{
    float d;

    if (old != c->Base.LogicSubState) {
        c->MyDLOffset.x = 0.0f;
        c->nDrivingLineIndex = -1;
    }
    c->MyDLOffset.x = 0.0f;
    c->New68 = COP_PULL_RATE;
    c->New64 = COP_PULL_RATE;
    c->MyDLOffset.y = 0.0f;
    d = chase_distance(c, ch);
    if (track_gap(c, ch) < 0.0f) {
        c->Base.DesiredLogicSubState = LSS_PURSUIT_FOLLOW;
    } else {
        const TrackRoutePoint *rp = car_get_route_point(ch, 1);

        if (COP_CHASE_MPH
                < fabsf(ch->State.VelocityMagnitude * COP_MPS_TO_MPH)
            && along_route(ch, rp) < 0.0f && COP_CLOSE_RANGE < d)
            c->Base.DesiredLogicSubState = LSS_FOLLOW_BACKWARDS;
    }
    if (fabsf(chased_mph(ch)) < COP_CHASE_MPH && COP_STOP_RANGE < d)
        c->Base.DesiredLogicSubState = LSS_LOW_SPEED_CLOSE_FOLLOW;
}

// 0x0022fee0. Once, on the way in: no driving line, and the side offset
// where the cop's car is across its own route point.
static void get_ahead(tAICop *c, eLogicSubState old, Car *ch)
{
    Car                   *mine;
    const TrackRoutePoint *rp;

    (void)ch;
    if (old == c->Base.LogicSubState)
        return;
    c->MyDLOffset.x = 0.0f;
    rp = car_get_route_point(c->Base.pMyCar, 1);
    mine = c->Base.pMyCar;
    c->nDrivingLineIndex = -1;
    c->MyDLOffset.y = (mine->State.Position.x - rp->Position.x)
                          * rp->Direction.y
                    - (mine->State.Position.y - rp->Position.y)
                          * rp->Direction.x;
}

// 0x0022fdb0. Driving line 0 and no offsets, until the cop is back within
// 180 m of the chased car.
static void acquire(tAICop *c, eLogicSubState old, Car *ch)
{
    if (old != c->Base.LogicSubState) {
        c->nDrivingLineIndex = 0;
        c->MyDLOffset.x = 0.0f;
        c->MyDLOffset.y = 0.0f;
    }
    if (COP_FAR_BEHIND < track_gap(c, ch))
        c->Base.DesiredLogicSubState = LSS_PURSUIT_FOLLOW;
}

// 0x0022fe28. On the chased car for half a second; then one moving off,
// above 5 mph or more than 10 m away, is followed close again.
static void stop(tAICop *c, eLogicSubState old, Car *ch)
{
    if (old != c->Base.LogicSubState) {
        c->MyDLOffset.x = 0.0f;
        c->fSubStateTimer = COP_STOP_TIME;
        c->MyDLOffset.y = 0.0f;
    }
    if (c->fSubStateTimer <= 0.0f
        && (COP_SLOW_MPH < fabsf(chased_mph(ch))
            || COP_STOP_RANGE < chase_distance(c, ch)))
        c->Base.DesiredLogicSubState = LSS_LOW_SPEED_CLOSE_FOLLOW;
}

void taicop_do_hot_pursuit_logic(tAICop *c)
{
    eLogicSubState old = c->Base.LogicSubState;
    // Retail reads the chased car with no test of the pursuit.
    Car           *ch = c->Base.pMyPursuit->pChasedCar;
    float          gap;

    if (old != c->Base.DesiredLogicSubState)
        c->Base.LogicSubState = c->Base.DesiredLogicSubState;
    gap = track_gap(c, ch);
    if (COP_GIVE_UP <= fabsf(gap)) {
        taicop_return_to_patrol(c);
        taicop_clear_pursuit(c);
        return;
    }
    if (gap <= COP_FAR_BEHIND)
        c->Base.DesiredLogicSubState = LSS_ACQUIRE;
    else if (COP_AHEAD <= gap && COP_CHASE_MPH <= chased_mph(ch))
        c->Base.DesiredLogicSubState =
            along_route(ch, car_get_route_point(ch, 1)) < 0.0f
                ? LSS_FOLLOW_BACKWARDS : LSS_BLOCK;
    switch (c->Base.LogicSubState) {
    case LSS_PURSUIT_FOLLOW:
        follow(c, old, ch);
        break;
    case LSS_FOLLOW_OFFSET:
        follow_offset(c, old, ch);
        break;
    case LSS_LOW_SPEED_CLOSE_FOLLOW:
        low_speed_close_follow(c, old, ch);
        break;
    case LSS_FOLLOW_BACKWARDS:
        follow_backwards(c, old, ch);
        break;
    case LSS_FLANK:
        flank(c, old, ch);
        break;
    case LSS_BUMP:
        bump(c, old, ch);
        break;
    case LSS_BLOCK:
        block(c, old, ch);
        break;
    case LSS_GET_AHEAD:
        get_ahead(c, old, ch);
        break;
    case LSS_ACQUIRE:
        acquire(c, old, ch);
        break;
    case LSS_STOP:
        stop(c, old, ch);
        break;
    default:
        break;
    }
}

void taicop_do_caught_speeder_logic(tAICop *c)
{
    taicop_hold_position(c);
    if (c->Base.LogicSubState != LSS_CAUGHTSPEEDER_WAITING)
        return;
    if (!(world_get_distance_to_closest_player_2d(pCurrentWorld,
              (const bVector2 *)(const void *)&c->Base.pMyCar->State.Position)
          < COP_FAR_FROM_PLAYERS))
        tcop_set_desired_logic_state(&c->Base, LS_LIMBO);
    else if (c->fSubStateTimer == 0.0f)
        taicop_return_to_patrol(c);
    search(c, 0);
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
        taicop_init_speed_trap_logic(c);
        break;
    case LS_ROAD_BLOCK:
        copmanager_reset_all_damage(pCopManager, car);
        taicop_init_road_block_logic(c);
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
        taicop_do_speed_trap_logic(c);
        break;
    case LS_ROAD_BLOCK:
        taicop_do_road_block_logic(c);
        break;
    case LS_DRIVING_ON_PATROL:
        taicop_do_driving_on_patrol_logic(c);
        break;
    case LS_HOT_PURSUIT:
        taicop_do_hot_pursuit_logic(c);
        break;
    case LS_CAUGHT_SPEEDER:
        taicop_do_caught_speeder_logic(c);
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
    { 0, 0, (VtFn)tplayercop_do_snapshot },     // 32  0x0022d7e8
};

static const VtEntry taicop_vt[] = {
    { 0, 0, NULL },
    { 0, 0, (VtFn)taicop_dtor_entry },          //  8  0x0022dcc0
    { 0, 0, (VtFn)taicop_is_ai_controlled },    // 16  0x00230d60
    { 0, 0, (VtFn)taicop_think_entry },         // 24  0x0022df88
    { 0, 0, (VtFn)taicop_do_snapshot },         // 32  0x0022dd20
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
