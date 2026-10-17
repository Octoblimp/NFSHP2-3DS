// trafficdriver -- TrafficDriver, the controller of a traffic car: retail's
// TrafficDriver.obj, 0x0018c380 to 0x0018d070 (the demo's 0x00183f70 on).
//
// SetControlMode builds one for a car under TRAFFIC_CONTROL. It is an
// AICarController (aicarcontroller.h) with a PsychoDriver (psychodriver.h)
// for its driver, and its own Think: a traffic car thinks on one frame in
// twelve, its place among the traffic, and keeps the best of six actions
// -- get unstuck, recover from an accident, react to a hit, avoid a car,
// pull over, or just drive -- each tried only while the action in hand
// scores below its global, and taken when it scores above the best so
// far. A car that avoids another or pulls over leaves its traffic belt
// for the mellow mover. Its speed is its own: the action's, but never over
// 24.59 m/s, nor over a third of a metre per second for each metre to the
// next hairpin sign within 75 m (and at 10 m it takes the sign's route),
// nor over 10 m/s through a bend in its points of more than 50 degrees.
// Which routes it may take, 50 to 59 or 60 to 69, is PickLowNumberedRoutes.
//
// DoSnapshot (0x0018c478) is the replay's, since TASKS 72c.
// Written up in docs/formats/traffic-driver.md; checked against retail by
// tools/trafficdriver_check.py.

#ifndef TRAFFICDRIVER_H
#define TRAFFICDRIVER_H

#include <stddef.h>
#include <stdint.h>

#include "aicarcontroller.h"

struct Car;

// 736 bytes: AICarController's 720 and PickLowNumberedRoutes, rounded up
// to the quadword the record's vPreviousLinePoint aligns it to.
// SetControlMode bMallocs 736 for it. The demo's stab (type#2598, 720
// bytes) also had a CurrentAction of its own at 704, ahead of the bool;
// retail's methods use AICarController's.
typedef struct TrafficDriver {
    AICarController  Base;                   //   0
    int32_t          PickLowNumberedRoutes;  // 720  a bool
    uint8_t          _pad724[12];            // 724  the round-up
} TrafficDriver;                             // 736

#ifndef TRAFFICDRIVER_NO_ASSERT
typedef char trafficdriver_layout_check[
    (sizeof(void *) != 4
     || (offsetof(TrafficDriver, PickLowNumberedRoutes) == 720
         && sizeof(TrafficDriver) == 736)) ? 1 : -1];
#endif

// _vt$13TrafficDriver, retail 0x002b4730: seventeen entries,
// AICarController's but for the destructor (8), DoSnapshot (24), Think
// (32), JustReset (80) and
// GetRouteNumbersToUse (112). ChooseNewAction (120) is AICarController's,
// which nothing calls for a traffic car: Think is TrafficDriver's own.
#define TRAFFICDRIVER_VTABLE 0x002b4730u

// 0x0018c380. AICarController's constructor; the vptr; a PsychoDriver
// bMalloc'd (624 bytes, "PsychoDriver", pool 16), built on the car and
// stored as the driver; ForceCurrentAction AIACTION_NONE; the low routes;
// no current action; and the first think staggered by the car's index,
// -1/70 s for each.
TrafficDriver *trafficdriver_init(TrafficDriver *d, struct Car *car);

// carmodes.h's gTrafficDriverCtorFn.
CarController *trafficdriver_construct(void *mem, struct Car *car);

// 0x0018c418. The vptr; the driver destroyed through its table (flags 3)
// if there is one; then ~AICarController with `flags`.
void trafficdriver_destroy(TrafficDriver *d, int32_t flags);

// 0x0018c4d8, the table's Think. The clock runs down by `dt`. A traffic
// car thinks on the odd frames of WorldLoopCounter's twelve whose half is
// its place among the traffic in the world's car table, anything else when
// its clock is out. Then: sticky decisions, the clock 0.2 s on, the nearby
// cars, the route point; nothing more off the routes. With no action,
// JustDrive at its global's score. Otherwise its status, and the cascade
// against its score (-1 when it is time to change): GetUnstuck (2 s since
// the last), AccidentRecovery, IJustGotHit (with a honk), AvoidCars (the
// choice, a honk, and off the belt), PullOver (off the belt) and JustDrive,
// each tried while the best so far is below its global, and taken, the old
// action destroyed, when it scores above. Then the choice's driving line,
// and ExecuteCurrentAction.
void trafficdriver_think(TrafficDriver *d, float dt);

// 0x0018cae8. Routes 50 to 59 with PickLowNumberedRoutes, else 60 to 69.
void trafficdriver_get_route_numbers_to_use(TrafficDriver *d,
                                            int32_t *first, int32_t *last);

// 0x0018cb10, the table's JustReset. PickLowNumberedRoutes from the route
// the car is on (50 to 59), if any; the action destroyed; the sticky
// decisions cleared; JustDrive at its global's score, executed.
void trafficdriver_just_reset(TrafficDriver *d);

// 0x0018cb98. The action's points calculated; shown, for the camera's car;
// CalculateDesiredSpeed; the driver given the points and the speed, with
// the action's AllowedToUseThrottleAndBrake; the points cleared.
void trafficdriver_execute_current_action(TrafficDriver *d);

// 0x0018cc78. The speed, the time to reach it and the tolerance: the
// action's own, or with its UseDrivingLineSpeed the most and no time; the
// speed never over the most. The most is 24.5865 m/s; 0.32782 x the
// distance to the first hairpin sign (not a backwards one) within 75 m and
// 19 points, with a tolerance of 2, and within 10 m the sign's route is
// taken; or, when the action has three points or more whose halves turn by
// more than acos(0.64), 10 with a tolerance of 2; and never under 10.
void trafficdriver_calculate_desired_speed(TrafficDriver *d, float *speed,
                                           float *time, float *tol);

// 0x0018d030. PickLowNumberedRoutes. Nothing in retail calls it.
void trafficdriver_set_direction(TrafficDriver *d, int32_t low);

// 0x0018c478, slot 24, the replay's, a "TrafficDriver" section:
// PickLowNumberedRoutes, then the AICarController.
struct ReplaySnapshot;
void trafficdriver_do_snapshot(TrafficDriver *d, struct ReplaySnapshot *s);

void trafficdriver_install_vtables(void);

#endif /* TRAFFICDRIVER_H */
