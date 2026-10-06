// nearbycar -- see nearbycar.h and docs/formats/ai-driving-info.md.
#include "nearbycar.h"

#include <math.h>
#include <string.h>

#include "bmath.h"
#include "carinfo.h"
#include "drivetarget.h"   // ai_calculate_look_ahead_distance, CameraFollow...
#include "emath.h"
#include "rigidbody.h"     // RIGIDBODY_GRAVITY
#include "table.h"
#include "trackpath.h"
#include "world.h"

float TrafficDriverLookaheadFactor = 3.0f;
float AIActionPassMaxTimeAheadToMakeAttempt = 3.0f;
int32_t HighlightDrivingLineInRouteNumber = -1;
int32_t HighlightDrivingLineNumber = -1;

BeltMoverGravityFn gBeltMoverGravityFn;

// BeltMover's fBeltAccelCoef (gp-16600, 0x00331818), which
// CalculateMaxAcceleration scales the acceleration by in either arm.
static float fBeltAccelCoef = 1.0f;

// CalculateMaxAcceleration's miles an hour to metres a second, an anonymous
// `.lit4` at gp-28516: 0x3ee4e0c2.
#define NEARBYCAR_MPH_TO_MS 0.447027266f

// A point's index in `r`'s table, the image's way (airoute.c's point_index).
static int32_t point_index(const TrackRoute *r, const TrackRoutePoint *p)
{
    uint32_t d = (uint32_t)((uintptr_t)p
                            - (uintptr_t)r->TrackRoutePointTable);

    return (int32_t)(d * 0xb6db6db7u) >> 4;
}

// ---------------------------------------------------------- NearbyCarList

void nearbycarlist_build_array(NearbyCarList *l, DrivingLocation *loc,
                               float unused)
{
    // 0x00193898.
    Car *me = l->MyCar;
    NearbyCar copy[NEARBYCARLIST_MAX];
    NearbyCar *order[NEARBYCARLIST_MAX];
    WorldList *head;
    Car *c;
    bVector3 mn, mx;
    float myDat, look;
    int32_t n = 0;
    int32_t i, j, k;

    (void)unused;
    if (me == NULL || loc == NULL)
        return;

    myDat = me->TheTrackPathCoordinate.DistanceAroundTrack;
    memset(l->Array, 0, sizeof l->Array);

    // CalculateMaxAcceleration(me, State.VelocityMagnitude) comes next in
    // the image, and its answer goes to CanICatchThisCar, which never reads
    // it (see there). It reads and writes nothing else, so it is left out.
    look = ai_calculate_look_ahead_distance(me);
    if (me->TheControlMode == TRAFFIC_CONTROL)
        look *= TrafficDriverLookaheadFactor;

    head = &pCurrentWorld->CarList;
    for (c = (Car *)head->next; c != (Car *)head; c = (Car *)c->Link.next) {
        NearbyCar *nc;
        bVector2 local;
        bVector3 rel;
        float dist, round;

        // A full list still walks the rest, doing nothing.
        if (n >= NEARBYCARLIST_MAX)
            continue;

        // `xori v0,v0,1 ; and v0,v0,v1`: IsPoofed's word flipped in bit 0,
        // anded with RenderingEnabled's sign-extended byte.
        if (((car_is_poofed(c) ^ 1) & (int32_t)c->RenderingEnabled) == 0)
            continue;

        nc = &l->Array[n];
        car_world_to_car(me, &local, (const bVector2 *)&c->State.Position);

        // All four lanes; only x and y are kept.
        rel.x = c->State.Velocity.x - me->State.Velocity.x;
        rel.y = c->State.Velocity.y - me->State.Velocity.y;
        rel.z = c->State.Velocity.z - me->State.Velocity.z;
        rel.pad = c->State.Velocity.pad - me->State.Velocity.pad;

        dist = sqrtf(local.x * local.x + local.y * local.y);
        round = fabsf(trackpath_compare_distances(
            &TheTrackPathManager,
            c->TheTrackPathCoordinate.DistanceAroundTrack, myDat));

        // Stored before either test, so a car not kept leaves them in the
        // entry the next one takes, or past the count when it is the last.
        nc->Position = local;
        nc->Velocity.x = rel.x;
        nc->Velocity.y = rel.y;
        nc->TheCar = c;

        if (!(dist <= look) && !ai_can_i_catch_this_car(nc, me, 0.0f, 0))
            continue;
        if (!(round <= look * 3.0f))
            continue;
        n++;

        {
            // The velocity turned to the car's heading: Z by a quarter
            // turn less bATan of its velocity.
            bMatrix4 m;
            float hl, hd, cs, c2, s2;
            int32_t ang = bATan(me->State.Velocity.x, me->State.Velocity.y);

            eIdentity(&m);
            eRotateZ(&m, &m, (uint16_t)(16384 - ang));
            eMulVector3(&rel, &m, &rel);
            nc->Velocity.x = rel.x;
            nc->Velocity.y = rel.y;

            car_get_car_space_bounding_box(c, &mn, &mx);
            hl = (mx.y - mn.y) * 0.5f;
            hd = (mx.x - mn.x) * 0.5f;
            cs = bCosBam((uint16_t)(c->State.Angle - me->State.Angle));
            c2 = cs * cs;
            s2 = 1.0f - c2;
            nc->ApparentHalfSizeL = c2 * hl + s2 * hd;
            nc->ApparentHalfSizeD = c2 * hd + s2 * hl;
        }
    }
    l->NumCarsInArray = n;

    // The sort: on a copy of the whole array, through pointers, then the
    // first n copied back. `c.lt.s` -- a NaN never swaps.
    memcpy(copy, l->Array, sizeof copy);
    for (i = 0; i < n; i++)
        order[i] = &copy[i];
    for (i = 0; i < n; i++) {
        for (j = 0; j < n - 1; j++) {
            if (order[j]->Position.y < order[j + 1]->Position.y) {
                NearbyCar *t = order[j];
                order[j] = order[j + 1];
                order[j + 1] = t;
            }
        }
    }
    for (k = 0; k < n; k++)
        l->Array[k] = *order[k];

    car_get_car_space_bounding_box(me, &mn, &mx);
    l->MyCar = me;
    l->MyHalfSizeL = mx.y;
    l->MyHalfSizeD = mx.x;
}

void nearbycarlist_clear_array(NearbyCarList *l)
{
    // 0x001940c8.
    l->MyHalfSizeD = 0.0f;
    l->NumCarsInArray = 0;
    l->MyHalfSizeL = 0.0f;
}

int32_t nearbycarlist_get_cars_index_in_array(const NearbyCarList *l,
                                              const Car *c)
{
    // 0x00193d90.
    int32_t i;

    for (i = 0; i < l->NumCarsInArray; i++)
        if (l->Array[i].TheCar == c)
            return i;
    return -1;
}

NearbyCar *nearbycarlist_get_nearby_car(NearbyCarList *l, const Car *c)
{
    // 0x00193dd8.
    int32_t i = nearbycarlist_get_cars_index_in_array(l, c);

    return i == -1 ? NULL : &l->Array[i];
}

NearbyCar *nearbycarlist_get_car_ahead(NearbyCarList *l, const Car *c)
{
    // 0x00193e20. `blez`: the first car, or one not there, has none.
    int32_t i = nearbycarlist_get_cars_index_in_array(l, c);

    return i <= 0 ? NULL : &l->Array[i - 1];
}

// ------------------------------------------------------ DrivingInformation

void drivinginformation_clear(DrivingInformation *d)
{
    // 0x00193e68.
    nearbycarlist_clear_array(&d->MyNearbyCarList);
    drivinglocation_clear(&d->MyDrivingLocation);
    d->MyDrivingChoice.Type = CHOICE_NONE;
    d->MyDrivingChoice.pCar = NULL;
    d->MyDrivingChoice.UseExtraLateralDistance = 0;
}

// ---------------------------------------------------- the free functions

float ai_calculate_max_acceleration(Car *car, float speed)
{
    // 0x001cce50.
    CarTypeInfo *ti = car->pCarTypeInfo;
    float v = speed / car->State.BoostFactor;
    float accel = table_get_value(get_acceleration_table(car->pRideInfo->Type),
                                  v);
    float drag = ((1.0f - car->DraftFactor) * ti->Aero.Drag) * (v * v);
    float dragAccel, grade;

    // `c.le.s`, then `c.lt.s` and the move in the likely delay slot.
    if (ti->Control.SpeedLimiter * NEARBYCAR_MPH_TO_MS <= v && drag < accel)
        accel = drag;
    dragAccel = drag / ti->Body.Mass;

    if (car->TheMovementMode == BELT_MOVEMENT) {
        grade = gBeltMoverGravityFn(car->pCarMover);
        accel *= fBeltAccelCoef;
    } else {
        // An inline VU0 normalise of the body's x axis, all four lanes by
        // `vrsqrt`'s quotient, of which z is kept.
        const bVector4 *x = &car->State.BodyMatrix.v0;
        float q = 1.0f / sqrtf((x->x * x->x + x->y * x->y) + x->z * x->z);

        accel *= fBeltAccelCoef;
        grade = -RIGIDBODY_GRAVITY * (x->z * q);
    }
    return (accel - dragAccel) + grade;
}

float ai_calculate_max_deceleration(Car *car, float speed)
{
    // 0x001ccf78. Retail's order: both halves before the weight, and the
    // downforce term first in the sum.
    CarTypeInfo *ti = car->pCarTypeInfo;
    float down = (ti->Aero.FrontDownforce + ti->Aero.RearDownforce) * 0.5f;
    float mu = (ti->Tires[1].StaticFrictionCoefficient
                + ti->Tires[0].StaticFrictionCoefficient) * 0.5f;
    float weight = RIGIDBODY_GRAVITY * ti->Body.Mass;

    return -(((fabsf(speed) * down + weight) * mu) / ti->Body.Mass);
}

int ai_can_i_catch_this_car(NearbyCar *nc, Car *car, float maxAccel,
                            int flag)
{
    // 0x001ccfd8. The image also works out |Position.x| when Position.y is
    // between -ApparentHalfSizeD and three of it, and never uses it; and
    // when maxAccel is below 0 it calls CalculateMaxAcceleration and drops
    // the answer. Neither is here, nor is `flag` read.
    float mine = car_get_forward_acceleration(car);
    float dist, closing, diff, t;
    Car *o = nc->TheCar;

    (void)maxAccel;
    (void)flag;
    dist = sqrtf(nc->Position.x * nc->Position.x
                 + nc->Position.y * nc->Position.y);
    closing = sqrtf(nc->Velocity.x * nc->Velocity.x
                    + nc->Velocity.y * nc->Velocity.y);

    // The two bodies' x axes, in x and y: facing the same way or not.
    if (0.0f < car->State.BodyMatrix.v0.x * o->State.BodyMatrix.v0.x
               + car->State.BodyMatrix.v0.y * o->State.BodyMatrix.v0.y)
        diff = mine - car_get_forward_acceleration(o);
    else
        diff = mine + car_get_forward_acceleration(o);

    t = AIActionPassMaxTimeAheadToMakeAttempt;
    return dist < closing * t + (diff * t) * (t * 0.5f);
}

int ai_do_we_care_about_this_car(const NearbyCar *nc,
                                 const NearbyCarList *l)
{
    // 0x001ccde8.
    float bias = 0.0f;

    if (nc == NULL || nc->TheCar == l->MyCar)
        return 0;
    if (nc->TheCar->pPlayer != NULL)
        bias = -0.5f;
    return -((nc->ApparentHalfSizeD + l->MyHalfSizeD) + bias)
           < nc->Position.y;
}

float ai_get_current_curvature_of_driving_line(DrivingLocation *loc)
{
    // 0x001ccbc0.
    TrackRoute *r;
    int32_t line, idx;
    bVector2 a, b, c, d1, d2;
    float lat, cx, cy, cz, len;

    if (drivinglocation_is_clear(loc))
        return 0.0f;
    r = loc->pRoute;
    line = loc->DrivingLine;
    // IsClear again, which can only say what it said.
    idx = point_index(r, loc->pRoutePoint);
    if (r->NumPoints - idx < 13)
        return 0.0f;

    // Each point's place on the line: Q8, through a `<< 8` and 2^-16.
    lat = (float)(r->TrackRoutePointTable[idx].DrivingLineOffsets[line] * 256)
          * (1.0f / 65536.0f);
    trpoint_get_position2(&r->TrackRoutePointTable[idx], &a, 0.0f, lat);
    lat = (float)(r->TrackRoutePointTable[idx + 6].DrivingLineOffsets[line]
                  * 256) * (1.0f / 65536.0f);
    trpoint_get_position2(&r->TrackRoutePointTable[idx + 6], &b, 0.0f, lat);
    lat = (float)(r->TrackRoutePointTable[idx + 12].DrivingLineOffsets[line]
                  * 256) * (1.0f / 65536.0f);
    trpoint_get_position2(&r->TrackRoutePointTable[idx + 12], &c, 0.0f, lat);

    d1.x = a.x - b.x;
    d1.y = a.y - b.y;
    d2.x = b.x - c.x;
    d2.y = b.y - c.y;
    bNormalize2(&d1, &d1);
    bNormalize2(&d2, &d2);

    // `vopmula`/`vopmsub`: d1 x d2 with both z 0, and its length as
    // (x^2 + y^2) + z^2.
    cx = d1.y * 0.0f - d2.y * 0.0f;
    cy = 0.0f * d2.x - 0.0f * d1.x;
    cz = d1.x * d2.y - d2.x * d1.y;
    len = sqrtf((cx * cx + cy * cy) + cz * cz);

    // `c.le.s 0,z` and the negate in the likely delay slot.
    return 0.0f <= cz ? -len : len;
}

void ai_highlight_driving_line(DrivingLocation *loc, int32_t carIndex)
{
    // 0x001cb450.
    if (CameraFollowThisCarInstead != carIndex)
        return;
    HighlightDrivingLineInRouteNumber =
        drivinglocation_is_clear(loc) ? -1 : loc->pRoute->RouteNumber;
    HighlightDrivingLineNumber = loc->DrivingLine;
}
