// Transcript harness for DriveTarget.
// Cross-checked by tools/drivetarget_check.py, which models the same
// behaviour from the disassembly at 0x002086f8..0x0020a840 (plus the copy
// constructor at 0x001da210) without reading this file.
//
// Every fixture float is spelled as its own decimal literal rather than
// built by arithmetic, because the model rounds each literal once and the C
// would round a sum twice. Fixtures are not the thing under test, so they
// are written so that both sides cannot disagree about them.
//
// WorldTimer lives in engine.c in the handheld build. This harness defines
// its own rather than dragging Engine, Table, CarTypeInfo and Wheel in
// behind it; DriveTarget reads the tick and never writes it.

#include <math.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "carstate.h"
#include "drivetarget.h"
#include "trackroute.h"

int32_t WorldTimer = 0;
int32_t WorldLoopCounter;   // realtime.c's too; ReplaySnapshot_Init reads it

// ----------------------------------------------------------------- output

static void pf(const char *tag, float x)
{
    printf("%s %.9g\n", tag, (double)x);
}

static void pint(const char *tag, int x)
{
    printf("%s %d\n", tag, x);
}

// The scalars, then `n` slots. The slot count is given per call site rather
// than taken from NumPoints, because the interesting part of ShiftRight and
// ShiftLeft is what they leave in the slots past the end.
static void pdt(const char *tag, const DriveTarget *t, int n)
{
    int i;

    printf("%s n %d len %.9g pick %d calct %d blendt %d ttype %d last %d\n",
           tag, (int)t->NumPoints, (double)t->Length,
           (int)t->WhichPointIPicked, (int)t->WhichPointIPickedCalculationTime,
           (int)t->WhichPointIPickedTime, (int)t->TType,
           (int)t->LastPointToScore);
    for (i = 0; i < n; i++)
        printf("%s [%02d] %.9g %.9g %.9g %.9g  s %.9g r %d p %d d %d\n",
               tag, i, (double)t->Points[i].x, (double)t->Points[i].y,
               (double)t->Points[i].z, (double)t->Points[i].pad,
               (double)t->CalculatedSpeed[i], (int)t->Route[i],
               (int)t->RoutePointNumber[i], (int)t->DrivingLine[i]);
}

// The three padding runs, as bytes. Only the assignment/copy pair can tell
// them apart, which is the whole reason they are printed anywhere.
static void ppad(const char *tag, const DriveTarget *t)
{
    const unsigned char *b = (const unsigned char *)t;
    int i;

    printf("%s pad0", tag);
    for (i = 1; i < 16; i++) printf(" %02x", b[i]);
    printf("\n%s pad1 %02x %02x %02x\n", tag, b[501], b[502], b[503]);
    printf("%s pad2", tag);
    for (i = 517; i < 528; i++) printf(" %02x", b[i]);
    printf("\n");
}

static void pv3(const char *tag, const bVector3 *v)
{
    printf("%s %.9g %.9g %.9g %.9g\n", tag, (double)v->x, (double)v->y,
           (double)v->z, (double)v->pad);
}

// ---------------------------------------------------------------- fixtures

// Zeroed as Clear leaves it, LastPointToScore -1 (score every corner)
// included.
static void dt_reset(DriveTarget *t)
{
    memset(t, 0, sizeof(*t));
    t->LastPointToScore = -1;
}

static void dt_point(DriveTarget *t, int i, float x, float y, float z,
                     float speed, int route, int rpn, int dl)
{
    t->Points[i].x = x;
    t->Points[i].y = y;
    t->Points[i].z = z;
    t->Points[i].pad = 0.0f;
    t->CalculatedSpeed[i] = speed;
    t->Route[i] = (int8_t)route;
    t->RoutePointNumber[i] = (int16_t)rpn;
    t->DrivingLine[i] = (int8_t)dl;
}

static void car_set(Car *c, float px, float py, float vx, float vy,
                    float ax, float ay, unsigned angle, float fwd, float vmag)
{
    memset(c, 0, sizeof(*c));
    c->State.Position.x = px;
    c->State.Position.y = py;
    c->State.Velocity.x = vx;
    c->State.Velocity.y = vy;
    c->State.Acceleration.x = ax;
    c->State.Acceleration.y = ay;
    c->State.Angle = (uint16_t)angle;
    c->State.ForwardSpeed = fwd;
    c->State.VelocityMagnitude = vmag;
}

// ShiftRight blanks x, y, z, CalculatedSpeed and RoutePointNumber and
// leaves Route, DrivingLine and the fourth lane alone. dt_point writes
// 0.0f into every pad, so a kept pad and a blanked one are the same
// number until something puts a different one there.
static void dt_dirty_pads(DriveTarget *t)
{
    int i;

    for (i = 0; i < 20; i++)
        t->Points[i].pad = (float)(100 + i);
}

// A straight target running east, five points ten metres apart, all on the
// same route and driving line.
static void dt_straight(DriveTarget *t)
{
    dt_reset(t);
    dt_point(t, 0, 10.0f,  0.0f, 0.0f, 20.0f, 3, 11, 1);
    dt_point(t, 1, 20.0f,  0.0f, 0.0f, 21.0f, 3, 12, 1);
    dt_point(t, 2, 30.0f,  0.0f, 0.0f, 22.0f, 3, 13, 1);
    dt_point(t, 3, 40.0f,  0.0f, 0.0f, 23.0f, 3, 14, 2);
    dt_point(t, 4, 50.0f,  0.0f, 0.0f, 24.0f, 4, 15, 2);
    t->NumPoints = 5;
    drivetarget_recalculate_length(t);
}

// The same five points bent into a corner, with a z step so the three-lane
// sums cannot pass by accident.
static void dt_corner(DriveTarget *t)
{
    dt_reset(t);
    dt_point(t, 0, 10.0f,  1.0f, 0.25f,  18.0f, 3, 11, 1);
    dt_point(t, 1, 19.0f,  5.0f, 0.5f,   17.0f, 3, 12, 1);
    dt_point(t, 2, 25.0f, 13.0f, 0.75f,  16.0f, 3, 13, 1);
    dt_point(t, 3, 28.0f, 23.0f, 1.0f,   15.0f, 3, 14, 2);
    dt_point(t, 4, 28.5f, 34.0f, 1.25f,  14.0f, 4, 15, 2);
    t->NumPoints = 5;
    drivetarget_recalculate_length(t);
}

// ----------------------------------------------------------------- layout

static void s_layout(void)
{
    pint("ly sizeof", (int)sizeof(DriveTarget));
    pint("ly points", (int)offsetof(DriveTarget, Points));
    pint("ly speed", (int)offsetof(DriveTarget, CalculatedSpeed));
    pint("ly route", (int)offsetof(DriveTarget, Route));
    pint("ly rpn", (int)offsetof(DriveTarget, RoutePointNumber));
    pint("ly dline", (int)offsetof(DriveTarget, DrivingLine));
    pint("ly ttype", (int)offsetof(DriveTarget, TType));
    pint("ly pick", (int)offsetof(DriveTarget, WhichPointIPicked));
    pint("ly calct", (int)offsetof(DriveTarget, WhichPointIPickedCalculationTime));
    pint("ly blendt", (int)offsetof(DriveTarget, WhichPointIPickedTime));
    pint("ly length", (int)offsetof(DriveTarget, Length));
    pint("ly last", (int)offsetof(DriveTarget, LastPointToScore));
    pint("ly maxpoints", DRIVETARGET_MAX_POINTS);
    pint("ly car driver", (int)offsetof(Car, DriverNumber));
    pint("ly car player", (int)offsetof(Car, pPlayer));
    pint("ly car state", (int)offsetof(Car, State));
    pint("ly dl route", (int)offsetof(DrivingLocation, pRoute));
    pint("ly dl point", (int)offsetof(DrivingLocation, pRoutePoint));
    pint("ly dl line", (int)offsetof(DrivingLocation, DrivingLine));
}

static void s_constants(void)
{
    drivetarget_static_init();
    pf("k seconds", AIDriverSecondsToLookAhead);
    pf("k default", AIDriverDefaultLookAhead);
    pf("k mindist", DriveTargetMinDistanceToPoint);
    pf("k mindistsq", DriveTargetMinDistanceToPointSquared);
    pint("k camdefault", (int)CameraFollowDefaultCar);
    pint("k caminstead", (int)CameraFollowThisCarInstead);
    pf("k maxlat", drivetarget_get_max_lateral_acceleration(0, 0));
}

// ------------------------------------------------------------- lifetime

static void s_ctor(void)
{
    DriveTarget t;
    DriveTarget a, b;
    unsigned char *pb;
    int i;

    // Dirty every byte first, so the memset has something to prove.
    memset(&t, 0xA5, sizeof(t));
    t.NumPoints = 7;
    drivetarget_init(&t);
    pdt("ct init", &t, 3);
    ppad("ct init", &t);

    // Assignment copies all 528 bytes; the copy constructor does not touch
    // the three pad runs. Both destinations start dirty so the difference
    // shows.
    dt_corner(&t);
    pb = (unsigned char *)&t;
    for (i = 1; i < 16; i++) pb[i] = (unsigned char)(0x10 + i);
    pb[501] = 0x71; pb[502] = 0x72; pb[503] = 0x73;
    for (i = 516; i < 528; i++) pb[i] = (unsigned char)(0x80 + i - 516);
    t.TType = 9;
    t.WhichPointIPicked = 2;
    t.WhichPointIPickedCalculationTime = 44;
    t.WhichPointIPickedTime = 55;

    memset(&a, 0x3C, sizeof(a));
    memset(&b, 0x3C, sizeof(b));
    pint("ct assign is dst", drivetarget_assign(&a, &t) == &a);
    drivetarget_copy(&b, &t);
    // All twenty slots: the copy constructor's five loops run to twenty
    // and the destinations start dirty, so a loop one short shows.
    pdt("ct assign", &a, 20);
    ppad("ct assign", &a);
    pdt("ct copy", &b, 20);
    ppad("ct copy", &b);
    pint("ct same", memcmp(&a, &b, sizeof(a)) == 0);

    drivetarget_destroy(&t);
    pdt("ct dtor", &t, 1);
}

// ------------------------------------------------------------- the scalars

static void s_get_angle(void)
{
    DriveTarget t;
    int i;

    dt_corner(&t);
    for (i = -3; i < 7; i++)
        pint("ga corner", (int)drivetarget_get_angle(&t, i));

    // Two points is the smallest list the clamp keeps inside the array.
    dt_reset(&t);
    dt_point(&t, 0, 1.0f, 2.0f, 0.0f, 0.0f, -1, -1, -1);
    dt_point(&t, 1, 4.0f, 6.0f, 0.0f, 0.0f, -1, -1, -1);
    t.NumPoints = 2;
    for (i = -1; i < 3; i++)
        pint("ga two", (int)drivetarget_get_angle(&t, i));

    // One point clamps the index to -1, which reads the record's own first
    // sixteen bytes as a vector. They are zero on a record the constructor
    // built, so this is defined and deterministic -- see the header.
    drivetarget_init(&t);
    dt_point(&t, 0, 3.0f, 4.0f, 0.0f, 0.0f, -1, -1, -1);
    t.NumPoints = 1;
    pint("ga one", (int)drivetarget_get_angle(&t, 0));
}

static void s_calculate_time(void)
{
    static const float d[] = { 100.0f, 0.0f, -50.0f };
    static const float b[] = { 20.0f, 0.0f, 0.0005f, -20.0f, 0.001f };
    static const float c[] = { 30.0f, 0.0f, 0.0005f, 0.001f };
    int i, j, k;

    for (i = 0; i < 3; i++)
        for (j = 0; j < 5; j++)
            for (k = 0; k < 4; k++)
                pf("ti", drivetarget_calculate_time(0, d[i], b[j], c[k]));
}

static void s_recalculate_length(void)
{
    DriveTarget t;

    dt_corner(&t);
    t.Length = 123.0f;
    t.NumPoints = 0;
    drivetarget_recalculate_length(&t);
    pf("rl zero", t.Length);

    t.NumPoints = 1;
    t.Length = 123.0f;
    drivetarget_recalculate_length(&t);
    pf("rl one", t.Length);

    t.NumPoints = 2;
    drivetarget_recalculate_length(&t);
    pf("rl two", t.Length);

    t.NumPoints = 5;
    drivetarget_recalculate_length(&t);
    pf("rl five", t.Length);

    // (x*x + y*y) + z*z and no other grouping. A half-ulp fixture is no
    // use here: the two sums differ by one ulp and the square root halves
    // that, so it rounds back to the same float. These three legs are one
    // of the triples where the two groupings round apart and the root
    // keeps them apart -- 25.4676304 against 25.4676323.
    dt_reset(&t);
    dt_point(&t, 0, 0.0f, 0.0f, 0.0f, 0.0f, -1, -1, -1);
    dt_point(&t, 1, -0.599609375f, -20.515625f, -15.078125f,
             0.0f, -1, -1, -1);
    t.NumPoints = 2;
    drivetarget_recalculate_length(&t);
    pf("rl assoc", t.Length);

    // A negative count takes the same early-out as zero.
    t.NumPoints = -3;
    t.Length = 123.0f;
    drivetarget_recalculate_length(&t);
    pf("rl neg", t.Length);
}

// -------------------------------------------------------------- the editors

static void s_set_point(void)
{
    DriveTarget t;
    bVector3 p3;
    bVector2 p2;

    dt_corner(&t);
    p3.x = 99.0f; p3.y = 98.0f; p3.z = 97.0f; p3.pad = 96.0f;
    drivetarget_set_point3(&t, 2, &p3, 7, 71, 3, 33.0f);
    pdt("sp wide", &t, 5);

    // Out of range in both directions, and the index the list has not
    // reached yet.
    drivetarget_set_point3(&t, -1, &p3, 8, 81, 4, 34.0f);
    drivetarget_set_point3(&t, 5, &p3, 8, 81, 4, 34.0f);
    drivetarget_set_point3(&t, 19, &p3, 8, 81, 4, 34.0f);
    pdt("sp oob", &t, 6);

    p2.x = 55.0f; p2.y = 44.0f;
    drivetarget_set_point2(&t, 0, &p2, -1, -1, -1, 0.0f);
    pdt("sp narrow", &t, 2);

    // The time stamp is cleared by every accepted write and left alone by
    // every rejected one.
    t.WhichPointIPickedCalculationTime = 12;
    drivetarget_set_point3(&t, 7, &p3, 1, 1, 1, 1.0f);
    pint("sp calct kept", (int)t.WhichPointIPickedCalculationTime);
    drivetarget_set_point3(&t, 1, &p3, 1, 1, 1, 1.0f);
    pint("sp calct cleared", (int)t.WhichPointIPickedCalculationTime);
}

static void s_shift_right(void)
{
    DriveTarget t;
    int n;

    for (n = 0; n < 4; n++) {
        dt_corner(&t);
        dt_dirty_pads(&t);
        t.WhichPointIPickedCalculationTime = 5;
        t.WhichPointIPickedTime = 6;
        drivetarget_shift_right(&t, n);
        pdt("sr", &t, 9);
    }

    // Twenty is refused; nineteen is not.
    dt_corner(&t);
    drivetarget_shift_right(&t, 20);
    pdt("sr twenty", &t, 6);
    dt_corner(&t);
    drivetarget_shift_right(&t, 19);
    pdt("sr nineteen", &t, 20);

    // The clamp: seventeen points plus five slots would be twenty-two.
    dt_reset(&t);
    for (n = 0; n < 17; n++)
        dt_point(&t, n, (float)n, 0.0f, 0.0f, 1.0f, 2, n, 1);
    t.NumPoints = 17;
    drivetarget_shift_right(&t, 5);
    pdt("sr clamp", &t, 20);
}

static void s_shift_left(void)
{
    DriveTarget t;
    int n;

    for (n = 0; n < 6; n++) {
        dt_corner(&t);
        t.WhichPointIPickedCalculationTime = 5;
        t.WhichPointIPickedTime = 6;
        drivetarget_shift_left(&t, n, 1);
        pdt("sl recalc", &t, 6);
    }

    dt_corner(&t);
    drivetarget_shift_left(&t, 2, 0);
    pdt("sl keep", &t, 6);

    // n == NumPoints is refused, so the list can never be emptied this way.
    dt_corner(&t);
    drivetarget_shift_left(&t, 5, 1);
    pdt("sl all", &t, 6);
}

// ----------------------------------------------------------- routes

static TrackRoute gRouteA;
static TrackRoute gRouteB;
// Route zero, because the sentinel for "no route" is -1 and only a route
// the manager actually has at index zero can say so.
static TrackRoute gRouteC;

static void routes_init(void)
{
    int i;

    memset(&gRouteA, 0, sizeof(gRouteA));
    memset(&gRouteB, 0, sizeof(gRouteB));
    gRouteA.RouteNumber = 3;
    gRouteB.RouteNumber = 4;
    for (i = 0; i < 40; i++) {
        gRouteA.TrackRoutePointTable[i].RouteNumber = 3;
        gRouteB.TrackRoutePointTable[i].RouteNumber = 4;
    }
    memset(&gRouteC, 0, sizeof(gRouteC));
    gRouteC.RouteNumber = 0;
    for (i = 0; i < 40; i++)
        gRouteC.TrackRoutePointTable[i].RouteNumber = 0;
    memset(&TheTrackRouteManager, 0, sizeof(TheTrackRouteManager));
    TheTrackRouteManager.pTrackRoutes[0] = &gRouteC;
    TheTrackRouteManager.pTrackRoutes[3] = &gRouteA;
    TheTrackRouteManager.pTrackRoutes[4] = &gRouteB;
}

static void s_route_point(void)
{
    DriveTarget t;
    TrackRoute *r;
    TrackRoutePoint *p;
    int i, got;

    routes_init();
    dt_corner(&t);
    t.Route[2] = -1;                 // no route
    t.RoutePointNumber[3] = -1;      // no point
    t.Route[1] = 7;                  // a route the manager does not have

    // Three more slots, because the first five cannot separate the bound
    // from the sentinel: route zero is a route the manager has and not a
    // refusal, -3 is below the sentinel rather than equal to it, and slot
    // 7 is past NumPoints rather than past twenty.
    t.NumPoints = 7;
    t.Route[5] = 0;  t.RoutePointNumber[5] = 4;  t.DrivingLine[5] = 1;
    t.Route[6] = -3; t.RoutePointNumber[6] = 5;  t.DrivingLine[6] = 1;
    t.Route[7] = 4;  t.RoutePointNumber[7] = 6;  t.DrivingLine[7] = 1;

    for (i = -1; i < 9; i++) {
        got = drivetarget_get_route_and_route_point(&t, i, &r, &p);
        printf("rp %d -> %d route %d point %d\n", i, got,
               r ? (int)r->RouteNumber : -99,
               p ? (int)(p - r->TrackRoutePointTable) : -99);
    }
}

// ------------------------------------------------------- the point chooser

static void s_first_point(void)
{
    DriveTarget t;
    Car car;

    routes_init();
    WorldTimer = 100;

    // Straight ahead at 20 m/s: the first point is already further away
    // than the four-metre minimum, so it wins.
    dt_straight(&t);
    car_set(&car, 0.0f, 0.0f, 20.0f, 0.0f, 0.0f, 0.0f, 0, 20.0f, 20.0f);
    pint("fp ahead", (int)drivetarget_get_first_point(&t, &car.State));
    pint("fp calct", (int)t.WhichPointIPickedCalculationTime);

    // The answer is cached for the frame: moving the car does nothing until
    // the tick changes.
    car.State.Position.x = 45.0f;
    pint("fp cached", (int)drivetarget_get_first_point(&t, &car.State));
    WorldTimer = 101;
    pint("fp uncached", (int)drivetarget_get_first_point(&t, &car.State));

    // Sitting on top of the first point: it fails the distance test and the
    // second one is taken.
    WorldTimer = 102;
    car_set(&car, 8.0f, 0.0f, 20.0f, 0.0f, 0.0f, 0.0f, 0, 20.0f, 20.0f);
    pint("fp tooclose", (int)drivetarget_get_first_point(&t, &car.State));

    // Driving away from the whole list: nothing passes the cone and the
    // fallback is the last point.
    WorldTimer = 103;
    car_set(&car, 0.0f, 0.0f, -20.0f, 0.0f, 0.0f, 0.0f, 0, -20.0f, 20.0f);
    pint("fp behind", (int)drivetarget_get_first_point(&t, &car.State));

    // The cone is 70 degrees wide. A point at 60 degrees off the heading
    // passes and one at 80 does not, until the car is over 30 m/s -- where
    // the threshold drops to zero and anything not behind it counts.
    WorldTimer = 104;
    dt_reset(&t);
    dt_point(&t, 0,  5.0f,  8.66025f, 0.0f, 0.0f, 2, 1, 1);  // 60 degrees
    dt_point(&t, 1,  1.73648f, 9.84808f, 0.0f, 0.0f, 2, 2, 1);
    dt_point(&t, 2, 30.0f,  0.0f, 0.0f, 0.0f, 2, 3, 1);
    t.NumPoints = 3;
    car_set(&car, 0.0f, 0.0f, 10.0f, 0.0f, 0.0f, 0.0f, 0, 10.0f, 10.0f);
    pint("fp cone60", (int)drivetarget_get_first_point(&t, &car.State));

    WorldTimer = 105;
    dt_reset(&t);
    dt_point(&t, 0, 1.73648f, 9.84808f, 0.0f, 0.0f, 2, 2, 1);  // 80 degrees
    dt_point(&t, 1, 30.0f, 0.0f, 0.0f, 0.0f, 2, 3, 1);
    t.NumPoints = 2;
    pint("fp cone80", (int)drivetarget_get_first_point(&t, &car.State));

    WorldTimer = 106;
    car.State.ForwardSpeed = 31.0f;
    pint("fp cone80 fast", (int)drivetarget_get_first_point(&t, &car.State));

    // Exactly 30 is not "fast": the test is strict.
    WorldTimer = 107;
    car.State.ForwardSpeed = 30.0f;
    pint("fp cone80 at30", (int)drivetarget_get_first_point(&t, &car.State));

    // Sixty-five degrees off the heading is a dot of 0.42262, which is
    // clear of the 0.342 threshold on one side and of a half on the
    // other. The sixty-degree point above is 0.50000018 after the
    // normalise -- one ulp the wrong side of a half, and so no use for
    // saying where the threshold is.
    WorldTimer = 109;
    dt_reset(&t);
    dt_point(&t, 0,  4.2262f, 9.0631f, 0.0f, 0.0f, 2, 1, 1);
    dt_point(&t, 1, 30.0f,    0.0f,    0.0f, 0.0f, 2, 3, 1);
    t.NumPoints = 2;
    car_set(&car, 0.0f, 0.0f, 10.0f, 0.0f, 0.0f, 0.0f, 0, 10.0f, 10.0f);
    pint("fp cone65", (int)drivetarget_get_first_point(&t, &car.State));

    // Over thirty the threshold is exactly zero, and a point straight
    // abeam normalises to (0,1) against a heading of (1,0) for a dot of
    // exactly zero. The test is strict, so the point is refused.
    WorldTimer = 110;
    dt_reset(&t);
    dt_point(&t, 0,  0.0f, 10.0f, 0.0f, 0.0f, 2, 1, 1);
    dt_point(&t, 1, 30.0f,  0.0f, 0.0f, 0.0f, 2, 3, 1);
    t.NumPoints = 2;
    car.State.ForwardSpeed = 31.0f;
    pint("fp perp fast", (int)drivetarget_get_first_point(&t, &car.State));

    // An empty target answers zero and clears the stamp rather than setting
    // it, so it re-answers on the next call inside the same frame.
    WorldTimer = 108;
    dt_reset(&t);
    t.WhichPointIPicked = 9;
    pint("fp empty", (int)drivetarget_get_first_point(&t, &car.State));
    pint("fp empty calct", (int)t.WhichPointIPickedCalculationTime);
}

// -------------------------------------------------------------- adding

static void s_add_point(void)
{
    DriveTarget t;
    Car car;
    bVector3 p3;
    bVector2 p2;
    DrivingLocation loc;
    int i;

    routes_init();
    WorldTimer = 200;

    // No check: everything lands, and Length grows by each leg.
    dt_reset(&t);
    for (i = 0; i < 3; i++) {
        p3.x = 10.0f * (float)(i + 1);
        p3.y = 0.0f;
        p3.z = 0.5f;
        p3.pad = 0.25f;
        drivetarget_add_point3(&t, &p3, (int8_t)(i + 1), (int16_t)(i + 10),
                               (int8_t)i, 0, 0);
    }
    pdt("ap free", &t, 4);

    // Checked with two points already there: a point that carries on is
    // taken and one that doubles back is refused.
    p3.x = 40.0f; p3.y = 0.0f; p3.z = 0.5f; p3.pad = 0.0f;
    drivetarget_add_point3(&t, &p3, 5, 15, 1, 1, 0);
    pint("ap forward n", (int)t.NumPoints);
    p3.x = 5.0f;
    drivetarget_add_point3(&t, &p3, 6, 16, 1, 1, 0);
    pint("ap back n", (int)t.NumPoints);

    // Exactly perpendicular gives a dot of zero, which is not less than
    // zero, so it is accepted.
    p3.x = 40.0f; p3.y = 12.0f;
    drivetarget_add_point3(&t, &p3, 7, 17, 1, 1, 0);
    pint("ap perp n", (int)t.NumPoints);
    pdt("ap checked", &t, 6);

    // Checked with fewer than two points: the car decides, and with no car
    // the point is simply taken.
    dt_reset(&t);
    car_set(&car, 0.0f, 0.0f, 10.0f, 0.0f, 0.0f, 0.0f, 0, 10.0f, 10.0f);
    p3.x = 20.0f; p3.y = 0.0f; p3.z = 0.0f; p3.pad = 0.0f;
    drivetarget_add_point3(&t, &p3, 1, 1, 1, 1, &car);
    pint("ap car ahead", (int)t.NumPoints);
    p3.x = -20.0f;
    drivetarget_add_point3(&t, &p3, 2, 2, 2, 1, &car);
    pint("ap car behind", (int)t.NumPoints);
    drivetarget_add_point3(&t, &p3, 2, 2, 2, 1, 0);
    pint("ap nocar", (int)t.NumPoints);

    // The doubling-back test is three lanes and every fixture above is
    // flat, so the third has never mattered. Here it decides: the two
    // lane dot is -0.5 and the z term is +6.
    dt_reset(&t);
    dt_point(&t, 0, 0.0f, 0.0f, 0.0f, 0.0f, 1, 1, 1);
    dt_point(&t, 1, 1.0f, 0.0f, 3.0f, 0.0f, 1, 2, 1);
    t.NumPoints = 2;
    p3.x = 0.5f; p3.y = 0.0f; p3.z = 5.0f; p3.pad = 0.0f;
    drivetarget_add_point3(&t, &p3, 2, 3, 1, 1, 0);
    pint("ap z saves n", (int)t.NumPoints);

    // The car form is called with a threshold of zero, so seventy-five
    // degrees off the heading -- a dot of 0.25882 -- still counts.
    dt_reset(&t);
    car_set(&car, 0.0f, 0.0f, 10.0f, 0.0f, 0.0f, 0.0f, 0, 10.0f, 10.0f);
    p3.x = 2.5882f; p3.y = 9.6593f; p3.z = 0.0f; p3.pad = 0.0f;
    drivetarget_add_point3(&t, &p3, 1, 1, 1, 1, &car);
    pint("ap car 75deg", (int)t.NumPoints);

    // Both stamps are cleared on the way through, and they are cleared
    // separately -- two stores, not one.
    dt_reset(&t);
    t.WhichPointIPickedCalculationTime = 44;
    t.WhichPointIPickedTime = 45;
    p3.x = 1.0f; p3.y = 2.0f; p3.z = 3.0f; p3.pad = 0.0f;
    drivetarget_add_point3(&t, &p3, 2, 3, 1, 0, 0);
    pdt("ap stamps", &t, 1);

    // Twenty is the wall.
    dt_reset(&t);
    for (i = 0; i < 25; i++) {
        p3.x = (float)i; p3.y = 0.0f; p3.z = 0.0f; p3.pad = 0.0f;
        drivetarget_add_point3(&t, &p3, 0, (int16_t)i, 0, 0, 0);
    }
    pint("ap full", (int)t.NumPoints);

    // The narrow overload zeroes z and the port zeroes pad with it.
    dt_reset(&t);
    p2.x = 3.0f; p2.y = 4.0f;
    drivetarget_add_point2(&t, &p2, -1, -1, -1, 0, 0);
    pdt("ap narrow", &t, 1);

    // The DrivingLocation overloads unpack the location. A clear one is
    // dropped before anything else happens.
    dt_reset(&t);
    loc.pRoute = 0;
    loc.pRoutePoint = 0;
    loc.DrivingLine = 5;
    p3.x = 1.0f; p3.y = 2.0f; p3.z = 3.0f; p3.pad = 4.0f;
    drivetarget_add_point3_dl(&t, &p3, &loc, 0, 0);
    pint("ap dl clear n", (int)t.NumPoints);

    loc.pRoute = &gRouteB;
    loc.pRoutePoint = &gRouteB.TrackRoutePointTable[17];
    drivetarget_add_point3_dl(&t, &p3, &loc, 0, 0);
    p2.x = 9.0f; p2.y = 8.0f;
    loc.pRoutePoint = &gRouteB.TrackRoutePointTable[0];
    loc.DrivingLine = -1;
    drivetarget_add_point2_dl(&t, &p2, &loc, 0, 0);
    pdt("ap dl", &t, 2);
}

// ------------------------------------------------------- walking the path

static void s_interpolate(void)
{
    DriveTarget t;
    Car car;
    bVector3 out;
    int r;
    static const float dists[] = { 5.0f, 15.0f, 25.0f, 55.0f, 100.0f };
    int i;

    routes_init();
    WorldTimer = 300;

    // No points: the answer is -1 and `out` is not written.
    dt_reset(&t);
    car_set(&car, 0.0f, 0.0f, 20.0f, 0.0f, 0.0f, 0.0f, 0, 20.0f, 20.0f);
    out.x = 1.0f; out.y = 2.0f; out.z = 3.0f; out.pad = 4.0f;
    r = drivetarget_interpolate_point(&t, &car, 10.0f, &out);
    pint("ip none", r);
    pv3("ip none out", &out);

    // One point: strike out towards it and stop at `dist`, overshoot or not.
    dt_reset(&t);
    dt_point(&t, 0, 30.0f, 40.0f, 0.0f, 0.0f, 1, 1, 1);
    t.Points[0].pad = 5.0f;
    t.NumPoints = 1;
    car.State.Position.pad = 2.0f;
    r = drivetarget_interpolate_point(&t, &car, 10.0f, &out);
    pint("ip one", r);
    pv3("ip one out", &out);
    r = drivetarget_interpolate_point(&t, &car, 100.0f, &out);
    pint("ip one far", r);
    pv3("ip one far out", &out);
    car.State.Position.pad = 0.0f;

    // The z lane, which every other one-point case leaves flat.
    WorldTimer = 301;
    dt_reset(&t);
    dt_point(&t, 0, 30.0f, 40.0f, 24.0f, 0.0f, 1, 1, 1);
    t.NumPoints = 1;
    r = drivetarget_interpolate_point(&t, &car, 10.0f, &out);
    pint("ip one z", r);
    pv3("ip one z out", &out);

    // `dist` exactly on the first point. The walk test is strict, so the
    // loop is not entered and the answer is the -1 of the first leg rather
    // than the 0 of the second.
    WorldTimer = 302;
    dt_straight(&t);
    r = drivetarget_interpolate_point(&t, &car, 10.0f, &out);
    pint("ip walk eq", r);
    pv3("ip walk eq out", &out);

    // `dist` inside the last leg, so the break lands on the last point
    // itself. Lerping that segment and extrapolating back along it give
    // the same place; only the returned index says which arm ran.
    WorldTimer = 303;
    dt_straight(&t);
    r = drivetarget_interpolate_point(&t, &car, 45.0f, &out);
    pint("ip tail eq", r);
    pv3("ip tail eq out", &out);

    // The real walk, on the straight target and then the corner.
    for (i = 0; i < 5; i++) {
        WorldTimer = 310 + i;
        dt_straight(&t);
        car_set(&car, 0.0f, 0.0f, 20.0f, 0.0f, 0.0f, 0.0f, 0, 20.0f, 20.0f);
        r = drivetarget_interpolate_point(&t, &car, dists[i], &out);
        pint("ip straight", r);
        pv3("ip straight out", &out);
    }

    for (i = 0; i < 5; i++) {
        WorldTimer = 320 + i;
        dt_corner(&t);
        car_set(&car, 0.0f, 0.0f, 15.0f, 2.0f, 0.0f, 0.0f, 0, 15.0f, 15.13275f);
        r = drivetarget_interpolate_point(&t, &car, dists[i], &out);
        pint("ip corner", r);
        pv3("ip corner out", &out);
    }

    // Starting from the middle of the list, so `first` is not zero and the
    // -1 return can happen on a later point.
    WorldTimer = 330;
    dt_straight(&t);
    car_set(&car, 22.0f, 0.0f, 20.0f, 0.0f, 0.0f, 0.0f, 0, 20.0f, 20.0f);
    r = drivetarget_interpolate_point(&t, &car, 5.0f, &out);
    pint("ip mid", r);
    pv3("ip mid out", &out);
    pint("ip mid pick", (int)t.WhichPointIPicked);
}

static void s_clear(void)
{
    DriveTarget t;
    Car car;

    routes_init();
    WorldTimer = 400;

    // Empty: Length is zeroed and nothing else happens, and the null Car is
    // never touched.
    dt_reset(&t);
    t.Length = 77.0f;
    t.WhichPointIPickedTime = 3;
    t.WhichPointIPickedCalculationTime = 4;
    drivetarget_clear(&t, 0, 12.0f);
    pdt("cl empty", &t, 1);

    // A speed inside the epsilon, and a negative one, both empty the list.
    dt_straight(&t);
    car_set(&car, 0.0f, 0.0f, 20.0f, 0.0f, 0.0f, 0.0f, 0, 20.0f, 20.0f);
    drivetarget_clear(&t, &car, 0.001f);
    pdt("cl eps", &t, 1);

    dt_straight(&t);
    drivetarget_clear(&t, &car, -5.0f);
    pdt("cl neg", &t, 1);

    // Just outside the epsilon is a real clear.
    WorldTimer = 401;
    dt_straight(&t);
    drivetarget_clear(&t, &car, 0.00101f);
    pdt("cl just", &t, 2);

    // Everything behind the car: the list is emptied.
    WorldTimer = 402;
    dt_straight(&t);
    car_set(&car, 100.0f, 0.0f, 20.0f, 0.0f, 0.0f, 0.0f, 0, 20.0f, 20.0f);
    drivetarget_clear(&t, &car, 25.0f);
    pdt("cl behind", &t, 1);

    // The ordinary case: keep the path up to 25 metres ahead.
    WorldTimer = 403;
    dt_straight(&t);
    car_set(&car, 0.0f, 0.0f, 20.0f, 0.0f, 0.0f, 0.0f, 0, 20.0f, 20.0f);
    drivetarget_clear(&t, &car, 25.0f);
    pdt("cl keep", &t, 5);

    // A short keep that lands on the first leg, which collapses the whole
    // target to a single point.
    WorldTimer = 404;
    dt_straight(&t);
    drivetarget_clear(&t, &car, 5.0f);
    pdt("cl collapse", &t, 2);

    // A keep longer than the path runs off the end and extrapolates.
    WorldTimer = 405;
    dt_straight(&t);
    drivetarget_clear(&t, &car, 200.0f);
    pdt("cl past", &t, 6);

    // Starting behind the first two points, so the shift runs first.
    WorldTimer = 406;
    dt_straight(&t);
    car_set(&car, 25.0f, 0.0f, 20.0f, 0.0f, 0.0f, 0.0f, 0, 20.0f, 20.0f);
    drivetarget_clear(&t, &car, 15.0f);
    pdt("cl shifted", &t, 4);

    // A point exactly abeam: the dot against the raw velocity is zero and
    // the test is strict, so the walk steps over it.
    WorldTimer = 408;
    dt_reset(&t);
    dt_point(&t, 0, 0.0f, 10.0f, 0.0f, 20.0f, 3, 11, 1);
    dt_point(&t, 1, 20.0f, 0.0f, 0.0f, 21.0f, 3, 12, 1);
    dt_point(&t, 2, 30.0f, 0.0f, 0.0f, 22.0f, 3, 13, 1);
    dt_point(&t, 3, 40.0f, 0.0f, 0.0f, 23.0f, 3, 14, 2);
    t.NumPoints = 4;
    drivetarget_recalculate_length(&t);
    car_set(&car, 0.0f, 0.0f, 20.0f, 0.0f, 0.0f, 0.0f, 0, 20.0f, 20.0f);
    drivetarget_clear(&t, &car, 15.0f);
    pdt("cl abeam", &t, 4);

    // A switchback at the point the truncation lands on. The truncating
    // AddPointToTarget is the unchecked one, so the doubling-back point
    // goes in; the checked overload would refuse it.
    WorldTimer = 409;
    dt_reset(&t);
    dt_point(&t, 0, 10.0f, 0.0f, 0.0f, 20.0f, 3, 11, 1);
    dt_point(&t, 1, 20.0f, 0.0f, 0.0f, 21.0f, 3, 12, 1);
    dt_point(&t, 2, 10.0f, 10.0f, 0.0f, 22.0f, 3, 13, 1);
    dt_point(&t, 3, 0.0f, 20.0f, 0.0f, 23.0f, 3, 14, 2);
    t.NumPoints = 4;
    drivetarget_recalculate_length(&t);
    drivetarget_clear(&t, &car, 25.0f);
    pdt("cl switchback", &t, 4);

    // The collapse arm reads its route data out of the slot GetFirstPoint
    // chose, and that is not always slot zero: the first point here is
    // inside the minimum distance, so the cone test steps past it while
    // Clear's own velocity walk does not.
    WorldTimer = 410;
    dt_reset(&t);
    dt_point(&t, 0, 2.0f, 0.0f, 0.0f, 20.0f, 3, 11, 1);
    dt_point(&t, 1, 20.0f, 5.0f, 0.0f, 21.0f, 4, 12, 2);
    dt_point(&t, 2, 30.0f, 10.0f, 0.0f, 22.0f, 3, 13, 1);
    dt_point(&t, 3, 40.0f, 15.0f, 0.0f, 23.0f, 3, 14, 2);
    t.NumPoints = 4;
    drivetarget_recalculate_length(&t);
    drivetarget_clear(&t, &car, 15.0f);
    pdt("cl collapse pick", &t, 2);

    // The corner, where the leg lengths differ.
    WorldTimer = 407;
    dt_corner(&t);
    car_set(&car, 0.0f, 0.0f, 15.0f, 2.0f, 0.0f, 0.0f, 0, 15.0f, 15.13275f);
    drivetarget_clear(&t, &car, 20.0f);
    pdt("cl corner", &t, 5);
}

static void s_resample(void)
{
    DriveTarget t;
    Car car;
    int i;

    car_set(&car, 0.0f, 0.0f, 20.0f, 0.0f, 0.0f, 0.0f, 0, 20.0f, 20.0f);

    // Fewer than three points is refused.
    dt_corner(&t);
    t.NumPoints = 2;
    drivetarget_resample(&t, &car);
    pdt("rs two", &t, 3);

    dt_corner(&t);
    t.NumPoints = 3;
    drivetarget_resample(&t, &car);
    pdt("rs three", &t, 4);

    dt_corner(&t);
    drivetarget_resample(&t, &car);
    pdt("rs corner", &t, 6);

    dt_straight(&t);
    drivetarget_resample(&t, &car);
    pdt("rs straight", &t, 6);

    // Unevenly spaced: one very long leg among short ones is where the
    // segment-skipping inner loop has to run more than once.
    dt_reset(&t);
    dt_point(&t, 0,  0.0f, 0.0f, 0.0f, 1.0f, 1, 1, 1);
    dt_point(&t, 1,  1.0f, 0.0f, 0.0f, 1.0f, 1, 2, 1);
    dt_point(&t, 2,  2.0f, 0.0f, 0.0f, 1.0f, 1, 3, 1);
    dt_point(&t, 3, 62.0f, 0.0f, 0.0f, 1.0f, 1, 4, 1);
    dt_point(&t, 4, 63.0f, 0.0f, 0.0f, 1.0f, 1, 5, 1);
    dt_point(&t, 5, 64.0f, 0.0f, 0.0f, 1.0f, 1, 6, 1);
    t.NumPoints = 6;
    drivetarget_recalculate_length(&t);
    drivetarget_resample(&t, &car);
    pdt("rs uneven", &t, 7);

    // The pads and both stamps carry through: Resample interpolates the
    // fourth lane with the other three and clears the two stamps.
    dt_corner(&t);
    dt_dirty_pads(&t);
    t.WhichPointIPickedCalculationTime = 51;
    t.WhichPointIPickedTime = 52;
    drivetarget_resample(&t, &car);
    pdt("rs pads", &t, 6);

    // Integer legs of 10, 20, 10, 15, 20 and 5. The even step is 13 1/3,
    // which lands exactly on a segment end twice, and that is the only
    // place the inner walk's test can tell <= from <.
    dt_reset(&t);
    dt_point(&t, 0, 0.0f, 0.0f, 0.0f, 1.0f, 2, 0, 1);
    dt_point(&t, 1, 6.0f, -8.0f, 0.0f, 1.0f, 2, 1, 1);
    dt_point(&t, 2, 22.0f, 4.0f, 0.0f, 1.0f, 2, 2, 1);
    dt_point(&t, 3, 22.0f, 14.0f, 0.0f, 1.0f, 2, 3, 1);
    dt_point(&t, 4, 34.0f, 23.0f, 0.0f, 1.0f, 2, 4, 1);
    dt_point(&t, 5, 50.0f, 11.0f, 0.0f, 1.0f, 2, 5, 1);
    dt_point(&t, 6, 54.0f, 8.0f, 0.0f, 1.0f, 2, 6, 1);
    t.NumPoints = 7;
    drivetarget_recalculate_length(&t);
    drivetarget_resample(&t, &car);
    pdt("rs exact", &t, 7);

    // The inner walk's <= against <, with nothing else in the way. Three
    // points, legs of exactly 5 m: Length is 10, the step is 5, and the
    // accumulator lands on the end of segment 0 dead on. The real test
    // steps over it and emits point 1 at frac 0; a strict one stays on
    // segment 0 and emits P0 + seg0 at frac 1. Everything after that
    // re-syncs -- the mutant just spends the next pass stepping over the
    // segment it should already have left -- so the whole difference is
    // one slot.
    //
    // That slot only differs where the addition does not undo the
    // subtraction, which is why the pad carries it. 16777218 - 1 is a tie
    // and rounds to 16777216; 1 + 16777216 is the same tie and rounds back
    // to 16777216, two ulps short of the 16777218 the other arm copies
    // straight across. The pad is not in len3, so the geometry stays a
    // plain 3-4-5 ladder and the walk above does not notice it. The pads
    // are written here rather than through dt_point, whose fourth float is
    // the CalculatedSpeed -- it puts 0.0f in every pad.
    dt_reset(&t);
    dt_point(&t, 0, 0.0f, 0.0f, 0.0f, 1.0f, 2, 0, 1);
    dt_point(&t, 1, 3.0f, 4.0f, 0.0f, 1.0f, 2, 1, 1);
    dt_point(&t, 2, 6.0f, 8.0f, 0.0f, 1.0f, 2, 2, 1);
    t.Points[0].pad = 1.0f;
    t.Points[1].pad = 16777218.0f;
    t.NumPoints = 3;
    drivetarget_recalculate_length(&t);
    drivetarget_resample(&t, &car);
    pdt("rs frac one", &t, 3);

    // Twenty points, so the walk uses every slot.
    dt_reset(&t);
    for (i = 0; i < 20; i++)
        dt_point(&t, i, (float)i * 3.0f, (float)i * (float)i * 0.25f, 0.0f,
                 1.0f, 2, i, 1);
    t.NumPoints = 20;
    drivetarget_recalculate_length(&t);
    drivetarget_resample(&t, &car);
    pdt("rs twenty", &t, 20);

    // The port's alone, and silent, since the EE has no infinity for the
    // model to compare: an infinite point, points too far apart for the
    // squares, and a NaN point. Each walk must end inside its twenty slots
    // -- unbounded, the first two wrote NaN up the stack until something
    // died (the device's race-end crash) -- and the NaN must leave the
    // points alone.
    for (i = 0; i < 3; i++) {
        dt_reset(&t);
        dt_point(&t, 0, 0.0f, 0.0f, 0.0f, 1.0f, 2, 0, 1);
        dt_point(&t, 1, 10.0f, 0.0f, 0.0f, 1.0f, 2, 1, 1);
        dt_point(&t, 2, i == 0 ? INFINITY : i == 1 ? 3e19f : NAN, 0.0f,
                 0.0f, 1.0f, 2, 2, 1);
        dt_point(&t, 3, 20.0f, 0.0f, 0.0f, 1.0f, 2, 3, 1);
        t.NumPoints = 4;
        drivetarget_recalculate_length(&t);
        drivetarget_resample(&t, &car);
        if (i == 2 && t.Points[1].x != 10.0f) {
            fprintf(stderr, "rs nan: the points moved\n");
            exit(1);
        }
    }
}

// -------------------------------------------------------------- the scoring

static void s_max_speed(void)
{
    Car car;
    bVector2 p0, p1, p2;
    float out;
    int r;
    static const float exits[] = { 20.0f, 5.0f, 40.0f };
    int i;

    car_set(&car, 0.0f, 0.0f, 20.0f, 0.0f, 0.0f, 0.0f, 0, 20.0f, 20.0f);
    p0.x = 0.0f;  p0.y = 0.0f;
    p1.x = 20.0f; p1.y = 0.0f;
    p2.x = 40.0f; p2.y = 0.0f;

    // A speed inside the epsilon answers yes without touching pOut.
    out = 33.0f;
    r = drivetarget_calculate_max_speed(0, &car, &p0, &p1, &p2, 20.0f, 0.0005f,
                                        &out);
    pint("ms slow", r);
    pf("ms slow out", out);

    // A distance inside the epsilon answers yes and pins pOut to the entry
    // speed.
    out = 33.0f;
    r = drivetarget_calculate_max_speed(0, &car, &p0, &p1, &p2, 0.0005f, 20.0f,
                                        &out);
    pint("ms short", r);
    pf("ms short out", out);

    // Straight ahead: no lateral acceleration at all.
    for (i = 0; i < 3; i++) {
        out = exits[i];
        r = drivetarget_calculate_max_speed(0, &car, &p0, &p1, &p2, 20.0f,
                                            20.0f, &out);
        pint("ms straight", r);
        pf("ms straight out", out);
    }

    // A gentle corner fits; a hard one at speed does not.
    p2.x = 36.0f; p2.y = 8.0f;
    out = 20.0f;
    r = drivetarget_calculate_max_speed(0, &car, &p0, &p1, &p2, 20.0f, 20.0f,
                                        &out);
    pint("ms gentle", r);

    p2.x = 22.0f; p2.y = 20.0f;
    out = 40.0f;
    r = drivetarget_calculate_max_speed(0, &car, &p0, &p1, &p2, 20.0f, 40.0f,
                                        &out);
    pint("ms hard", r);

    // A right-angle turn taken slowly enough to stay inside the grip.
    out = 3.0f;
    r = drivetarget_calculate_max_speed(0, &car, &p0, &p1, &p2, 20.0f, 3.0f,
                                        &out);
    pint("ms slowturn", r);

    // Coincident points, so both normalises take their zero arm.
    p1 = p0;
    p2 = p0;
    out = 20.0f;
    r = drivetarget_calculate_max_speed(0, &car, &p0, &p1, &p2, 20.0f, 20.0f,
                                        &out);
    pint("ms same", r);
    pf("ms same out", out);

    // The entry-speed epsilon is 0.001 and the test is inclusive, so a car
    // crawling at exactly that answers yes without looking at the corner.
    // At 0.01 the same doubling-back corner has to be answered, and is
    // refused.
    p0.x = 0.0f;  p0.y = 0.0f;
    p1.x = 20.0f; p1.y = 0.0f;
    p2.x = 0.0f;  p2.y = 2.0f;
    out = 20.0f;
    r = drivetarget_calculate_max_speed(0, &car, &p0, &p1, &p2, 0.25f,
                                        0.00100000005f, &out);
    pint("ms eps speed", r);
    out = 20.0f;
    r = drivetarget_calculate_max_speed(0, &car, &p0, &p1, &p2, 0.25f, 0.01f,
                                        &out);
    pint("ms eps between", r);

    // Distance goes through fabsf and is then divided by unchanged, so a
    // negative one makes a negative time -- which the second fabsf catches
    // and a bare comparison would not.
    p2.x = 22.0f; p2.y = 20.0f;
    out = 30.0f;
    r = drivetarget_calculate_max_speed(0, &car, &p0, &p1, &p2, -20.0f, 20.0f,
                                        &out);
    pint("ms neg dist", r);
    pf("ms neg dist out", out);

    // A pure speed change along a straight line: all of the acceleration is
    // parallel to v1, so the lateral part is zero however hard the braking.
    p2.x = 40.0f; p2.y = 0.0f;
    out = 1.0f;
    r = drivetarget_calculate_max_speed(0, &car, &p0, &p1, &p2, 1.0f, 20.0f,
                                        &out);
    pint("ms brake hard", r);

    // One corner, two exit speeds one ulp apart, both landing the lateral
    // demand on the last float inside the margin -- 30.000999 against a
    // limit of 30 and a margin of 0.001. The answer is yes on both, and it
    // stops being yes if the reciprocal is divided by rather than
    // multiplied, if v1 is scaled by the exit speed instead of the entry
    // speed, or if the margin is dropped.
    p1.x = 9.125f;   p1.y = 17.3125f;
    p2.x = -24.375f; p2.y = -28.3125f;
    out = 104.335945f;
    r = drivetarget_calculate_max_speed(0, &car, &p0, &p1, &p2, 33.625f,
                                        26.5625f, &out);
    pint("ms grip edge", r);
    out = 104.335953f;
    r = drivetarget_calculate_max_speed(0, &car, &p0, &p1, &p2, 33.625f,
                                        26.5625f, &out);
    pint("ms grip edge up", r);

    // Retail's _v half on its own, handed the two velocities as they are: a
    // straight, a gentle and a hard corner, then a time inside its epsilon.
    {
        static const struct { const char *tag; float x, y, sp, dist; } mv[] = {
            { "mv straight", 20.0f,  0.0f, 20.0f, 20.0f },
            { "mv gentle",   16.0f, 12.0f, 20.0f, 20.0f },
            { "mv hard",      0.0f, 40.0f, 40.0f, 20.0f },
        };
        bVector2 v1, v2;
        char tag[64];

        v1.x = 20.0f; v1.y = 0.0f;
        for (i = 0; i < 3; i++) {
            v2.x = mv[i].x; v2.y = mv[i].y;
            out = mv[i].sp;
            r = drivetarget_calculate_max_speed_v(0, &car, &v1, &v2,
                                                  mv[i].dist, mv[i].sp, &out);
            pint(mv[i].tag, r);
            snprintf(tag, sizeof(tag), "%s out", mv[i].tag);
            pf(tag, out);
        }
        out = 33.0f;
        r = drivetarget_calculate_max_speed_v(0, &car, &v1, &v1, 0.0005f,
                                              20.0f, &out);
        pint("mv short", r);
        pf("mv short out", out);

        // It has neither of CalculateMaxSpeed's early answers, so a crawl
        // into a hard corner is asked about and refused.
        v2.x = 0.0f; v2.y = 40.0f;
        out = 40.0f;
        r = drivetarget_calculate_max_speed_v(0, &car, &v1, &v2, 20.0f,
                                              0.0005f, &out);
        pint("mv slow", r);

        // A zero v1, as from a car standing still: the projection divides
        // 0 by 0, the EE's FLT_MAX, and the lateral part is the whole
        // acceleration -- small here, so yes; large, so no.
        v1.x = 0.0f; v1.y = 0.0f;
        v2.x = 3.0f; v2.y = 4.0f;
        out = 5.0f;
        r = drivetarget_calculate_max_speed_v(0, &car, &v1, &v2, 20.0f, 0.0f,
                                              &out);
        pint("mv zero v1", r);
        v2.x = 300.0f; v2.y = 400.0f;
        out = 500.0f;
        r = drivetarget_calculate_max_speed_v(0, &car, &v1, &v2, 20.0f, 0.0f,
                                              &out);
        pint("mv zero v1 hard", r);
    }

    // Retail's first-corner question: v1 is State.Velocity unscaled, v2
    // aims from the car at the point, the distance is the factor times
    // |ForwardSpeed| and the entry speed is VelocityMagnitude.
    {
        static const struct { const char *tag; float x, y, want; } mc[] = {
            { "mc ahead",  30.0f,  0.0f, 20.0f },
            { "mc wide",   10.0f, 30.0f, 20.0f },
            { "mc slower", 30.0f,  2.0f, 12.0f },
            { "mc fwd 20", 30.0f, 10.0f, 20.0f },
        };
        bVector2 p;
        char tag[64];

        car_set(&car, 0.0f, 0.0f, 20.0f, 0.0f, 0.0f, 0.0f, 0, 20.0f, 20.0f);
        for (i = 0; i < 4; i++) {
            p.x = mc[i].x; p.y = mc[i].y;
            out = mc[i].want;
            r = drivetarget_calculate_max_speed_from_car(0, &car, &p, &out,
                                                         0.5f);
            pint(mc[i].tag, r);
            snprintf(tag, sizeof(tag), "%s out", mc[i].tag);
            pf(tag, out);
        }

        // The same 18-degree corner at three forward speeds and one entry
        // speed: half a second at 20 m/s fits, at 2 m/s it does not, and a
        // car going backwards at 20 is measured by the size of its speed.
        p.x = 30.0f; p.y = 10.0f;
        car_set(&car, 0.0f, 0.0f, 20.0f, 0.0f, 0.0f, 0.0f, 0, 2.0f, 20.0f);
        out = 20.0f;
        r = drivetarget_calculate_max_speed_from_car(0, &car, &p, &out, 0.5f);
        pint("mc fwd 2", r);
        car_set(&car, 0.0f, 0.0f, 20.0f, 0.0f, 0.0f, 0.0f, 0, -20.0f, 20.0f);
        out = 20.0f;
        r = drivetarget_calculate_max_speed_from_car(0, &car, &p, &out, 0.5f);
        pint("mc fwd back", r);

        // The factor scales the distance, and VelocityMagnitude, not
        // ForwardSpeed, is the entry speed.
        car_set(&car, 0.0f, 0.0f, 20.0f, 0.0f, 0.0f, 0.0f, 0, 20.0f, 20.0f);
        out = 20.0f;
        r = drivetarget_calculate_max_speed_from_car(0, &car, &p, &out, 0.05f);
        pint("mc factor", r);
        car_set(&car, 0.0f, 0.0f, 20.0f, 0.0f, 0.0f, 0.0f, 0, 20.0f, 200.0f);
        out = 20.0f;
        r = drivetarget_calculate_max_speed_from_car(0, &car, &p, &out, 0.5f);
        pint("mc vmag", r);

        // Standing still with nothing wanted at the point: bNormalize2To is
        // asked for a length of zero and the _v half then divides 0 by 0.
        // Both are the EE's FLT_MAX, and the corner fits -- on the point
        // itself too, where the vector is zero as well and IEEE would make
        // a NaN of it.
        car_set(&car, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0, 0.0f, 0.0f);
        out = 0.0f;
        r = drivetarget_calculate_max_speed_from_car(0, &car, &p, &out, 0.5f);
        pint("mc stopped", r);
        pf("mc stopped out", out);
        car_set(&car, 30.0f, 10.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0, 0.0f, 0.0f);
        out = 0.0f;
        r = drivetarget_calculate_max_speed_from_car(0, &car, &p, &out, 0.5f);
        pint("mc stopped on point", r);
        pf("mc stopped on point out", out);
    }
}

static void s_estimate_score(void)
{
    DriveTarget t;
    Car car;
    int i;

    routes_init();
    WorldTimer = 500;

    dt_reset(&t);
    car_set(&car, 0.0f, 0.0f, 20.0f, 0.0f, 0.0f, 0.0f, 0, 20.0f, 20.0f);
    pf("es none", drivetarget_estimate_score(&t, &car));

    WorldTimer = 501;
    dt_reset(&t);
    dt_point(&t, 0, 30.0f, 40.0f, 0.0f, 9.0f, 1, 1, 1);
    t.NumPoints = 1;
    pf("es one", drivetarget_estimate_score(&t, &car));
    pdt("es one after", &t, 2);

    WorldTimer = 502;
    dt_straight(&t);
    pf("es straight", drivetarget_estimate_score(&t, &car));
    pdt("es straight after", &t, 5);

    WorldTimer = 503;
    dt_corner(&t);
    car_set(&car, 0.0f, 0.0f, 15.0f, 2.0f, 0.0f, 0.0f, 0, 15.0f, 15.13275f);
    pf("es corner", drivetarget_estimate_score(&t, &car));
    pdt("es corner after", &t, 5);

    // Fast into the same corner: the lateral demand goes past the grip and
    // the whole target scores -1.
    WorldTimer = 504;
    dt_corner(&t);
    car_set(&car, 0.0f, 0.0f, 60.0f, 8.0f, 0.0f, 0.0f, 0, 60.0f, 60.5310f);
    pf("es corner fast", drivetarget_estimate_score(&t, &car));

    // Twenty points of gentle sweep, so both nested walks run.
    WorldTimer = 505;
    dt_reset(&t);
    for (i = 0; i < 20; i++)
        dt_point(&t, i, (float)i * 6.0f, (float)i * (float)i * 0.5f, 0.0f,
                 0.0f, 2, i, 1);
    t.NumPoints = 20;
    drivetarget_recalculate_length(&t);
    car_set(&car, 0.0f, 0.0f, 25.0f, 0.0f, 0.0f, 0.0f, 0, 25.0f, 25.0f);
    pf("es sweep", drivetarget_estimate_score(&t, &car));
    pdt("es sweep after", &t, 20);

    // A crawling car, where CalculateTime's sentinel arm is live.
    WorldTimer = 506;
    dt_straight(&t);
    car_set(&car, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0, 0.0f, 0.0f);
    pf("es stopped", drivetarget_estimate_score(&t, &car));

    // ForwardSpeed and VelocityMagnitude apart, because the one-point arm
    // reads the second and every other fixture passes the same number for
    // both.
    WorldTimer = 508;
    dt_reset(&t);
    dt_point(&t, 0, 30.0f, 40.0f, 0.0f, 9.0f, 1, 1, 1);
    t.NumPoints = 1;
    car_set(&car, 0.0f, 0.0f, 20.0f, 0.0f, 0.0f, 0.0f, 0, 7.0f, 20.0f);
    pf("es one fwd", drivetarget_estimate_score(&t, &car));
    pdt("es one fwd after", &t, 2);

    // Four points sitting on the car. Nothing clears the cone, every leg
    // is zero, and the distance total the score divides by is zero --
    // which is what the guard on that divide is for.
    WorldTimer = 509;
    dt_reset(&t);
    for (i = 0; i < 4; i++)
        dt_point(&t, i, 0.0f, 0.0f, 0.0f, 0.0f, 2, (int16_t)i, 1);
    t.NumPoints = 4;
    car_set(&car, 0.0f, 0.0f, 20.0f, 0.0f, 0.0f, 0.0f, 0, 20.0f, 20.0f);
    pf("es coincident", drivetarget_estimate_score(&t, &car));

    // The first point is 6 m out: far enough to clear the minimum distance
    // -- 4 m, and that test is strict, so a point at exactly 4 m would be
    // stepped over -- and 0.3 s at 20 m/s, inside the first threshold, so
    // the skip-ahead opens. The second point is 8 m out, which is 0.4 s
    // exactly: the second threshold itself, and that test is strict too.
    WorldTimer = 510;
    dt_reset(&t);
    dt_point(&t, 0, 6.0f, 0.0f, 0.0f, 0.0f, 2, 0, 1);
    dt_point(&t, 1, 8.0f, 0.0f, 0.0f, 0.0f, 2, 1, 1);
    dt_point(&t, 2, 12.0f, 16.0f, 0.0f, 0.0f, 2, 2, 1);
    dt_point(&t, 3, -6.0f, 10.0f, 0.0f, 0.0f, 2, 3, 1);
    dt_point(&t, 4, -10.0f, 30.0f, 0.0f, 0.0f, 2, 4, 1);
    t.NumPoints = 5;
    drivetarget_recalculate_length(&t);
    pf("es t2 edge", drivetarget_estimate_score(&t, &car));

    // Three layouts that reach the second walk with legs it can tell
    // apart: the outer leg is measured from the point before `outer`, the
    // inner one keeps measuring from that same point while `nxt` runs on,
    // and the skip-ahead inside it has to actually run.
    WorldTimer = 511;
    dt_reset(&t);
    dt_point(&t, 0, 6.0f, -11.25f, 0.0f, 0.0f, 2, 0, 1);
    dt_point(&t, 1, 12.0f, -14.25f, 0.0f, 0.0f, 2, 1, 1);
    dt_point(&t, 2, 15.0f, -10.75f, 0.0f, 0.0f, 2, 2, 1);
    dt_point(&t, 3, 26.0f, -11.0f, 0.0f, 0.0f, 2, 3, 1);
    dt_point(&t, 4, 29.5f, -15.25f, 0.0f, 0.0f, 2, 4, 1);
    dt_point(&t, 5, 42.0f, -25.5f, 0.0f, 0.0f, 2, 5, 1);
    t.NumPoints = 6;
    drivetarget_recalculate_length(&t);
    car_set(&car, 0.0f, 0.0f, 22.25f, 0.0f, 0.0f, 0.0f, 0, 22.25f, 22.25f);
    pf("es p2 base", drivetarget_estimate_score(&t, &car));

    WorldTimer = 512;
    dt_reset(&t);
    dt_point(&t, 0, 8.0f, 12.0f, 0.0f, 0.0f, 2, 0, 1);
    dt_point(&t, 1, 11.75f, 14.25f, 0.0f, 0.0f, 2, 1, 1);
    dt_point(&t, 2, 22.0f, 15.75f, 0.0f, 0.0f, 2, 2, 1);
    dt_point(&t, 3, 35.0f, 6.5f, 0.0f, 0.0f, 2, 3, 1);
    dt_point(&t, 4, 45.5f, 8.0f, 0.0f, 0.0f, 2, 4, 1);
    t.NumPoints = 5;
    drivetarget_recalculate_length(&t);
    car_set(&car, 0.0f, 0.0f, 31.75f, 0.0f, 0.0f, 0.0f, 0, 31.75f, 31.75f);
    pf("es p2 inner", drivetarget_estimate_score(&t, &car));

    WorldTimer = 513;
    dt_reset(&t);
    dt_point(&t, 0, 4.25f, -5.25f, 0.0f, 0.0f, 2, 0, 1);
    dt_point(&t, 1, 16.0f, -1.75f, 0.0f, 0.0f, 2, 1, 1);
    dt_point(&t, 2, 27.75f, -5.5f, 0.0f, 0.0f, 2, 2, 1);
    dt_point(&t, 3, 31.25f, -10.5f, 0.0f, 0.0f, 2, 3, 1);
    dt_point(&t, 4, 42.75f, -16.0f, 0.0f, 0.0f, 2, 4, 1);
    dt_point(&t, 5, 49.0f, -18.0f, 0.0f, 0.0f, 2, 5, 1);
    t.NumPoints = 6;
    drivetarget_recalculate_length(&t);
    car_set(&car, 0.0f, 0.0f, 21.75f, 0.0f, 0.0f, 0.0f, 0, 21.75f, 21.75f);
    pf("es p2 skip", drivetarget_estimate_score(&t, &car));
    pdt("es p2 skip after", &t, 6);

    // Two points only, which stops before the second walk.
    WorldTimer = 507;
    dt_straight(&t);
    t.NumPoints = 2;
    car_set(&car, 0.0f, 0.0f, 20.0f, 0.0f, 0.0f, 0.0f, 0, 20.0f, 20.0f);
    pf("es two", drivetarget_estimate_score(&t, &car));

    // The same skip-ahead, one notch the other side of the threshold. At
    // 35.5 m/s the first point is 0.145 s out, so the gate opens; the
    // second is 13.87 m, which is 0.391 s -- inside the threshold, so the
    // walk steps over it -- and the third is 15.01 m, or 0.423 s, which
    // stops it. The walk therefore ends on the third point and asks about
    // the corner that follows it, which fits. Halve the threshold and the
    // walk stops one point earlier instead, on a corner that does not.
    WorldTimer = 514;
    dt_reset(&t);
    dt_point(&t, 0, 1.25f, -5.0f, 0.0f, 0.0f, 2, 0, 1);
    dt_point(&t, 1, 6.5f, -12.25f, 0.0f, 0.0f, 2, 1, 1);
    dt_point(&t, 2, 15.0f, -0.5f, 0.0f, 0.0f, 2, 2, 1);
    dt_point(&t, 3, 26.25f, 2.5f, 0.0f, 0.0f, 2, 3, 1);
    t.NumPoints = 4;
    drivetarget_recalculate_length(&t);
    car_set(&car, 0.0f, 0.0f, 35.5f, 0.0f, 0.0f, 0.0f, 0, 35.5f, 35.5f);
    pf("es t2 mid", drivetarget_estimate_score(&t, &car));

    // Retail's accessor, on its own: NumPoints - 2 while the byte is -1,
    // the byte less one otherwise, both narrowed to a signed byte.
    {
        static const int lc[][2] = {
            { 5, -1 }, { 0, -1 }, { 1, -1 }, { 20, -1 }, { 5, 3 }, { 5, 0 },
            { 5, 1 }, { 20, 19 }, { 3, -128 }, { 3, 127 },
        };
        char tag[64];

        for (i = 0; i < 10; i++) {
            dt_reset(&t);
            t.NumPoints = (int8_t)lc[i][0];
            t.LastPointToScore = (int8_t)lc[i][1];
            snprintf(tag, sizeof(tag), "es lastcorner %d %d", lc[i][0],
                     lc[i][1]);
            pint(tag, drivetarget_get_last_corner_to_score(&t));
        }
    }

    // At 40 m/s the first corner, from the car, fits and the walk's one
    // corner, at point 3, does not. Cut at 1 the walk never starts (the
    // accessor's 0 is below s0), at 2 it starts and bails on point 3 being
    // past the cut, at 3 it stops just short of the bad corner and the
    // target scores, and at 4 or -1 (NumPoints - 2) the bad corner is
    // asked and refuses.
    {
        static const int8_t lasts[] = { 1, 2, 3, 4, -1 };
        char tag[64];

        for (i = 0; i < 5; i++) {
            WorldTimer = 515 + i;
            dt_corner(&t);
            t.LastPointToScore = lasts[i];
            car_set(&car, 0.0f, 0.0f, 40.0f, 5.0f, 0.0f, 0.0f, 0, 40.0f,
                    40.3112887f);
            snprintf(tag, sizeof(tag), "es corner last %d", (int)lasts[i]);
            pf(tag, drivetarget_estimate_score(&t, &car));
            snprintf(tag, sizeof(tag), "es corner last %d after",
                     (int)lasts[i]);
            pdt(tag, &t, 5);
        }
    }

    // The sweep with its last point hooked back: thirteen corners fit at
    // 25 m/s and the fourteenth, the hook, does not. Every cut up to 18
    // leaves the hook out and scores; 19 and -1 take it in.
    {
        static const int8_t lasts[] = { 2, 10, 18, 19, -1 };
        char tag[64];
        int k;

        for (k = 0; k < 5; k++) {
            WorldTimer = 520 + k;
            dt_reset(&t);
            for (i = 0; i < 20; i++)
                dt_point(&t, i, (float)i * 6.0f, (float)i * (float)i * 0.5f,
                         0.0f, 0.0f, 2, i, 1);
            dt_point(&t, 19, 90.0f, 162.0f, 0.0f, 0.0f, 2, 19, 1);
            t.NumPoints = 20;
            drivetarget_recalculate_length(&t);
            t.LastPointToScore = lasts[k];
            car_set(&car, 0.0f, 0.0f, 25.0f, 0.0f, 0.0f, 0.0f, 0, 25.0f,
                    25.0f);
            snprintf(tag, sizeof(tag), "es hook last %d", (int)lasts[k]);
            pf(tag, drivetarget_estimate_score(&t, &car));
        }
    }

    // Standing still with VelocityMagnitude zero: the fill writes zero
    // speeds, and the first corner divides by zero twice -- bNormalize2To's
    // length of zero and the _v half's 0/0 projection -- and fits on the
    // EE's FLT_MAX where IEEE's NaN would refuse it. Every later corner is
    // entered at zero and answered early, and the score is zero.
    WorldTimer = 525;
    dt_corner(&t);
    car_set(&car, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0, 0.0f, 0.0f);
    pf("es stopped corner", drivetarget_estimate_score(&t, &car));
    pdt("es stopped corner after", &t, 5);

    // The first corner's distance is half of |ForwardSpeed| and its entry
    // speed is VelocityMagnitude, cut at 3 so the first corner alone
    // decides: 40 fits, 4 is a tenth of the distance and does not, -40 is
    // 40's size, and 0 is a time inside the epsilon, a yes that writes
    // the entry speed.
    {
        static const float fwds[] = { 40.0f, 4.0f, -40.0f, 0.0f };
        char tag[64];

        for (i = 0; i < 4; i++) {
            WorldTimer = 526 + i;
            dt_corner(&t);
            t.LastPointToScore = 3;
            car_set(&car, 0.0f, 0.0f, 40.0f, 5.0f, 0.0f, 0.0f, 0, fwds[i],
                    40.3112887f);
            snprintf(tag, sizeof(tag), "es corner fwd %g", (double)fwds[i]);
            pf(tag, drivetarget_estimate_score(&t, &car));
        }
    }

    // Pass one stops on the last point: (6, 0) is 0.15 s out at 40 m/s and
    // (10, 20) 0.56 s. The first corner is asked only of a point with one
    // after it, so this one -- a corner far too hard at 40 -- is never
    // asked, and the target scores.
    WorldTimer = 530;
    dt_reset(&t);
    dt_point(&t, 0, 6.0f, 0.0f, 0.0f, 0.0f, 2, 0, 1);
    dt_point(&t, 1, 10.0f, 20.0f, 0.0f, 0.0f, 2, 1, 1);
    t.NumPoints = 2;
    drivetarget_recalculate_length(&t);
    car_set(&car, 0.0f, 0.0f, 40.0f, 0.0f, 0.0f, 0.0f, 0, 40.0f, 40.0f);
    pf("es last point corner", drivetarget_estimate_score(&t, &car));

    // The cut on its edge. At 20 m/s pass one stops on (20, 0), whose
    // corner is straight, and the walk starts at s0 = 2. The leg to (30, 0)
    // is 0.5 s, so nothing is skipped, and the corner there turns a right
    // angle in 10 m: 40 m/s/s against 30. A cut of 2 (a byte of 3, or -1
    // on four points) is not below s0, so the corner is asked and refuses;
    // a cut of 1 ends the walk first.
    {
        static const int8_t lasts[] = { -1, 3, 2 };
        char tag[64];

        for (i = 0; i < 3; i++) {
            WorldTimer = 531 + i;
            dt_reset(&t);
            dt_point(&t, 0, 6.0f, 0.0f, 0.0f, 0.0f, 2, 0, 1);
            dt_point(&t, 1, 20.0f, 0.0f, 0.0f, 0.0f, 2, 1, 1);
            dt_point(&t, 2, 30.0f, 0.0f, 0.0f, 0.0f, 2, 2, 1);
            dt_point(&t, 3, 30.0f, 20.0f, 0.0f, 0.0f, 2, 3, 1);
            t.NumPoints = 4;
            drivetarget_recalculate_length(&t);
            t.LastPointToScore = lasts[i];
            car_set(&car, 0.0f, 0.0f, 20.0f, 0.0f, 0.0f, 0.0f, 0, 20.0f,
                    20.0f);
            snprintf(tag, sizeof(tag), "es cut edge %d", (int)lasts[i]);
            pf(tag, drivetarget_estimate_score(&t, &car));
        }
    }

    // The inner walk measures from Points[outer - 1], not from the point
    // before. Points 6 m apart at 20 m/s are 0.3 s each, but (12, 0) to
    // (24, 0) is 0.6 s, so the walk stops on (24, 0) and asks its corner,
    // 33 m/s/s, which refuses. Measured point to point, the walk would run
    // off the end and ask nothing.
    WorldTimer = 534;
    dt_reset(&t);
    dt_point(&t, 0, 6.0f, 0.0f, 0.0f, 0.0f, 2, 0, 1);
    dt_point(&t, 1, 12.0f, 0.0f, 0.0f, 0.0f, 2, 1, 1);
    dt_point(&t, 2, 18.0f, 0.0f, 0.0f, 0.0f, 2, 2, 1);
    dt_point(&t, 3, 24.0f, 0.0f, 0.0f, 0.0f, 2, 3, 1);
    dt_point(&t, 4, 24.0f, 6.0f, 0.0f, 0.0f, 2, 4, 1);
    t.NumPoints = 5;
    drivetarget_recalculate_length(&t);
    car_set(&car, 0.0f, 0.0f, 20.0f, 0.0f, 0.0f, 0.0f, 0, 20.0f, 20.0f);
    pf("es inner from base", drivetarget_estimate_score(&t, &car));

    // A cut past the points, as a byte BuildDriveTargetAndCheckIt set and
    // something since shortened the target under: the walk goes on past
    // NumPoints - 2, asking about the slots beyond the last point. Slot 5
    // is left from a longer target, 40 m/s at (40, 34); the corner there,
    // into the zeroed slot 6, is far too hard, so a walk that reaches it
    // refuses. A cut of 5 or less never asks it, and scores as -1 does.
    {
        static const int8_t lasts[] = { 6, 10 };
        char tag[64];

        for (i = 0; i < 2; i++) {
            WorldTimer = 535 + i;
            dt_corner(&t);
            dt_point(&t, 5, 40.0f, 34.0f, 1.5f, 40.0f, 4, 16, 2);
            t.LastPointToScore = lasts[i];
            car_set(&car, 0.0f, 0.0f, 15.0f, 2.0f, 0.0f, 0.0f, 0, 15.0f,
                    15.13275f);
            snprintf(tag, sizeof(tag), "es stale cut %d", (int)lasts[i]);
            pf(tag, drivetarget_estimate_score(&t, &car));
        }
    }
}

// ------------------------------------------------------- the two predictors

static void s_fill(void)
{
    DriveTarget t;
    Car car;

    routes_init();
    WorldTimer = 600;

    // Acceleration past three quarters of the speed -- 16 sideways
    // against 20 forward, whose three quarters is 15 -- so the
    // straight-line predictor takes over and leaves exactly one point.
    dt_straight(&t);
    car_set(&car, 0.0f, 0.0f, 20.0f, 0.0f, 0.0f, 16.0f, 0, 20.0f, 20.0f);
    drivetarget_fill_with_current_acceleration(&t, &car);
    pdt("fi straight", &t, 2);

    // Stationary but accelerating, which is past three quarters of no
    // speed at all, so the straight line comes off State.Angle.
    WorldTimer = 601;
    dt_straight(&t);
    car_set(&car, 5.0f, 6.0f, 0.0f, 0.0f, 0.5f, 0.0f, 8192, 0.0f, 0.0f);
    drivetarget_fill_with_current_acceleration(&t, &car);
    pdt("fi angle", &t, 2);

    // A real integration: cornering acceleration of 5.39 at a modest
    // speed of 8, under the bar of 6. The eighteenth step takes the
    // walk past the 20 m look-ahead.
    WorldTimer = 602;
    dt_straight(&t);
    car_set(&car, 0.0f, 0.0f, 8.0f, 0.0f, 2.0f, 5.0f, 0, 8.0f, 8.0f);
    drivetarget_fill_with_current_acceleration(&t, &car);
    pdt("fi integrate", &t, 20);

    // Braking at 2.8 against a speed of 4, under the bar of 3, for long
    // enough to turn the velocity round. The fifteenth step doubles
    // back, the checked AddPointToTarget refuses it, and the dot test
    // ends the walk with fourteen points.
    WorldTimer = 603;
    dt_straight(&t);
    car_set(&car, 0.0f, 0.0f, 4.0f, 0.0f, -2.8f, 0.0f, 0, 4.0f, 4.0f);
    drivetarget_fill_with_current_acceleration(&t, &car);
    pdt("fi brake", &t, 16);

    // Enough acceleration, under the bar, and little enough distance
    // per step that the twenty-point wall is what stops it.
    WorldTimer = 604;
    dt_straight(&t);
    car_set(&car, 0.0f, 0.0f, 5.0f, 0.0f, 1.0f, 3.0f, 0, 5.0f, 5.0f);
    drivetarget_fill_with_current_acceleration(&t, &car);
    pdt("fi full", &t, 20);

    // Three quarters exactly: a speed of 8 against an acceleration of
    // 6. The test is strict, so this integrates, sixteen points to the
    // look-ahead.
    WorldTimer = 605;
    dt_straight(&t);
    car_set(&car, 0.0f, 0.0f, 8.0f, 0.0f, 6.0f, 0.0f, 0, 8.0f, 8.0f);
    drivetarget_fill_with_current_acceleration(&t, &car);
    pdt("fi ratio", &t, 17);

    // Braking across the lane. The forward velocity turns over at the
    // fourteenth step, but the constant sideways drift keeps every leg
    // within a right angle of the one before, so AddPointToTarget
    // takes each point. It is the dot against the car's own velocity,
    // re-read every pass, that ends the walk a step later, with the
    // fifteenth point in.
    WorldTimer = 606;
    dt_straight(&t);
    car_set(&car, 0.0f, 0.0f, 2.5f, 0.25f, -1.8f, 0.0f, 0, 2.5f, 2.5125f);
    drivetarget_fill_with_current_acceleration(&t, &car);
    pdt("fi turnback", &t, 16);

    // Nine steps of a car at 20 m/s gaining 10 m/s^2 cover 22.5 m
    // exactly, and a VelocityMagnitude of 11.25 makes the look-ahead
    // 22.5 m exactly too. The distance test is strict, so the ninth
    // point is the last.
    WorldTimer = 607;
    dt_straight(&t);
    car_set(&car, 0.0f, 0.0f, 20.0f, 0.0f, 10.0f, 0.0f, 0, 20.0f, 11.25f);
    drivetarget_fill_with_current_acceleration(&t, &car);
    pdt("fi look eq", &t, 11);

    // No speed and no acceleration. Nothing is past three quarters of
    // nothing, so this integrates: every step lands on the car, the
    // zero-length legs pass the strict doubling-back test, the dot is
    // 0 and the distance never grows. The wall stops it at twenty.
    WorldTimer = 608;
    dt_straight(&t);
    car_set(&car, 5.0f, 6.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0, 0.0f, 0.0f);
    drivetarget_fill_with_current_acceleration(&t, &car);
    pdt("fi still", &t, 20);

    // Just past the bar: 6.01 against a speed of 8 is
    // the straight line again.
    WorldTimer = 609;
    dt_straight(&t);
    car_set(&car, 0.0f, 0.0f, 8.0f, 0.0f, 6.01f, 0.0f, 0, 8.0f, 8.0f);
    drivetarget_fill_with_current_acceleration(&t, &car);
    pdt("fi ratio over", &t, 2);
}

static void s_blend(void)
{
    DriveTarget t;
    Car car;
    int player;

    routes_init();
    WorldTimer = 700;

    // A car with a player on it is left alone.
    dt_straight(&t);
    car_set(&car, 0.0f, 0.0f, 20.0f, 0.0f, 1.0f, 3.0f, 0, 20.0f, 20.0f);
    // car.h's pPlayer is a `Player *`; the stand-in's was a `void *`.
    // Only its non-nullness is under test, so the cast is the whole fix.
    car.pPlayer = (Player *)&player;
    drivetarget_blend_with_current_acceleration(&t, &car);
    pdt("bl player", &t, 3);

    // Once per frame: the second call inside the same tick returns.
    WorldTimer = 701;
    dt_straight(&t);
    car.pPlayer = 0;
    drivetarget_blend_with_current_acceleration(&t, &car);
    pdt("bl first", &t, 5);
    drivetarget_blend_with_current_acceleration(&t, &car);
    pdt("bl second", &t, 5);

    // Under 1 m/s the stamp is still taken but nothing is blended.
    WorldTimer = 702;
    dt_straight(&t);
    car_set(&car, 0.0f, 0.0f, 0.5f, 0.0f, 1.0f, 3.0f, 0, 0.5f, 0.5f);
    drivetarget_blend_with_current_acceleration(&t, &car);
    pdt("bl slow", &t, 3);

    // A slow car with a long path: the 0.75s window closes before the
    // points run out.
    WorldTimer = 703;
    dt_straight(&t);
    car_set(&car, 0.0f, 0.0f, 12.0f, 0.0f, 2.0f, 6.0f, 0, 12.0f, 12.0f);
    drivetarget_blend_with_current_acceleration(&t, &car);
    pdt("bl window", &t, 5);

    // A fast car on the corner: the points run out before the window does.
    WorldTimer = 704;
    dt_corner(&t);
    car_set(&car, 0.0f, 0.0f, 40.0f, 5.0f, 1.0f, -4.0f, 0, 40.0f, 40.3113f);
    drivetarget_blend_with_current_acceleration(&t, &car);
    pdt("bl fast", &t, 5);

    // Starting from the middle, so the first leg is measured from the car
    // and the rest from the previous point.
    WorldTimer = 705;
    dt_straight(&t);
    car_set(&car, 22.0f, 0.0f, 20.0f, 0.0f, 0.5f, 2.0f, 0, 20.0f, 20.0f);
    drivetarget_blend_with_current_acceleration(&t, &car);
    pdt("bl mid", &t, 5);

    // Legs of 5 m and then 2.5 m at 10 m/s: half a second and a quarter,
    // which is the 0.75 s window exactly. The test is strict, so the second
    // point is the last one dragged.
    //
    // The z of 3 is what makes that visible. On the pass that lands on the
    // boundary the blend is 0.75 * 1.33333337, which clamps to 1, so a
    // further pass would leave x and y exactly where they are. SetPoint3
    // writes z as 0 whatever the blend is, though, and Length follows it --
    // so with a z here an inclusive window drags a third point and says so,
    // and without one it drags a third point in silence.
    WorldTimer = 706;
    dt_reset(&t);
    dt_point(&t, 0, 5.0f, 0.0f, 3.0f, 0.0f, 2, 0, 1);
    dt_point(&t, 1, 7.5f, 0.0f, 3.0f, 0.0f, 2, 1, 1);
    dt_point(&t, 2, 10.0f, 0.0f, 3.0f, 0.0f, 2, 2, 1);
    dt_point(&t, 3, 12.5f, 0.0f, 3.0f, 0.0f, 2, 3, 1);
    dt_point(&t, 4, 15.0f, 0.0f, 3.0f, 0.0f, 2, 4, 1);
    t.NumPoints = 5;
    drivetarget_recalculate_length(&t);
    car_set(&car, 0.0f, 0.0f, 10.0f, 0.0f, 0.0f, 0.0f, 0, 10.0f, 10.0f);
    drivetarget_blend_with_current_acceleration(&t, &car);
    pdt("bl window eq", &t, 5);
}

// ------------------------------------------------------------------- debug

static void s_dump(void)
{
    DriveTarget t;
    Car car;

    routes_init();
    WorldTimer = 800;

    // Dump prints nothing in the shipped image. What it still does is ask
    // the CarState for its transform, which builds RelCoordMatrix and sets
    // MatrixValid -- so that flag is the only way to see the guard from
    // outside, and it is enough to see it.
    dt_straight(&t);
    car_set(&car, 1.0f, 2.0f, 20.0f, 3.0f, 0.0f, 0.0f, 0, 20.0f, 20.24846f);
    car.DriverNumber = -1;
    drivetarget_dump(&t, &car, 1, 0);
    pint("du guarded", (int)car.State.MatrixValid);

    // With the camera default off and the driver number matching, it runs.
    CameraFollowDefaultCar = 0;
    drivetarget_dump(&t, &car, 1, 0);
    pint("du matched", (int)car.State.MatrixValid);

    car.State.MatrixValid = 0;
    car.DriverNumber = 7;
    drivetarget_dump(&t, &car, 1, 0);
    pint("du wrongcar", (int)car.State.MatrixValid);

    // No guard at all.
    drivetarget_dump(&t, &car, 0, 0);
    pint("du unguarded", (int)car.State.MatrixValid);

    // An empty target never reaches the transform.
    car.State.MatrixValid = 0;
    dt_reset(&t);
    drivetarget_dump(&t, &car, 0, 0);
    pint("du empty", (int)car.State.MatrixValid);

    // A null car takes the other arm of the loop and touches nothing.
    dt_straight(&t);
    drivetarget_dump(&t, 0, 0, 0);
    pdt("du nocar", &t, 1);

    CameraFollowDefaultCar = 1;
}

// ------------------------------------------------- DriveTarget's free functions
//
// Three of these are in DriveTarget.obj's call graph and the fourth,
// DrivingLocation::IsClear, is the two instructions the AddPointToTarget
// overloads branch on. Everywhere else in this file they are reached
// sideways, which is how eight mutations to them lived through a pass that
// every other line of the class survived.

static void s_free(void)
{
    DriveTarget t;
    Car car;
    DrivingLocation loc;
    bVector2 p;

    routes_init();

    // IsClear reads pRoute and nothing else, so the two pointers are made
    // to disagree in both directions -- which is the only way to say so.
    loc.pRoute = 0;          loc.pRoutePoint = 0;
    loc.DrivingLine = 1;
    pint("fn clear 00", drivinglocation_is_clear(&loc));
    loc.pRoutePoint = &gRouteB.TrackRoutePointTable[3];
    pint("fn clear 01", drivinglocation_is_clear(&loc));
    loc.pRoute = &gRouteB;   loc.pRoutePoint = 0;
    pint("fn clear 10", drivinglocation_is_clear(&loc));
    loc.pRoutePoint = &gRouteB.TrackRoutePointTable[3];
    pint("fn clear 11", drivinglocation_is_clear(&loc));

    // IsPointAheadOfCar. A point straight ahead gives a dot of exactly
    // 1.0, which the strict test refuses at a threshold of 1.0 and takes
    // at anything below it.
    car_set(&car, 0.0f, 0.0f, 12.0f, 0.0f, 0.0f, 0.0f, 0, 12.0f, 12.0f);
    p.x = 5.0f;  p.y = 0.0f;
    pint("fn ahead dot1 t1",   ai_is_point_ahead_of_car(&p, &car, 1.0f));
    pint("fn ahead dot1 t0.9", ai_is_point_ahead_of_car(&p, &car, 0.9f));

    // The delta is normalised as well as the velocity, so distance cannot
    // change the answer: (3,4) and (30,40) are one direction. A threshold
    // of 5.0 is above every possible dot and below the raw dot of the far
    // one, so the pair says the normalise happened.
    p.x = 3.0f;  p.y = 4.0f;
    pint("fn ahead near 0.0", ai_is_point_ahead_of_car(&p, &car, 0.0f));
    pint("fn ahead near 5.0", ai_is_point_ahead_of_car(&p, &car, 5.0f));
    p.x = 30.0f; p.y = 40.0f;
    pint("fn ahead far 0.0",  ai_is_point_ahead_of_car(&p, &car, 0.0f));
    pint("fn ahead far 5.0",  ai_is_point_ahead_of_car(&p, &car, 5.0f));
    p.x = -3.0f; p.y = 4.0f;
    pint("fn ahead behind",   ai_is_point_ahead_of_car(&p, &car, 0.0f));

    // CalculateLookAheadDistance reads VelocityMagnitude and not
    // ForwardSpeed, and the twenty-metre floor is a max rather than a
    // clamp on the speed. Every other car in this file is built with the
    // same number in both fields; this one is not.
    car.State.VelocityMagnitude = 12.0f;   // 24 m, over the floor
    car.State.ForwardSpeed      = 40.0f;
    pf("fn look 12", ai_calculate_look_ahead_distance(&car));
    car.State.VelocityMagnitude = 5.0f;    // 10 m, under it
    pf("fn look 5",  ai_calculate_look_ahead_distance(&car));
    car.State.VelocityMagnitude = 10.0f;   // exactly the floor
    pf("fn look 10", ai_calculate_look_ahead_distance(&car));

    // StraightLinePredict clears the target first, so a list of five comes
    // back as one. Under 1 m/s the heading is the body angle rather than
    // the velocity, and 0x1555 is thirty degrees -- not 0x2000, where sine
    // and cosine are the same number and a swap would not show.
    dt_straight(&t);
    car_set(&car, 1.0f, 2.0f, 0.2f, 0.1f, 0.0f, 0.0f, 0x1555,
            0.22360680f, 0.5f);
    ai_straight_line_predict(&car, &t);
    pdt("fn slp slow", &t, 2);

    // Above it the velocity is used, and all four lanes go through the
    // normalise -- so z and the lane CarState calls pad ride along, the
    // pad divided by |v.xyz| like the other three.
    dt_straight(&t);
    car_set(&car, 1.0f, 2.0f, 0.9f, 1.2f, 0.0f, 0.0f, 0x1555, 1.5f, 1.5f);
    car.State.Velocity.z = 0.3f;
    car.State.Velocity.pad = 0.7f;
    car.State.Position.z = 4.0f;
    car.State.Position.pad = 8.0f;
    ai_straight_line_predict(&car, &t);
    pdt("fn slp fast", &t, 2);

    // The gate is strict, so exactly 1.0 takes the velocity arm too.
    dt_straight(&t);
    car.State.VelocityMagnitude = 1.0f;
    ai_straight_line_predict(&car, &t);
    pdt("fn slp at1", &t, 2);

    // A 3-4-5 velocity at 1.5 m/s: 0.9 * (1 / 1.5) and 0.9 / 1.5 round
    // apart, so this is where the one reciprocal vrsqrt makes shows.
    dt_straight(&t);
    car_set(&car, 1.0f, 2.0f, 0.9f, 1.2f, 0.0f, 0.0f, 0x1555, 1.5f, 1.5f);
    car.State.Velocity.pad = 0.7f;
    car.State.Position.z = 4.0f;
    car.State.Position.pad = 8.0f;
    ai_straight_line_predict(&car, &t);
    pdt("fn slp divide", &t, 2);

    // Rolling backwards with the body still pointing forwards: the heading
    // comes from the angle and points one way while the velocity points
    // the other. That is the only arrangement in which the two trailing
    // arguments of the AddPointToTarget call could matter -- and they are
    // 0 and NULL, so the point lands anyway.
    dt_reset(&t);
    car_set(&car, 0.0f, 0.0f, -0.2f, 0.0f, 0.0f, 0.0f, 0, -0.2f, 0.2f);
    ai_straight_line_predict(&car, &t);
    pdt("fn slp reversing", &t, 2);
}

// ------------------------------------------------------------------ frames

static void s_frames(void)
{
    DriveTarget t;
    Car car;
    int f;

    routes_init();
    dt_straight(&t);
    car_set(&car, 0.0f, 0.0f, 18.0f, 1.0f, 0.75f, 2.5f, 0, 18.0f, 18.02776f);

    // Ten ticks of what the AI actually does with one of these: blend the
    // current acceleration in, clear back to the look-ahead distance, score
    // what is left. The car is walked forward by hand between ticks.
    for (f = 0; f < 10; f++) {
        WorldTimer = 900 + f;
        drivetarget_blend_with_current_acceleration(&t, &car);
        drivetarget_clear(&t, &car, 30.0f);
        pf("fr score", drivetarget_estimate_score(&t, &car));
        pdt("fr", &t, 4);

        car.State.Position.x = car.State.Position.x + 1.8f;
        car.State.Position.y = car.State.Position.y + 0.1f;
        car.State.Velocity.x = car.State.Velocity.x + 0.075f;
        car.State.Velocity.y = car.State.Velocity.y + 0.25f;
    }
}

// -------------------------------------------------------------------- main

int main(void)
{
    s_layout();
    s_constants();
    s_ctor();
    s_get_angle();
    s_calculate_time();
    s_recalculate_length();
    s_set_point();
    s_shift_right();
    s_shift_left();
    s_route_point();
    s_first_point();
    s_add_point();
    s_interpolate();
    s_clear();
    s_resample();
    s_max_speed();
    s_estimate_score();
    s_fill();
    s_blend();
    s_dump();
    s_free();
    s_frames();
    return 0;
}
