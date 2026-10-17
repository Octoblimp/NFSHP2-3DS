// trafficcar -- TrafficCar, the mover of a traffic car: retail's
// TrafficCar.obj, 0x00167a08 to 0x00168098.
//
// A traffic car is not simulated. The mover keeps its own position on the
// ground plane, heading and speed, and each frame drives them as a
// bicycle: straight on when the wheel is nearly centred, else round the
// circle the steering angle and the wheelbase make, whose centre is level
// with the rear axle (Wheels[3]'s x along the heading). The
// speed follows the driver's pedals through two Tables, the throttle's
// acceleration and the brake's deceleration over the speed, and is held
// between 0 and 55 mph. The CarState is then written outright: the
// position (the height left to PutFlatOnTrack), a velocity of the speed's
// length along the step, the heading and a yaw rate from its change, the
// steering, and the four wheels turning at the speed on the road with
// nothing on them. The third Table, the stopping distance over the speed,
// is CalculateStopDistance's, which nothing in retail calls.
//
// Car::SetMovementMode's TRAFFIC_MOVEMENT arm builds one through
// carmodes.h's gTrafficCarCtorFn; main.c points it here.
//
// See docs/formats/traffic-car.md.

#ifndef TRAFFICCAR_H
#define TRAFFICCAR_H

#include <stddef.h>
#include <stdint.h>

#include "bvector.h"
#include "car.h"
#include "physicscar.h"    // CarMover
#include "table.h"

// 36 bytes on the console, the mdebug record's names. CarMover's eight,
// then the car and where the mover has it.
typedef struct TrafficCar {
    CarMover  Mover;       //  0  Driver 0, vptr 4
    Car      *pCar;        //  8
    bVector2  Position;    // 12  on the ground plane
    float     Angle;       // 20  the heading, radians
    float     Speed;       // 24  metres a second, 0 .. 24.5865
    float     Pitch;       // 28  zeroed, never read
    float     Roll;        // 32  zeroed, never read
} TrafficCar;              // 36

#ifndef TRAFFICCAR_NO_ASSERT
typedef char trafficcar_layout_check[
    (sizeof(void *) != 4
     || (offsetof(TrafficCar, pCar) == 8
         && offsetof(TrafficCar, Position) == 12
         && offsetof(TrafficCar, Angle) == 20
         && offsetof(TrafficCar, Speed) == 24
         && offsetof(TrafficCar, Pitch) == 28
         && offsetof(TrafficCar, Roll) == 32
         && sizeof(TrafficCar) == 36)) ? 1 : -1];
#endif

// _vt$10TrafficCar, 0x002b2190, CarMover's layout: the destructor
// (0x00168088), Move (0x00167af8) and DoSnapshot (0x00167a60).
#define TRAFFICCAR_VTABLE     0x002b2190u
#define TRAFFICCAR_VT_ENTRIES 4

// The three Tables and their data, retail 0x002fad40 .. 0x002fae9c (the
// demo's names, 0x002f2d50 .. 0x002f2eac). Each is over 0 .. 24.5865 m/s.
extern Table TrafficAcceleration;      // 0x002fad50  m/s/s at full throttle
extern Table TrafficBraking;           // 0x002fad78  m/s/s at full brake
extern Table StoppingDistanceTable;    // 0x002fae88  metres

// 0x00167fe0 (the demo's 0x001635f0, _GLOBAL_$I$TrafficAccelerationTable):
// the three Tables over their data, 4, 4 and 61 entries.
void trafficcar_static_init(void);

// 0x00167a08, `__10TrafficCarP3Car`. Every word but the Driver, which
// SetMovementMode's tail stores: the vptr, the car, its x and y, its
// heading from the CarState's BAM, its speed from VelocityMagnitude, and
// Pitch and Roll 0.
TrafficCar *trafficcar_init(TrafficCar *m, Car *car);

// carmodes.h's CarMoverCtorFn: the constructor on memory Car allocated.
CarMover *trafficcar_construct(void *mem, Car *car);

// 0x00168088. Its own vptr, then ~CarMover with this call's flags.
void trafficcar_destroy(TrafficCar *m, int32_t flags);

// 0x00167af8. One frame; see docs/formats/traffic-car.md. Returns dt.
float trafficcar_move(TrafficCar *m, float dt);

// DoSnapshot, 0x00167a60, section "TrafficCar" (TASKS 72d): Position's
// eight bytes as they are, Angle, Speed, Pitch and Roll, then CarMover's,
// which does nothing.
struct ReplaySnapshot;
void trafficcar_do_snapshot(TrafficCar *m, struct ReplaySnapshot *s);

// 0x00167fb8. The stopping distance at `speed` from StoppingDistanceTable;
// the first float is not read. Retail has no call to it (no jal, no
// pointer): it is ported for the Table it reads.
float trafficcar_calculate_stop_distance(TrafficCar *m, float unused,
                                         float speed);

// Installs the table. The game calls it once at boot; a harness calls it
// after vt_reset().
void trafficcar_install_vtables(void);

// Points carmodes.h's gTrafficCarCtorFn at this file.
void trafficcar_install_seams(void);

#endif
