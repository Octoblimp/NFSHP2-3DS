// carcontroller -- CarController, the record only.
//
// Twelve bytes: the car, its driver, and the vptr. Car dispatches five of
// its methods through this class -- Think, GetRoute, GetRoutePoint,
// GetAmountOutOfBounds and SetToPhysicsMode -- and IsFacingWrongWay reaches
// it through GetRoutePoint. Of CarController's own fields it reads none.
//
// It reads one field of a subclass: GetTrackedAcceleration, when the car is
// under REAL_CONTROL, takes `Acceleration` at +20 of TrackedController,
// RealController's base. That prefix is below.
//
// The concrete controllers are AICarController (task 26, the race AI),
// RealController (the pad) and NullController, which lives in Car.obj.
// None is ported yet; this header is what the dispatch needs and nothing
// more. `CarController:Tt742=s12`, and the vptr's place is the stab's own
// `$vf742:47,64`.

#ifndef CARCONTROLLER_H
#define CARCONTROLLER_H

#include <stddef.h>
#include <stdint.h>

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

// TrackedController, RealController's base, as far as Car reads it. From
// the stab in RealController's own unit:
//
//   TrackedController:Tt2611=s36!1,020,810    base CarController (810 there)
//
// The last field, pCaffeineObj at 28, is 64 bits wide in the stab and its
// type does not resolve in that unit, so the record stops before it; task
// 26 finishes it with the controllers.
typedef struct TrackedController {
    CarController Base;                   //  0
    struct TrackRoutePoint *RoutePoint;   // 12
    float         TimeBeforeUpdate;       // 16
    float         Acceleration;           // 20
    float         PrevSpeed;              // 24
    // 28 pCaffeineObj, 8 bytes: task 26.
} TrackedController;

// CarController's host size rounds up to a whole pointer, which is one
// slack unit more than its two pointers account for -- hence three before
// RoutePoint and four after it.
typedef char trackedcontroller_layout_check[
    (offsetof(TrackedController, RoutePoint)
        == 12 + 3 * CARCONTROLLER_SLACK
     && offsetof(TrackedController, TimeBeforeUpdate)
        == 16 + 4 * CARCONTROLLER_SLACK
     && offsetof(TrackedController, Acceleration)
        == 20 + 4 * CARCONTROLLER_SLACK
     && offsetof(TrackedController, PrevSpeed)
        == 24 + 4 * CARCONTROLLER_SLACK) ? 1 : -1];

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
#define AICARCONTROLLER_VTABLE   0x002981b0u
#define REALCONTROLLER_VTABLE    0x002a0b00u

#define CARCONTROLLER_VT_THINK                    32
#define CARCONTROLLER_VT_GET_CURRENT_ROUTE        48
#define CARCONTROLLER_VT_GET_CURRENT_ROUTE_POINT  56
#define CARCONTROLLER_VT_GET_AMOUNT_OUT_OF_BOUNDS 64
#define CARCONTROLLER_VT_SET_TO_PHYSICS_MODE      88

#endif
