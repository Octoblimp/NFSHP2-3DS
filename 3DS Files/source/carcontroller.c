// carcontroller -- see carcontroller.h.

#include "carcontroller.h"

#include "bmem.h"
#include "car.h"
#include "cardriver.h"
#include "carmodes.h"
#include "vtable.h"

// -------------------------------------------------------- the base's methods

CarController *carcontroller_init(CarController *c, Car *car)
{
    c->pCar = car;
    c->_vtable = CARCONTROLLER_VTABLE;
    return c;
}

void carcontroller_destroy(CarController *c, int32_t flags)
{
    c->_vtable = CARCONTROLLER_VTABLE;
    if (flags & 1)
        bFree(c);
}

void carcontroller_debug_display(CarController *c)
{
    (void)c;
}

typedef void (*CarDriverDoSnapshotFn)(void *self, void *snap);

void carcontroller_do_snapshot(CarController *c, void *snap)
{
    CarDriver *d = c->Driver;
    const VtEntry *e = vt_slot(d->_vtable, CARDRIVER_VT_DO_SNAPSHOT);

    ((CarDriverDoSnapshotFn)e->fn)(vt_this(d, e), snap);
}

void carcontroller_set_to_physics_mode(CarController *c, Car *car)
{
    Car *mine = c->pCar;

    (void)car;
    if (mine->TheMovementMode == PHYSICS_MOVEMENT
        || mine->TheMovementMode == MELLOW_MOVEMENT)
        return;
    car_set_movement_mode(mine, MELLOW_MOVEMENT);
}

void carcontroller_force_boost(CarController *c, float f)
{
    if (c->pCar != NULL)
        c->pCar->State.BoostFactor = f;
}

void carcontroller_release_boost(CarController *c)
{
    if (c->pCar != NULL)
        c->pCar->State.BoostFactor = 1.0f;
}

CarDriver *carcontroller_get_driver(CarController *c)
{
    return c->Driver;
}

// ----------------------------------------------------------- NullController

typedef void (*CarDriverDtorFn)(void *self, int32_t flags);

void nullcontroller_destroy(NullController *c, int32_t flags)
{
    CarDriver *d;

    c->Base._vtable = NULLCONTROLLER_VTABLE;
    d = c->Base.Driver;
    if (d != NULL) {
        const VtEntry *e = vt_slot(d->_vtable, CARDRIVER_VT_DTOR);
        ((CarDriverDtorFn)e->fn)(vt_this(d, e), 3);
    }
    carcontroller_destroy(&c->Base, flags);
}

void nullcontroller_think(NullController *c, float dt)
{
    (void)c; (void)dt;
}

void nullcontroller_set_current_route(NullController *c, TrackRoute *r,
                                      TrackRoutePoint *p)
{
    (void)c; (void)r; (void)p;
}

TrackRoute *nullcontroller_get_current_route(NullController *c)
{
    (void)c;
    return NULL;                        // move v0,zero
}

TrackRoutePoint *nullcontroller_get_current_route_point(NullController *c)
{
    (void)c;
    return NULL;                        // move v0,zero
}

float nullcontroller_get_amount_out_of_bounds(NullController *c)
{
    (void)c;
    return 0.0f;                        // mtc1 zero,$f0
}

void nullcontroller_find_where_i_am(NullController *c) { (void)c; }
void nullcontroller_just_reset(NullController *c)      { (void)c; }

// ------------------------------------------------------------- the tables

#define E(f) { 0, 0, (VtFn)(f) }

// _vt$13CarController, 0x0029a6e0. Slots 32 .. 80 are `__pure_virtual`.
static const VtEntry carcontroller_vt[CARCONTROLLER_VT_ENTRIES] = {
    { 0, 0, NULL },
    E(carcontroller_destroy),                       //   8  0x001b6080
    E(carcontroller_debug_display),                 //  16  0x001b6160
    E(carcontroller_do_snapshot),                   //  24  0x001b60a8
    { 0, 0, NULL },                                 //  32  Think
    { 0, 0, NULL },                                 //  40  SetCurrentRoute
    { 0, 0, NULL },                                 //  48  GetCurrentRoute
    { 0, 0, NULL },                                 //  56  GetCurrentRoutePoint
    { 0, 0, NULL },                                 //  64  GetAmountOutOfBounds
    { 0, 0, NULL },                                 //  72  FindWhereIAm
    { 0, 0, NULL },                                 //  80  JustReset
    E(carcontroller_set_to_physics_mode),           //  88  0x001b60d8
    E(carcontroller_force_boost),                   //  96  0x001b6108
    E(carcontroller_release_boost),                 // 104  0x001b6128
};

// _vt$14NullController, 0x00292350. The base's DebugDisplay, DoSnapshot and
// the last three; its own seven in between.
static const VtEntry nullcontroller_vt[CARCONTROLLER_VT_ENTRIES] = {
    { 0, 0, NULL },
    E(nullcontroller_destroy),                      //   8  0x00134aa0
    E(carcontroller_debug_display),                 //  16  0x001b6160
    E(carcontroller_do_snapshot),                   //  24  0x001b60a8
    E(nullcontroller_think),                        //  32  0x00134a98
    E(nullcontroller_set_current_route),            //  40  0x00134a90
    E(nullcontroller_get_current_route),            //  48  0x00134a88
    E(nullcontroller_get_current_route_point),      //  56  0x00134a80
    E(nullcontroller_get_amount_out_of_bounds),     //  64  0x00134a70
    E(nullcontroller_find_where_i_am),              //  72  0x00134a68
    E(nullcontroller_just_reset),                   //  80  0x00134a60
    E(carcontroller_set_to_physics_mode),           //  88  0x001b60d8
    E(carcontroller_force_boost),                   //  96  0x001b6108
    E(carcontroller_release_boost),                 // 104  0x001b6128
};

#undef E

void carcontroller_install_vtables(void)
{
    vt_install(CARCONTROLLER_VTABLE, carcontroller_vt,
               CARCONTROLLER_VT_ENTRIES);
    vt_install(NULLCONTROLLER_VTABLE, nullcontroller_vt,
               CARCONTROLLER_VT_ENTRIES);
}
