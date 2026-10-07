// realcontroller -- see realcontroller.h and docs/formats/real-controller.md.
#include "realcontroller.h"

#include <math.h>
#include <string.h>

#include "bmem.h"
#include "bvector.h"
#include "car.h"
#include "cardriver.h"
#include "carmodes.h"
#include "drivetargetrenderer.h"
#include "eefpu.h"
#include "player.h"
#include "realdriver.h"
#include "vtable.h"

int32_t DoSpeedDifferencePrinting;          // 0x00323ab0

// gp-27292, -27288 and -27284: three copies of 0.1f, one per function.
#define TRACKED_UPDATE_PERIOD 0.1f

// FindWhereIAm's search: 24 around the old point, Posted points only,
// measured along the track.
#define TRACKED_SEARCH_RADIUS 24.0f
#define TRACKED_SEARCH_FLAGS  (TRFIND_POSTED_ONLY | TRFIND_BY_TRACK_DISTANCE)

typedef void             (*ControllerFn)(void *self);
typedef TrackRoute      *(*GetRouteFn)(void *self);
typedef TrackRoutePoint *(*GetRoutePointFn)(void *self);
typedef void             (*DriverDtorFn)(void *self, int32_t flags);
typedef void             (*DriverSetTargetFn)(void *self,
                                              const DriveTarget *t);

// `max.s fd,fs,ft` and `min.s fd,fs,ft`, as the image's operands are
// ordered: each returns fs unless ft is strictly past it.
static float max_s(float fs, float ft) { return (fs < ft) ? ft : fs; }
static float min_s(float fs, float ft) { return (ft < fs) ? ft : fs; }

// How far `pos` is outside the point's road: the distance across Direction
// (positive to the right), less the width on that side. Negative inside.
// FindWhereIAm and GetAmountOutOfBounds each have this inline, the same
// way.
static float out_of_bounds(const TrackRoutePoint *p, const bVector3 *pos)
{
    float f = (pos->x - p->Position.x) * p->Direction.y
              - (pos->y - p->Position.y) * p->Direction.x;

    if (0.0f < f)
        return f - p->RightWidth;
    return -(f + p->LeftWidth);
}

// The manager's slot for a point's own route number. A byte, so up to 255;
// the table has 100 and the image reads past it for more, as this does.
static TrackRoute *route_of(const TrackRoutePoint *p)
{
    return TheTrackRouteManager.pTrackRoutes[p->RouteNumber];
}

// Driving line `line` at `p`, read at the image's own byte offsets: the
// offset is `lh` at 48 + 2 * line and the speed `lbu` at 90 + line. A line
// past the table reads what the image reads, the next field, rather than
// past a C array. TrackRoutePoint is 112 bytes on every build.
static float line_offset(const TrackRoutePoint *p, int32_t line)
{
    int16_t v;

    memcpy(&v, (const uint8_t *)p + 48 + 2 * line, sizeof v);
    // `sll 8`, `cvt.s.w`, times 2^-16: Q8 to units, exactly.
    return (float)((int32_t)v * 256) * (1.0f / 65536.0f);
}

static uint8_t line_speed(const TrackRoutePoint *p, int32_t line)
{
    return ((const uint8_t *)p)[90 + line];
}

// ------------------------------------------------------- TrackedController

TrackedController *trackedcontroller_init(TrackedController *c, Car *car)
{
    carcontroller_init(&c->Base, car);
    c->RoutePoint = NULL;
    c->Acceleration = 0.0f;
    c->pCaffeineObj = NULL;
    c->CaffeineObjHigh = 0;
    c->Base._vtable = TRACKEDCONTROLLER_VTABLE;
    // `jal`, not the table: a subclass's FindWhereIAm is not reached here.
    trackedcontroller_find_where_i_am(c);
    return c;
}

void trackedcontroller_destroy(TrackedController *c, int32_t flags)
{
    c->Base._vtable = TRACKEDCONTROLLER_VTABLE;
    carcontroller_destroy(&c->Base, flags);
}

void trackedcontroller_think(TrackedController *c, float dt)
{
    float          left = c->TimeBeforeUpdate - dt;
    const VtEntry *e;

    c->TimeBeforeUpdate = left;
    if (0.0f < left)
        return;
    // The period that just ended is 0.1 plus the overshoot. PrevSpeed is
    // FindWhereIAm's to reset.
    c->Acceleration = (c->Base.pCar->State.VelocityMagnitude - c->PrevSpeed)
                      / (TRACKED_UPDATE_PERIOD - left);
    e = vt_slot(c->Base._vtable, CARCONTROLLER_VT_FIND_WHERE_I_AM);
    ((ControllerFn)e->fn)(vt_this(c, e));
}

void trackedcontroller_set_current_route(TrackedController *c, TrackRoute *r,
                                         TrackRoutePoint *p)
{
    (void)r;
    c->TimeBeforeUpdate = TRACKED_UPDATE_PERIOD;
    c->RoutePoint = p;
    c->PrevSpeed = c->Base.pCar->State.VelocityMagnitude;
}

TrackRoute *trackedcontroller_get_current_route(TrackedController *c,
                                                int find)
{
    (void)find;
    if (c->RoutePoint == NULL)
        return NULL;
    return route_of(c->RoutePoint);
}

TrackRoutePoint *trackedcontroller_get_current_route_point(
    TrackedController *c, int find)
{
    (void)find;
    return c->RoutePoint;
}

float trackedcontroller_get_acceleration(TrackedController *c)
{
    return c->Acceleration;
}

float trackedcontroller_get_amount_out_of_bounds(TrackedController *c)
{
    const VtEntry   *e = vt_slot(c->Base._vtable,
                                 CARCONTROLLER_VT_GET_CURRENT_ROUTE_POINT);
    TrackRoutePoint *p = ((GetRoutePointFn)e->fn)(vt_this(c, e));

    if (p == NULL)
        return 0.0f;
    return out_of_bounds(p, &c->Base.pCar->State.Position);
}

void trackedcontroller_find_where_i_am(TrackedController *c)
{
    Car            *car = c->Base.pCar;
    const bVector2 *pos = (const bVector2 *)&car->State.Position;

    if (c->RoutePoint != NULL) {
        TrackRoutePoint *p = troute_find_closest_point(
            route_of(c->RoutePoint), pos, TRACKED_SEARCH_RADIUS,
            TRACKED_SEARCH_FLAGS, car->TheTrackPathCoordinate.DistanceAroundTrack);

        c->RoutePoint = p;
        if (p != NULL && 5.0f < out_of_bounds(p, &car->State.Position))
            c->RoutePoint = NULL;
    }

    // No point to start from, none near it, or the car off its road: every
    // racing route. `info` is not initialised, and is only read on success.
    if (c->RoutePoint == NULL) {
        NearestRoutePointInfo info;

        car = c->Base.pCar;
        if (ai_get_nearest_route_point(&info, pos, ALL_RACING_ROUTES,
                                       TRACKED_SEARCH_FLAGS,
                                       car->TheTrackPathCoordinate
                                           .DistanceAroundTrack))
            c->RoutePoint = info.Point;
    }

    c->TimeBeforeUpdate = TRACKED_UPDATE_PERIOD;
    c->PrevSpeed = c->Base.pCar->State.VelocityMagnitude;
}

void trackedcontroller_just_reset(TrackedController *c)
{
    (void)c;
}

// ---------------------------------------------------------- RealController

RealController *realcontroller_init(RealController *c, Car *car)
{
    RealDriver  *d;
    Average     *a;
    QuickSpline *s;
    int          i;

    trackedcontroller_init(&c->Base, car);
    c->PreviousLateralOffsetFromLine = 0.0f;
    c->Base.Base._vtable = REALCONTROLLER_VTABLE;

    d = (RealDriver *)bMalloc((int)sizeof(RealDriver), "RealDriver", 0,
                              CAR_MEMORY_POOL);
    realdriver_init(d, car);
    c->Base.Base.Driver = &d->Base;

    a = (Average *)bMalloc((int)sizeof(Average), "AverageInRealController",
                           0, CAR_MEMORY_POOL);
    c->LateralVelocityWRTLineAverage = average_init(a, 8);

    s = (QuickSpline *)bMalloc((int)sizeof(QuickSpline),
                               "QuickSplineInRealController", 0,
                               CAR_MEMORY_POOL);
    s = quickspline_init(s, QUICKSPLINE_EXTRAPOLATED, QUICKSPLINE_OVERHAUSER,
                         4);
    c->DrivingLineSpline = s;
    quickspline_set_num_control_points(s, 0);

    c->NumPreviousRoutePoints = 0;
    // The loop counts 1 down to 0: two of the four.
    for (i = 0; i < 2; i++) {
        c->PreviousRoutePoints[i].Route = NULL;
        c->PreviousRoutePoints[i].Point = NULL;
    }
    return c;
}

CarController *realcontroller_construct(void *mem, Car *car)
{
    return &realcontroller_init((RealController *)mem, car)->Base.Base;
}

void realcontroller_destroy(RealController *c, int32_t flags)
{
    CarDriver *d;

    c->Base.Base._vtable = REALCONTROLLER_VTABLE;
    d = c->Base.Base.Driver;
    if (d != NULL) {
        const VtEntry *e = vt_slot(d->_vtable, CARDRIVER_VT_DTOR);
        ((DriverDtorFn)e->fn)(vt_this(d, e), 3);
    }
    // Freed and not cleared: nothing reads them again.
    if (c->LateralVelocityWRTLineAverage != NULL)
        average_destroy(c->LateralVelocityWRTLineAverage, 3);
    if (c->DrivingLineSpline != NULL)
        quickspline_destroy(c->DrivingLineSpline, 3);
    trackedcontroller_destroy(&c->Base, flags);
}

int32_t realcontroller_player_drive_line_number(RealController *c)
{
    // `sll v0,v0,1`.
    return (int32_t)((uint32_t)c->Base.Base.pCar->pCarTypeInfo->CarClass
                     << 1);
}

void realcontroller_route_delta_predict(RealController *c, DriveTarget *t,
                                        float vel, float pos, TrackRoute *r,
                                        TrackRoutePoint *p)
{
    Car                  *car = c->Base.Base.pCar;
    float                 travelled = 0.0f;
    float                 look = ai_calculate_look_ahead_distance(car);
    // The line is converted as an unsigned word, and back with cvt.w.s.
    float                 lineF = (float)(uint32_t)
        realcontroller_player_drive_line_number(c);
    NearestRoutePointInfo info, prev;
    bVector3              at, lo, hi;
    float                 speed, half;

    // `at` starts as the whole of the car's position, pad included, and
    // AddPointToTarget copies all sixteen bytes. On the console each
    // point's pad is garbage: GetPosition(bVector3) stores four VU0 lanes,
    // and the fourth comes from two stack words (12(sp), 44(sp)) it never
    // sets. trpoint_get_position3 leaves the pad alone, so here it is the
    // position's (drivetarget.h, STACK-W).
    at = car->State.Position;
    speed = car->State.VelocityMagnitude;
    car_get_car_space_bounding_box(car, &lo, &hi);
    half = (hi.y - lo.y) * 0.5f;
    info.Route = r;
    info.Point = p;

    if (!(0.0f < look))
        return;
    while (t->NumPoints < 20) {
        TrackRoutePoint *np;
        float            d, step, lat;
        int32_t          line;
        uint32_t         bytes;

        prev = info;
        ai_get_next_route_point_ahead(&info);
        if (info.Route == NULL || info.Point == NULL) {
            // Off the end: start again with a straight line.
            drivetarget_clear(t, NULL, 0.0f);
            ai_straight_line_predict(c->Base.Base.pCar, t);
            return;
        }
        np = info.Point;

        // The time to the new point at the car's speed, along the old
        // point's direction; the offset moves on by the lateral speed, and
        // the lateral speed falls by one per second towards zero.
        d = (np->Position.x - prev.Point->Position.x) * prev.Point->Direction.x
            + (np->Position.y - prev.Point->Position.y)
              * prev.Point->Direction.y;
        step = d / speed;
        pos = pos + vel * step;
        if (vel < 0.0f)
            vel = vel + step;
        else
            vel = vel - step;

        // The line plus the offset, kept half the car's width inside each
        // side of the road.
        line = ee_trunc_w(lineF);
        lat = line_offset(np, line) + pos;
        lat = max_s(lat, half - np->LeftWidth);
        lat = min_s(np->RightWidth - half, lat);
        trpoint_get_position3(np, &at, 0.0f, lat);

        // The point's index the compiler's way, bits 4 to 19 of the byte
        // distance times the inverse of 7, and the route number's low byte.
        bytes = (uint32_t)((uintptr_t)np
                           - (uintptr_t)info.Route->TrackRoutePointTable);
        drivetarget_add_point3(
            t, &at, (int8_t)info.Route->RouteNumber,
            (int16_t)((int32_t)((bytes * 0xb6db6db7u) << 12) >> 16),
            (int8_t)line, 0, NULL);

        travelled = travelled + prev.Point->Length;
        if (!(travelled < look))
            return;
    }
}

void realcontroller_combo_predict(RealController *c, DriveTarget *t,
                                  float vel, float pos, TrackRoute *r,
                                  TrackRoutePoint *p)
{
    int32_t  line = realcontroller_player_drive_line_number(c);
    Car     *car = c->Base.Base.pCar;
    // `sll 16`, `cvt.s.w`, times 2^-16: the byte, exactly.
    float    speed = (float)line_speed(p, line);
    bVector2 dir;

    bNormalize2(&dir, (const bVector2 *)&car->State.Velocity);
    if (0.99f < dir.x * p->Direction.x + dir.y * p->Direction.y
        && fabsf(vel) < 6.0f
        && fabsf(pos) < 12.0f
        && speed * 0.7f < c->Base.Base.pCar->State.VelocityMagnitude) {
        realcontroller_route_delta_predict(c, t, vel, pos, r, p);
        return;
    }
    drivetarget_fill_with_current_acceleration(t, c->Base.Base.pCar);
}

int32_t realcontroller_calculate_lateral(RealController *c, float *pos,
                                         float *vel, float dt, TrackRoute *r,
                                         TrackRoutePoint *p)
{
    NearestRoutePointInfo *prev = c->PreviousRoutePoints;
    int32_t                line = realcontroller_player_drive_line_number(c);
    bVector3               pts[REALCONTROLLER_PREVIOUS_POINTS];
    NearestRoutePointInfo  info;
    QuickSpline           *s;
    Car                   *car;
    bVector4               at;
    float                  param, dx, dy;
    int32_t                n = 0, i, num;

    // The earlier points that are still good, oldest first.
    for (i = 0; i < c->NumPreviousRoutePoints; i++) {
        if (nrpi_is_valid(&prev[i])) {
            trpoint_get_position3(prev[i].Point, &pts[n], 0.0f,
                                  line_offset(prev[i].Point, line));
            n++;
        }
    }

    // Then on from the newest, or from `p` if it is gone. With none kept
    // the image tests the eight bytes before the array, the Average's
    // pointer and the count of 0, which is never valid.
    num = c->NumPreviousRoutePoints;
    if (num > 0 && nrpi_is_valid(&prev[num - 1])) {
        info = prev[num - 1];
        ai_get_next_route_point_ahead(&info);
    } else {
        info.Route = r;
        info.Point = p;
    }
    while (n < REALCONTROLLER_PREVIOUS_POINTS && nrpi_is_valid(&info)) {
        trpoint_get_position3(info.Point, &pts[n], 0.0f,
                              line_offset(info.Point, line));
        n++;
        ai_get_next_route_point_ahead(&info);
    }

    s = c->DrivingLineSpline;
    if (n < s->MinControlPoints) {
        *pos = 0.0f;
        *vel = c->LateralVelocityWRTLineAverage->fAverage;
        return 0;
    }

    quickspline_set_num_control_points(s, n);
    for (i = 0; i < n; i++) {
        bVector4 *cp = &c->DrivingLineSpline->pControlPoints[i];

        cp->x = pts[i].x;
        cp->y = pts[i].y;
        cp->z = pts[i].z;
        cp->w = 0.0f;
        c->DrivingLineSpline->ControlPointsDirty = 1;
    }

    // The nearest point on the line, and the car's distance from it in the
    // plane, signed by the side the line is on: negative when it lies
    // against the body matrix's second row.
    car = c->Base.Base.pCar;
    param = quickspline_find_closest_param(c->DrivingLineSpline,
                                           &car->State.Position, 0.0f, 0.1f);
    quickspline_get_point(c->DrivingLineSpline, &at, param, 0);
    car = c->Base.Base.pCar;
    dx = at.x - car->State.Position.x;
    dy = at.y - car->State.Position.y;
    *pos = sqrtf(dx * dx + dy * dy);
    if (car->State.BodyMatrix.v1.x * dx + car->State.BodyMatrix.v1.y * dy
        < 0.0f)
        *pos = -*pos;

    average_record(c->LateralVelocityWRTLineAverage,
                   (*pos - c->PreviousLateralOffsetFromLine) / dt);
    *vel = c->LateralVelocityWRTLineAverage->fAverage;
    c->PreviousLateralOffsetFromLine = *pos;

    // Keep `p` as the newest, unless it already is. With some kept, a NULL
    // route is not kept either; with none, it is.
    num = c->NumPreviousRoutePoints;
    if (num != 0) {
        if (prev[num - 1].Point == p)
            return 1;
        if (r == NULL)
            return 1;
    }
    if (num == REALCONTROLLER_PREVIOUS_POINTS) {
        for (i = 0; i < c->NumPreviousRoutePoints - 1; i++)
            prev[i] = prev[i + 1];
        num = c->NumPreviousRoutePoints - 1;
    } else {
        c->NumPreviousRoutePoints = num + 1;
    }
    prev[num].Point = p;
    prev[num].Route = r;
    return 1;
}

void realcontroller_think(RealController *c, float dt)
{
    CarController        *base = &c->Base.Base;
    DriveTarget           t;
    NearestRoutePointInfo info;
    TrackRoute           *route;
    TrackRoutePoint      *point;
    CarDriver            *d;
    const VtEntry        *e;
    int                   predicted = 0;

    drivetarget_init(&t);
    trackedcontroller_think(&c->Base, dt);
    e = vt_slot(base->_vtable, CARCONTROLLER_VT_GET_CURRENT_ROUTE);
    info.Route = ((GetRouteFn)e->fn)(vt_this(c, e));
    e = vt_slot(base->_vtable, CARCONTROLLER_VT_GET_CURRENT_ROUTE_POINT);
    point = ((GetRoutePointFn)e->fn)(vt_this(c, e));
    info.Point = point;
    route = info.Route;
    dt = max_s(dt, 0.001f);

    // Going the wrong way, the route is not looked at.
    if (base->pCar->pPlayer->bWrongWay == 0) {
        float pos, vel;

        // A step ahead whose result nothing reads.
        ai_get_next_route_point_ahead(&info);
        vel = 0.0f;
        pos = 0.0f;
        if (route != NULL && point != NULL
            && realcontroller_calculate_lateral(c, &pos, &vel, dt, route,
                                                point)) {
            if (10.0f <= base->pCar->State.ForwardSpeed) {
                realcontroller_route_delta_predict(c, &t, vel, pos, route,
                                                   point);
                drivetarget_blend_with_current_acceleration(&t, base->pCar);
            } else {
                ai_straight_line_predict(base->pCar, &t);
            }
            predicted = 1;
        }
    }
    if (!predicted) {
        if (10.0f <= base->pCar->State.ForwardSpeed)
            drivetarget_fill_with_current_acceleration(&t, base->pCar);
        else
            ai_straight_line_predict(base->pCar, &t);
    }

    d = base->Driver;
    e = vt_slot(d->_vtable, CARDRIVER_VT_SET_TARGET);
    ((DriverSetTargetFn)e->fn)(vt_this(d, e), &t);

    if ((int32_t)base->pCar->DriverNumber == CameraFollowThisCarInstead)
        drivetargetrenderer_set_target_to_render(&TheDriveTargetRenderer, &t);

    // With DoSpeedDifferencePrinting set and a point, the image passes
    // VelocityMagnitude less the line's speed at the point to
    // Car::PrintAbove as a double. PrintAbove is empty in the retail build
    // and in car.c, so there is nothing to port but the flag.

    drivetarget_destroy(&t);
}

// ------------------------------------------------------------- the tables

#define E(f) { 0, 0, (VtFn)(f) }

// _vt$17TrackedController, 0x002a0960. DebugDisplay and the last three are
// CarController's; DoSnapshot waits on ReplaySnapshot.
static const VtEntry trackedcontroller_vt[CARCONTROLLER_VT_ENTRIES] = {
    { 0, 0, NULL },
    E(trackedcontroller_destroy),                   //   8  0x002243d8
    E(carcontroller_debug_display),                 //  16  0x001b6160
    { 0, 0, NULL },                                 //  24  0x00224458
    E(trackedcontroller_think),                     //  32  0x002243f0
    E(trackedcontroller_set_current_route),         //  40  0x002244e0
    E(trackedcontroller_get_current_route),         //  48  0x00224500
    E(trackedcontroller_get_current_route_point),   //  56  0x00224738
    E(trackedcontroller_get_amount_out_of_bounds),  //  64  0x00224668
    E(trackedcontroller_find_where_i_am),           //  72  0x00224530
    E(trackedcontroller_just_reset),                //  80  0x00224660
    E(carcontroller_set_to_physics_mode),           //  88  0x001b60d8
    E(carcontroller_force_boost),                   //  96  0x001b6108
    E(carcontroller_release_boost),                 // 104  0x001b6128
};

// _vt$14RealController, 0x002a0b00. Its own destructor, DoSnapshot and
// Think; the rest as TrackedController's.
static const VtEntry realcontroller_vt[CARCONTROLLER_VT_ENTRIES] = {
    { 0, 0, NULL },
    E(realcontroller_destroy),                      //   8  0x00224840
    E(carcontroller_debug_display),                 //  16  0x001b6160
    { 0, 0, NULL },                                 //  24  0x002248c8
    E(realcontroller_think),                        //  32  0x00224db8
    E(trackedcontroller_set_current_route),         //  40  0x002244e0
    E(trackedcontroller_get_current_route),         //  48  0x00224500
    E(trackedcontroller_get_current_route_point),   //  56  0x00224738
    E(trackedcontroller_get_amount_out_of_bounds),  //  64  0x00224668
    E(trackedcontroller_find_where_i_am),           //  72  0x00224530
    E(trackedcontroller_just_reset),                //  80  0x00224660
    E(carcontroller_set_to_physics_mode),           //  88  0x001b60d8
    E(carcontroller_force_boost),                   //  96  0x001b6108
    E(carcontroller_release_boost),                 // 104  0x001b6128
};

#undef E

void realcontroller_install_vtables(void)
{
    vt_install(TRACKEDCONTROLLER_VTABLE, trackedcontroller_vt,
               CARCONTROLLER_VT_ENTRIES);
    vt_install(REALCONTROLLER_VTABLE, realcontroller_vt,
               CARCONTROLLER_VT_ENTRIES);
}
