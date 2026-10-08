// cop -- tCop, tPlayerCop and tAICop. See cop.h.

#include "cop.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bmem.h"
#include "bslotpool.h"
#include "car.h"
#include "cardriver.h"
#include "carinit.h"
#include "carmodes.h"
#include "cartypeinfo.h"
#include "copdriver.h"
#include "copmgr.h"
#include "drivetarget.h"
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
    (void)self;
    unported("tAICop::Think (0x0022df88)");
}

static void tplayercop_think_entry(void *self)
{
    (void)self;
    unported("tPlayerCop::Think (0x0022d5c8)");
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
