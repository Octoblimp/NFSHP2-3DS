// carmodes -- Car's fourth slice: who steers the car and what moves it.
//
//   Car::SetControlMode     0x0012fb50   a five-way table at 0x00292180
//   Car::SetMovementMode    0x0012fd58   a seven-way table at 0x00292200
//   Car::SetToPhysicsMode   0x0012ff68
//   Car::SetFrictionBoost   0x0012fd38
//
// with NullMover (0x00134ba0 .. 0x00134c50, and Move at 0x0012f1f0), the
// mover Car.obj emits for a car nothing moves. The four are declared in
// car.h with the rest of Car; this header is what they build.
//
// **Two of the twelve things the two tables build are not ported.** The
// mover DeliveryMover is task 26's and the controller CopDriver step 12's;
// RealController, BeltMover, CopMover, TrafficCar, AIDriver and
// TrafficDriver are ported (realcontroller.h, beltmover.h, copdriver.h,
// trafficcar.h, aidriver.h, trafficdriver.h), and main.c sets their seams
// at boot. Car allocates
// each itself -- `bMalloc(size, name, 0, 16)` -- and calls its constructor
// with (memory, car), so the port does the same and reaches the
// constructor through a seam below. A NULL seam is an object the port
// cannot build yet, and the arm aborts there, the way vt_slot does on an
// entry nobody installed.
//
// See docs/formats/car-modes.md.

#ifndef CARMODES_H
#define CARMODES_H

#include <stddef.h>
#include <stdint.h>

#include "car.h"
#include "carcontroller.h"
#include "carstate.h"
#include "aidriver.h"          // AIDRIVER_SIZE
#include "beltmover.h"         // BELTMOVER_SIZE
#include "copdriver.h"         // COPMOVER_SIZE
#include "physicscar.h"        // CarMover
#include "realcontroller.h"    // REALCONTROLLER_SIZE
#include "trafficcar.h"        // TRAFFICCAR_SIZE
#include "trafficdriver.h"     // TRAFFICDRIVER_SIZE

// ------------------------------------------------------------- NullMover

// 12 bytes, type#2215: CarMover and the CarState it keeps the wheel
// matrices of. `pState` is the stab's name.
typedef struct NullMover {
    CarMover  Mover;       // 0  Driver 0, vptr 4
    CarState *pState;      // 8
} NullMover;               // 12

#ifndef CARMODES_NO_ASSERT
typedef char nullmover_layout_check[
    (offsetof(NullMover, pState) == 8 + 2 * PHYSICSCAR_SLACK
     && sizeof(NullMover) == 12 + 3 * PHYSICSCAR_SLACK) ? 1 : -1];
#endif

// _vt$9NullMover, 0x002923c0, CarMover's layout: the destructor
// (0x00134bd8), Move (0x0012f1f0) and CarMover's DoSnapshot (0x0012f1e8,
// `jr ra`).
#define NULLMOVER_VTABLE     0x002923c0u
#define NULLMOVER_VT_ENTRIES 4

// 0x00134bb8 / 0x00134ba8. bOMalloc and bFree on NullMoverSlotPool, whose
// slot is cleared on the way out. SetMovementMode inlines the new; the
// destructor calls the delete.
NullMover *nullmover_new(void);
void       nullmover_delete(void *p);

// 0x00134c38. The CarState, then the vptr. The driver is left as the slot
// had it, zero, until SetMovementMode stores the car's. Nothing calls it:
// SetMovementMode's eNO_MOVEMENT arm has it inline.
NullMover *nullmover_init(NullMover *m, CarState *cs);

// 0x00134bd8. Its own vptr; ~CarMover with flags 0, which puts CarMover's
// back; then the pool's delete if bit 0.
void nullmover_destroy(NullMover *m, int32_t flags);

// 0x0012f1f0. CalculateWheelMatrices on the CarState, and dt back.
float nullmover_move(NullMover *m, float dt);

// Installs the table. The game calls it once at boot; a harness calls it
// after vt_reset().
void nullmover_install_vtables(void);

// ----------------------------------------- the classes task 26 will bring

// `__10TrafficCarP3Car` and the rest: (this, car), returning this. Each
// takes the memory Car has just allocated for it and constructs in place.
typedef CarMover      *(*CarMoverCtorFn)(void *mem, Car *car);
typedef CarController *(*CarControllerCtorFn)(void *mem, Car *car);

extern CarMoverCtorFn gTrafficCarCtorFn;       // 0x00163018
extern CarMoverCtorFn gDeliveryMoverCtorFn;    // 0x001f0b80
extern CarMoverCtorFn gCopMoverCtorFn;         // 0x00196f00
extern CarMoverCtorFn gBeltMoverCtorFn;        // 0x001f1ca8

// BeltMover::SetBelt, 0x00204990: AICarController::Think's, each think
// it keeps the belt (BeltMover::Move is the other caller). main.c points
// it at beltmover.c's; a harness that leaves it NULL makes Think abort
// rather than go on.
typedef void (*BeltMoverSetBeltFn)(CarMover *m);
extern BeltMoverSetBeltFn gBeltMoverSetBeltFn;

extern CarControllerCtorFn gRealControllerCtorFn;  // 0x00224740
extern CarControllerCtorFn gAIDriverCtorFn;        // 0x0012e810
extern CarControllerCtorFn gTrafficDriverCtorFn;   // 0x00183f70
extern CarControllerCtorFn gCopDriverCtorFn;       // 0x00197d48

// The image's bMalloc sizes for them, which are each class's mdebug size.
// Each becomes sizeof() when its class is ported: on a 64-bit host the
// records are wider. RealController's already has, and is 84 bytes on the
// console and 160 on a 64-bit host, BeltMover's 72 on the console,
// CopMover's 128 (retail's; the demo's, which carmode_check runs, 112),
// TrafficCar's 36 and AIDriver's and TrafficDriver's 736 (retail's
// SetControlMode asks 736 for each; the demo's 720).
#define TRAFFICCAR_SIZE       ((int)sizeof(TrafficCar))
#define DELIVERYMOVER_SIZE   192
#define COPMOVER_SIZE        ((int)sizeof(CopMover))
#define BELTMOVER_SIZE       ((int)sizeof(BeltMover))
#define REALCONTROLLER_SIZE  ((int)sizeof(RealController))
#define AIDRIVER_SIZE        ((int)sizeof(AIDriver))
#define TRAFFICDRIVER_SIZE   ((int)sizeof(TrafficDriver))
#define COPDRIVER_SIZE        76

// The memory pool every one of Car's bMallocs names.
#define CAR_MEMORY_POOL 16

// ------------------------------------------------------ the null controller

// The NullController and its NullDriver, as Car's constructor (the
// demo's 0x0012f400 .. 0x0012f490, retail's 0x00130c44 .. 0x00130cf4) and
// SetControlMode's eNO_CONTROL arm both build them inline, store for
// store: bMalloc(12, "NullController"), the CarController constructor,
// NullController's vptr; bMalloc(560, "NullDriver"), the CarDriver
// constructor, NullDriver's vptr; the driver into the controller. Car's
// constructor also stores both into the car; the arm leaves that to its
// tail. It is defined in carcontroller.c, with NullController's methods.
NullController *car_new_null_controller(Car *c);

#endif
