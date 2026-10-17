// realcontroller -- TrackedController (0x00224388 .. 0x00224740) and
// RealController (0x00224740 .. 0x002253fc), the controller a human's car
// is given.
//
// TrackedController keeps the car's place on the route network: the route
// point it is on, refreshed every 0.1 s, and the car's acceleration over
// that time, which is all car.c reads of it (GetTrackedAcceleration).
// RealController adds a RealDriver for the pad, and every frame it gives
// that driver a DriveTarget: where the car will be if it keeps its current
// lateral speed relative to the driving line for its class. The pad does
// not steer by it. What reads the target is the driver's own code, and the
// drive target renderer when the camera is watching this car.
//
// The record is TrackedController's, in carcontroller.h, so car.c can
// reach Acceleration; the methods are here.
//
// The two DoSnapshots (0x00224458, 0x002248c8; retail 0x0023a0f0 and
// 0x0023a560) are the replay's, since TASKS 72c.
//
// See docs/formats/real-controller.md.
#ifndef REALCONTROLLER_H
#define REALCONTROLLER_H

#include <stddef.h>
#include <stdint.h>

#include "airoute.h"
#include "average.h"
#include "carcontroller.h"
#include "drivetarget.h"
#include "quickspline.h"
#include "trackroute.h"

#define REALCONTROLLER_PREVIOUS_POINTS 4

// From the stab in its own unit, where TrackedController is type#2611 (bit
// offsets and widths):
//
//   RealController:Tt2673=s84!1,020,2611;
//     PreviousLateralOffsetFromLine:/014,288,32;
//     LateralVelocityWRTLineAverage:/01700,320,32;
//     NumPreviousRoutePoints:/01,352,32;
//     PreviousRoutePoints:/02674=ar1;0;3;2658,384,256;
//     DrivingLineSpline:/0491,640,32;
typedef struct RealController {
    TrackedController      Base;                            //  0
    float                  PreviousLateralOffsetFromLine;   // 36
    Average               *LateralVelocityWRTLineAverage;   // 40
    int32_t                NumPreviousRoutePoints;          // 44
    NearestRoutePointInfo  PreviousRoutePoints[REALCONTROLLER_PREVIOUS_POINTS];
                                                            // 48
    QuickSpline           *DrivingLineSpline;               // 80
} RealController;                                           // 84

// On a 64-bit host: 64, 72, 80, 88, 152 and 160. Every field after the
// base moves by one slack unit per pointer before it, the base's seven
// included, and each route point is two pointers.
typedef char realcontroller_layout_check[
    (offsetof(RealController, PreviousLateralOffsetFromLine)
        == 36 + 7 * CARCONTROLLER_SLACK
     && offsetof(RealController, LateralVelocityWRTLineAverage)
        == 40 + 8 * CARCONTROLLER_SLACK
     && offsetof(RealController, NumPreviousRoutePoints)
        == 44 + 9 * CARCONTROLLER_SLACK
     && offsetof(RealController, PreviousRoutePoints)
        == 48 + 10 * CARCONTROLLER_SLACK
     && offsetof(RealController, DrivingLineSpline)
        == 80 + 18 * CARCONTROLLER_SLACK
     && sizeof(RealController) == 84 + 19 * CARCONTROLLER_SLACK)
    ? 1 : -1];

// 0x00323ab0, 0. With it set, Think would print each frame's speed less the
// driving line's through Car::PrintAbove, which the retail build and the
// port both keep empty.
extern int32_t DoSpeedDifferencePrinting;

// ------------------------------------------------------- TrackedController

// 0x00224388. CarController's constructor; RoutePoint, Acceleration and
// the editor handle zeroed; the vptr; then FindWhereIAm called directly,
// not through the table. TimeBeforeUpdate and PrevSpeed are left for it to
// write. The driver is not set: RealController's constructor does that.
TrackedController *trackedcontroller_init(TrackedController *c,
                                          struct Car *car);

// 0x002243d8. The vptr, then `j ~CarController`.
void trackedcontroller_destroy(TrackedController *c, int32_t flags);

// 0x002243f0. The countdown, then once it runs out, the acceleration over
// the period that just ended and FindWhereIAm through the table.
void trackedcontroller_think(TrackedController *c, float dt);

// 0x002244e0. The countdown back to 0.1, the point, and the car's speed.
// **The route is not read.**
void trackedcontroller_set_current_route(TrackedController *c, TrackRoute *r,
                                         TrackRoutePoint *p);

// 0x00224500. The manager's slot for the point's own RouteNumber, or NULL
// with no point.
TrackRoute *trackedcontroller_get_current_route(TrackedController *c,
                                                int find);

// 0x00224738 / 0x00224730.
TrackRoutePoint *trackedcontroller_get_current_route_point(
    TrackedController *c, int find);
float trackedcontroller_get_acceleration(TrackedController *c);

// 0x00224668. How far outside the point's road the car is, through the
// table's GetCurrentRoutePoint: negative inside, 0 with no point.
float trackedcontroller_get_amount_out_of_bounds(TrackedController *c);

// 0x00224530. Searches the point's own route for a closer point, drops it
// if the car is more than 5 outside that point's road, and searches every
// racing route if there is then no point. The countdown and PrevSpeed are
// reset whatever happens.
void trackedcontroller_find_where_i_am(TrackedController *c);

// 0x00224660. `jr ra`.
void trackedcontroller_just_reset(TrackedController *c);

// ---------------------------------------------------------- RealController

// 0x00224740. TrackedController's constructor, the offset zeroed, the
// vptr, then three bMallocs on pool 16: a RealDriver for the car, an
// Average over 8, and an EXTRAPOLATED spline over 4 set to no points. Only
// the first two PreviousRoutePoints are zeroed; NumPreviousRoutePoints is 0,
// so nothing reads the other two before they are written.
RealController *realcontroller_init(RealController *c, struct Car *car);

// gRealControllerCtorFn: the constructor on Car's memory.
CarController *realcontroller_construct(void *mem, struct Car *car);

// 0x00224840. The vptr; the driver through its table's slot 8, the Average
// and the spline, each with flags 3 and each skipped if NULL; then
// ~TrackedController with the caller's flags.
void realcontroller_destroy(RealController *c, int32_t flags);

// 0x002249a0. The car's CarClass times two.
int32_t realcontroller_player_drive_line_number(RealController *c);

// 0x002249b8. Walks ahead from `point` until the look-ahead distance is
// used up or the target holds 20, adding the driving line's point at each
// step, shifted by `pos` and moved on by `vel`.
void realcontroller_route_delta_predict(RealController *c, DriveTarget *t,
                                        float vel, float pos, TrackRoute *r,
                                        TrackRoutePoint *p);

// 0x00224c60. RouteDeltaPredict when the car is heading along the point,
// close to the line and not much slower than it; FillWithCurrentAcceleration
// otherwise. No `jal` in the image reaches it, and it is not virtual.
void realcontroller_combo_predict(RealController *c, DriveTarget *t,
                                  float vel, float pos, TrackRoute *r,
                                  TrackRoutePoint *p);

// 0x00224ff8. The car's signed distance from the driving line and the
// running mean of its rate of change, through a spline over up to four
// points: the valid ones kept from earlier calls, then the route ahead.
// Returns 0, with the offset 0, when there are too few points for the
// spline; otherwise 1, after keeping `p` as the newest earlier point.
int32_t realcontroller_calculate_lateral(RealController *c, float *pos,
                                         float *vel, float dt, TrackRoute *r,
                                         TrackRoutePoint *p);

// 0x00224db8. TrackedController's Think, a prediction, the driver's
// SetTarget, and the renderer when the camera follows this car.
void realcontroller_think(RealController *c, float dt);

// The replay's, slot 24 of each table. Retail 0x0023a0f0, a
// "TrackedController" section: the CarController (the driver's), the
// route point by route and index, TimeBeforeUpdate, Acceleration and
// PrevSpeed. Retail 0x0023a560, a "RealController" section: taking or
// restoring sets the spline's control points to 0 first; then the lateral
// offset, its Average, NumPreviousRoutePoints and that many points, and
// the TrackedController.
struct ReplaySnapshot;
void trackedcontroller_do_snapshot(TrackedController *c,
                                   struct ReplaySnapshot *s);
void realcontroller_do_snapshot(RealController *c, struct ReplaySnapshot *s);

// Installs _vt$17TrackedController (0x002a0960) and _vt$14RealController
// (0x002a0b00). The game calls it once at boot; a harness calls it after
// vt_reset().
void realcontroller_install_vtables(void);

#endif
