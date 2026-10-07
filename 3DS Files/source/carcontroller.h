// carcontroller -- CarController (0x001b6068 .. 0x001b6168) and
// NullController, which Car.obj emits (0x00134a60 .. 0x00134b00).
//
// Twelve bytes: the car, its driver, and the vptr. Car dispatches five of
// its methods through this class -- Think, GetRoute, GetRoutePoint,
// GetAmountOutOfBounds and SetToPhysicsMode -- and IsFacingWrongWay reaches
// it through GetRoutePoint. Of CarController's own fields it reads none.
//
// It reads one field of a subclass: GetTrackedAcceleration, when the car is
// under REAL_CONTROL, takes `Acceleration` at +20 of TrackedController,
// RealController's base. TrackedController's record is below, so car.c
// can reach that field; its methods are in realcontroller.{c,h}.
//
// The concrete controllers are AICarController (task 26, the race AI),
// RealController (the pad) and NullController. The base's eight methods
// and NullController are ported; the others are task 26's, and
// Car::SetControlMode reaches their constructors through seams
// (carmodes.h). `CarController:Tt742=s12`, and the vptr's place is the
// stab's own `$vf742:47,64`.
#ifndef CARCONTROLLER_H
#define CARCONTROLLER_H

#include <stddef.h>
#include <stdint.h>

#include "trackroute.h"   // NullController's three route methods

typedef struct CarController {
    struct Car       *pCar;      // 0
    struct CarDriver *Driver;    // 4
    uint32_t          _vtable;   // 8
} CarController;                 // 12

#define CARCONTROLLER_SLACK ((size_t)(sizeof(void *) - 4))

typedef char carcontroller_layout_check[
    (offsetof(CarController, Driver)  == 4 + CARCONTROLLER_SLACK
     && offsetof(CarController, _vtable) == 8 + 2 * CARCONTROLLER_SLACK
     && sizeof(CarController)
        == ((12 + 2 * CARCONTROLLER_SLACK + sizeof(void *) - 1)
            / sizeof(void *)) * sizeof(void *)) ? 1 : -1];

// TrackedController, RealController's base. From the stab in
// RealController's own unit:
//
//   TrackedController:Tt2611=s36!1,020,810    base CarController (810 there)
//
// pCaffeineObj at 28 is 64 bits wide in the stab, the same editor handle
// TrackPathCoordinate carries, and is kept the same way: a pointer and the
// word after it. The constructor zeroes both and nothing else touches them.
typedef struct TrackedController {
    CarController Base;                   //  0
    struct TrackRoutePoint *RoutePoint;   // 12
    float         TimeBeforeUpdate;       // 16
    float         Acceleration;           // 20
    float         PrevSpeed;              // 24
    void         *pCaffeineObj;           // 28, 64 bits on the disc
    uint32_t      CaffeineObjHigh;        // 32
} TrackedController;                      // 36

// CarController's host size rounds up to a whole pointer, which is one
// slack unit more than its two pointers account for -- hence three before
// RoutePoint and four after it. pCaffeineObj's own alignment adds a fifth,
// and the record rounds up to a pointer again: 36 bytes here, 64 on a
// 64-bit host.
typedef char trackedcontroller_layout_check[
    (offsetof(TrackedController, RoutePoint)
        == 12 + 3 * CARCONTROLLER_SLACK
     && offsetof(TrackedController, TimeBeforeUpdate)
        == 16 + 4 * CARCONTROLLER_SLACK
     && offsetof(TrackedController, Acceleration)
        == 20 + 4 * CARCONTROLLER_SLACK
     && offsetof(TrackedController, PrevSpeed)
        == 24 + 4 * CARCONTROLLER_SLACK
     && offsetof(TrackedController, pCaffeineObj)
        == 28 + 5 * CARCONTROLLER_SLACK
     && sizeof(TrackedController) == 36 + 7 * CARCONTROLLER_SLACK)
    ? 1 : -1];

// _vt$13CarController and the three concrete ones. The slots, by byte
// offset, from the image's tables:
//
//      8  destructor        48  GetCurrentRoute       88  SetToPhysicsMode
//     16  DebugDisplay      56  GetCurrentRoutePoint  96  ForceBoost
//     24  DoSnapshot        64  GetAmountOutOfBounds 104  ReleaseBoost
//     32  Think             72  FindWhereIAm
//     40  SetCurrentRoute   80  JustReset
#define CARCONTROLLER_VTABLE     0x0029a6e0u
#define NULLCONTROLLER_VTABLE    0x00292350u
#define TRACKEDCONTROLLER_VTABLE 0x002a0960u
#define AICARCONTROLLER_VTABLE   0x002981b0u
#define REALCONTROLLER_VTABLE    0x002a0b00u

#define CARCONTROLLER_VT_DTOR                      8
#define CARCONTROLLER_VT_DEBUG_DISPLAY            16
#define CARCONTROLLER_VT_DO_SNAPSHOT              24
#define CARCONTROLLER_VT_THINK                    32
#define CARCONTROLLER_VT_SET_CURRENT_ROUTE        40
#define CARCONTROLLER_VT_GET_CURRENT_ROUTE        48
#define CARCONTROLLER_VT_GET_CURRENT_ROUTE_POINT  56
#define CARCONTROLLER_VT_GET_AMOUNT_OUT_OF_BOUNDS 64
#define CARCONTROLLER_VT_FIND_WHERE_I_AM          72
#define CARCONTROLLER_VT_JUST_RESET               80
#define CARCONTROLLER_VT_SET_TO_PHYSICS_MODE      88
#define CARCONTROLLER_VT_FORCE_BOOST              96
#define CARCONTROLLER_VT_RELEASE_BOOST           104

// Fourteen entries in each table, the empty header included.
#define CARCONTROLLER_VT_ENTRIES 14

typedef void (*CarControllerDtorFn)(void *self, int32_t flags);

// -------------------------------------------------------- the base's methods

// 0x001b6068. pCar and the vptr. **Driver is not written**: every
// subclass constructor sets it, and Car::SetControlMode's inlined
// NullController sets it after building the NullDriver.
CarController *carcontroller_init(CarController *c, struct Car *car);

// 0x001b6080. The vptr back, then `j __builtin_delete` if bit 0. The
// driver is not the base's to destroy; NullController's destructor does.
void carcontroller_destroy(CarController *c, int32_t flags);

// 0x001b6160. `jr ra`.
void carcontroller_debug_display(CarController *c);

// 0x001b60a8. The driver's DoSnapshot, through its vptr at 556, with the
// snapshot passed on. The dispatch is ported; the entry it reaches in
// every table but a harness's is CarDriver::DoSnapshot, which waits on
// ReplaySnapshot, and vt_slot aborts on it.
void carcontroller_do_snapshot(CarController *c, void *snap);

// Retail's 0x001c0100 (the demo's 0x001b60d8). **The argument is not
// read**: the test and the call are on `this->pCar`, through
// carcontroller_physics_or_mellow.
void carcontroller_set_to_physics_mode(CarController *c, struct Car *car);

// Unless the car's movement mode is PHYSICS_MOVEMENT or MELLOW_MOVEMENT,
// SetMovementMode: PHYSICS_MOVEMENT for a player's car, MELLOW_MOVEMENT for
// any other. The demo's went to MELLOW_MOVEMENT either way. Retail's
// CarController::SetToPhysicsMode, which Car::SetToPhysicsMode inlines for
// a car with no controller.
void carcontroller_physics_or_mellow(struct Car *car);

// 0x001b6108 / 0x001b6128. pCar->State.BoostFactor, to `f` or to 1.0,
// when pCar is not NULL. The image tests the CarState's address as well
// (`addiu a0,a0,64 ; bnel a0,zero`), which is never zero.
void carcontroller_force_boost(CarController *c, float f);
void carcontroller_release_boost(CarController *c);

// 0x001b6158. `jr ra ; lw v0,4(a0)`.
struct CarDriver *carcontroller_get_driver(CarController *c);

// ----------------------------------------------------------- NullController

// No fields of its own: type#5776 is 12 bytes, the base and nothing
// else. What a car is given when nothing is to steer it, and what Car's
// constructor builds inline before anything else can.
typedef struct NullController {
    CarController Base;          // 0
} NullController;                // 12

// 0x00134aa0. Its own vptr; the driver through the driver's vptr at 556
// with flags 3, so the driver frees itself; then ~CarController with the
// caller's flags. A NULL driver is skipped.
void nullcontroller_destroy(NullController *c, int32_t flags);

// Each is `jr ra` with a nop or a cleared return register:
//
//   GetAmountOutOfBounds  mtc1 zero,$f0   -> 0.0f
//   GetCurrentRoutePoint  move v0,zero    -> NULL
//   GetCurrentRoute       move v0,zero    -> NULL
void  nullcontroller_think(NullController *c, float dt);          // 0x00134a98
void  nullcontroller_set_current_route(NullController *c,
                                       TrackRoute *r,
                                       TrackRoutePoint *p);        // 0x00134a90
TrackRoute *nullcontroller_get_current_route(NullController *c,
                                             int find);           // 0x00134a88
TrackRoutePoint *nullcontroller_get_current_route_point(
    NullController *c, int find);                                 // 0x00134a80
float nullcontroller_get_amount_out_of_bounds(NullController *c); // 0x00134a70
void  nullcontroller_find_where_i_am(NullController *c);          // 0x00134a68
void  nullcontroller_just_reset(NullController *c);               // 0x00134a60

// Installs _vt$13CarController (0x0029a6e0) and _vt$14NullController
// (0x00292350). The base's seven pure entries (32 .. 80) are NULL, which
// vt_slot aborts on. The game calls it once at boot; a harness calls it
// after vt_reset().
void carcontroller_install_vtables(void);

#endif
