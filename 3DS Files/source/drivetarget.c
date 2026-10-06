// drivetarget -- DriveTarget.obj (0x002086f8 .. 0x0020a840), plus the copy
// constructor at 0x001da210 and the three free functions the class calls.
//
// Retail's (step 11b-1): DriveTarget.obj is retail's 0x0021b918 ..
// 0x0021dbb8. Retail added a byte at 516, LastPointToScore, which Clear
// sets and the copy constructor copies, and three methods: the accessor
// EstimateScore reads it through, and the two halves of a CalculateMaxSpeed
// it split so that EstimateScore's first corner could start from the car's
// velocity. The other changed functions moved CarState's fields and
// nothing else. The addresses below are the demo's where nothing changed.
//
// Written from the listing. Every float expression keeps the image's
// association and its divides: `(b + c) * 0.5f` is not `b * 0.5f + c * 0.5f`
// once the sum rounds, and `x * (1.0f / y)` is not `x / y`. The three-lane
// VU0 sums are spelled `(x * x + y * y) + z * z` for the same reason.
//
// Two shapes recur and are worth naming once.
//
// **NumPoints is re-read from the record inside almost every loop.** The
// image reloads it with `lb` on each pass rather than keeping it in a
// register, and where a call in the body can change it -- AddPointToTarget
// does, SetPoint does not -- that is the difference between a loop that
// stops and one that does not. The reloads are kept.
//
// **A stack bVector3 whose w is never written.** Five places build one,
// fill x, y and z, and hand it to something that copies all sixteen bytes
// with lqc2/sqc2. Points[i].pad ends up holding whatever the stack held.
//
// This is the one place the port does not follow the image, and it is
// deliberate: reading an uninitialised automatic is undefined behaviour in
// C, so those temporaries get a `pad` of 0.0f instead. Nothing on the disc
// can depend on the value either -- it is a different number on every call
// -- so the divergence costs a behaviour no caller could have had. Every
// site is marked STACK-W below.
//
// See drivetarget.h for the layout and docs/formats/car-drive-target.md
// for the write-up.

#include "drivetarget.h"

#include <math.h>
#include <string.h>

#include "bmath.h"
#include "eefpu.h"
#include "engine.h"   /* WorldTimer, gp-20224 */

// ---------------------------------------------------------- the constants
//
// DriveTarget.obj's .lit4 is the demo's 0x00321fa8, 0x28 long, and
// retail's 0x0032ee84, 0x2c long: anonymous floats, listed here in address
// order with the gp offsets the two listings quote (demo, then retail),
// because that is the only name they have. Retail's one more is the 0.001
// of the half of CalculateMaxSpeed it split out; every value is the demo's.
#define K_CLEAR_EPS        0.00100000005f  // gp-27720 / -27244, Clear
#define K_AHEAD_DOT        0.342000008f    // gp-27716 / -27240, cos 70
#define K_SCORE_T1         0.400000006f    // gp-27712 / -27236, EstimateScore
#define K_SCORE_T2         0.400000006f    // gp-27708 / -27232, EstimateScore
#define K_SCORE_T3         0.400000006f    // gp-27704 / -27228, EstimateScore
#define K_MAXSPEED_EPS     0.00100000005f  // gp-27700 / -27224, CalculateMaxSpeed
#define K_MAXSPEED_V_EPS   0.00100000005f  //   retail -27220, its _v half
#define K_TIME_EPS         0.00100000005f  // gp-27696 / -27216, CalculateTime
#define K_NO_TIME          9999999.0f      // gp-27692 / -27212, CalculateTime
#define K_PREDICT_DT       0.100000001f    // gp-27688 / -27208, the step
#define K_BLEND_SCALE      1.33333337f     // gp-27684 / -27204, 1 / 0.75

// Inline literals rather than pooled ones, so they are `lui at,...` in the
// listing instead of a gp load.
#define K_FAST_CAR         30.0f   // 0x41f00000, GetFirstPoint's speed gate
#define K_MAX_LATERAL      30.0f   // 0x41f00000, and the lateral grip limit
#define K_ACC_DOMINATES    0.75f   // 0x3f400000, FillWithCurrentAcceleration
#define K_BLEND_WINDOW     0.75f   // 0x3f400000, BlendWithCurrentAcceleration
#define K_FIRST_CORNER     0.5f    // 0x3f000000, retail EstimateScore's factor

float AIDriverSecondsToLookAhead = 2.0f;
float AIDriverDefaultLookAhead   = 20.0f;
float DriveTargetMinDistanceToPoint        = 4.0f;
float DriveTargetMinDistanceToPointSquared = 0.0f;  // .sbss; see below
int32_t CameraFollowDefaultCar     = 1;
int32_t CameraFollowThisCarInstead = -1;

void drivetarget_static_init(void)
{
    // 0x0020ab48, four instructions: load gp-16784, multiply it by itself,
    // store gp-14492. The square is in .sbss precisely because it is not a
    // constant the linker could fold -- it is computed at start-up.
    DriveTargetMinDistanceToPointSquared =
        DriveTargetMinDistanceToPoint * DriveTargetMinDistanceToPoint;
}

// ------------------------------------------------------------- small helpers

// The VU0 three-lane length: vmul.xyz, vaddy.x, vaddz.x, sqrt.s. The sum
// associates left, so it is (x*x + y*y) + z*z and not any other grouping.
static float dt_len3(float x, float y, float z)
{
    return sqrtf((x * x + y * y) + z * z);
}

// The two-lane one, which the FPU does directly: mul, mul, add, sqrt.
static float dt_len2(float x, float y)
{
    return sqrtf(x * x + y * y);
}

// GetAngle's index arithmetic is `sll v0,i,4 ; addiu v0,v0,16 ; addu
// v0,this,v0`, which is a byte offset from the top of the record and not
// an array subscript -- and the clamp below lets it go negative. This
// spells that, so the negative case reads the record's own header bytes
// rather than becoming an array access the compiler may assume away.
static const bVector3 *dt_point_at(const DriveTarget *t, int i)
{
    return (const bVector3 *)((const char *)t + 16 + i * 16);
}

// ---------------------------------------------------------- the free functions

int ai_is_point_ahead_of_car(const bVector2 *p, Car *car, float thresh)
{
    // 0x001c0e30. The car's velocity is normalised first and the delta
    // second, both in place on the stack, and the answer is a strict
    // `thresh < dot`.
    bVector2 v, d;

    v.x = car->State.Velocity.x;
    v.y = car->State.Velocity.y;
    d.x = p->x - car->State.Position.x;
    d.y = p->y - car->State.Position.y;

    bNormalize2(&v, &v);
    bNormalize2(&d, &d);

    return thresh < (v.x * d.x + v.y * d.y) ? 1 : 0;
}

float ai_calculate_look_ahead_distance(Car *car)
{
    // 0x001c0c20, six instructions ending in max.s. Written as the
    // comparison rather than as fmaxf, which would drag in a NaN rule the
    // hardware does not have.
    float d = car->State.VelocityMagnitude * AIDriverSecondsToLookAhead;

    return d < AIDriverDefaultLookAhead ? AIDriverDefaultLookAhead : d;
}

void ai_straight_line_predict(Car *car, DriveTarget *t)
{
    // 0x001c3338. One point, one look-ahead distance in front of the car.
    bVector3 dir, p;
    float look = ai_calculate_look_ahead_distance(car);

    if (car->State.VelocityMagnitude < 1.0f) {
        // Under 1 m/s the velocity is useless as a heading, so the body
        // angle is used instead. bSinCos writes sine first, cosine
        // second, and the caller puts the cosine in x -- and leaves
        // dir.pad alone, the same stack-w shape as everywhere else.
        float s, c;

        bSinCos(&s, &c, car->State.Angle);
        dir.x = c;
        dir.y = s;
        dir.z = 0.0f;
        dir.pad = 0.0f;   // STACK-W
    } else {
        // lqc2 of State.Velocity, then an inline VU0 normalise rather than
        // a call: `vrsqrt Q,vf00w,vf02x` over the three-lane sum and
        // `vmulx.xyzw` by it. The multiply is all four lanes, so the one
        // CarState calls pad comes out divided by |v.xyz| too -- it is
        // not the bNormalize3To it rounds the same as on x, y and z.
        //
        // A zero vector would be FLT_MAX on the VU and so a point on the
        // car. It cannot arrive here: both writers of VelocityMagnitude
        // take it from this Velocity, so 1 m/s of one is 1 m/s of the
        // other, and the divide is the plain one.
        const bVector3 *v = &car->State.Velocity;
        float q = 1.0f / dt_len3(v->x, v->y, v->z);

        dir.x = v->x * q;
        dir.y = v->y * q;
        dir.z = v->z * q;
        dir.pad = v->pad * q;
    }

    // vmulx broadcasts the look-ahead over all four lanes and vadd.xyzw
    // adds the position's four, so pad rides along.
    p.x = dir.x * look + car->State.Position.x;
    p.y = dir.y * look + car->State.Position.y;
    p.z = dir.z * look + car->State.Position.z;
    p.pad = dir.pad * look + car->State.Position.pad;

    drivetarget_clear(t, 0, 0.0f);
    drivetarget_add_point3(t, &p, -1, -1, -1, 0, 0);
}

// -------------------------------------------------------------- lifetime

DriveTarget *drivetarget_init(DriveTarget *t)
{
    // 0x002086f8. The twenty-iteration loop at the top has been optimised
    // down to nops -- the only trace left of twenty default-constructed
    // members -- and then the two time stamps are stored before a memset
    // that is about to zero them again.
    t->WhichPointIPickedCalculationTime = 0;
    t->WhichPointIPickedTime = 0;
    memset(t, 0, sizeof(DriveTarget));

    // With NumPoints zeroed this takes Clear's first early-out, so the
    // null Car is never dereferenced.
    drivetarget_clear(t, 0, 0.0f);
    return t;
}

void drivetarget_destroy(DriveTarget *t)
{
    // 0x00208768 is the GNU v2 deleting destructor: `if (flag & 1)
    // operator delete(this);` and nothing else. There is no destructor
    // body to port, and the delete belongs to the caller here.
    (void)t;
}

DriveTarget *drivetarget_assign(DriveTarget *dst, const DriveTarget *src)
{
    // 0x00208788: bMemCpy(a0, a1, 528), then `move v0,s0`. The size is an
    // immediate, so it is the whole record every time regardless of how
    // many points are actually in use -- pad bytes included.
    memcpy(dst, src, sizeof(DriveTarget));
    return dst;
}

DriveTarget *drivetarget_copy(DriveTarget *dst, const DriveTarget *src)
{
    // 0x001da210, in CarCollisionDetect.obj. Member-wise, and that is the
    // difference from the assignment operator above: five twenty-iteration
    // loops and eight scalar stores, no memcpy, so the three pad runs keep
    // whatever the destination already held. Retail's (0x001e7930) has a
    // ninth, `lbu v1,516 ; sb v1,516`, after Length.
    int i;

    for (i = 0; i < DRIVETARGET_MAX_POINTS; i++) dst->Points[i] = src->Points[i];
    for (i = 0; i < DRIVETARGET_MAX_POINTS; i++)
        dst->CalculatedSpeed[i] = src->CalculatedSpeed[i];
    for (i = 0; i < DRIVETARGET_MAX_POINTS; i++) dst->Route[i] = src->Route[i];
    for (i = 0; i < DRIVETARGET_MAX_POINTS; i++)
        dst->RoutePointNumber[i] = src->RoutePointNumber[i];
    for (i = 0; i < DRIVETARGET_MAX_POINTS; i++)
        dst->DrivingLine[i] = src->DrivingLine[i];

    dst->NumPoints = src->NumPoints;
    dst->TType = src->TType;
    dst->WhichPointIPicked = src->WhichPointIPicked;
    dst->WhichPointIPickedCalculationTime = src->WhichPointIPickedCalculationTime;
    dst->WhichPointIPickedTime = src->WhichPointIPickedTime;
    dst->Length = src->Length;
    dst->LastPointToScore = src->LastPointToScore;   // retail's ninth
    return dst;
}

// ------------------------------------------------------------ the queries

int32_t drivetarget_get_angle(DriveTarget *t, int i)
{
    // 0x002087b8. The clamp is `movz` then `movn`, in that order: up from
    // -1 to 0 first, then down to NumPoints - 2. Nothing brings it back
    // up, so 0 and 1 points leave it negative and the reads go off the
    // front of the array. See the header.
    const bVector3 *a, *b;
    float dx, dy;

    if (i <= -1) i = 0;
    if (t->NumPoints - 2 < i) i = t->NumPoints - 2;

    a = dt_point_at(t, i);
    b = dt_point_at(t, i + 1);
    dx = b->x - a->x;
    dy = b->y - a->y;
    return bATan(dx, dy);
}

float drivetarget_calculate_time(DriveTarget *t, float a, float b, float c)
{
    // 0x00209f40. Distance over the mean of the two speeds, with a
    // sentinel when both speeds are at rest. The second test is only
    // reached when the first fails, so a zero entry speed and a live exit
    // speed still divides.
    (void)t;
    if (fabsf(b) <= K_TIME_EPS && fabsf(c) <= K_TIME_EPS) return K_NO_TIME;
    return a / ((b + c) * 0.5f);
}

float drivetarget_get_max_lateral_acceleration(DriveTarget *t, Car *car)
{
    // 0x00209f30: lui at,0x41f0 ; mtc1 at,$f0 ; jr ra. Three instructions,
    // and neither argument is read.
    (void)t;
    (void)car;
    return K_MAX_LATERAL;
}

void drivetarget_recalculate_length(DriveTarget *t)
{
    // 0x0020a748. Length is zeroed in the branch's delay slot, so it
    // happens whether or not the loop runs, and then reloaded from and
    // stored back to the record on every iteration.
    int n, i;

    n = t->NumPoints;
    t->Length = 0.0f;
    if (n - 1 <= 0) return;

    for (i = 1; i < n; i++) {
        // vsub is prev - cur here, which the squares make irrelevant, but
        // it is what the listing does.
        float d = dt_len3(t->Points[i - 1].x - t->Points[i].x,
                          t->Points[i - 1].y - t->Points[i].y,
                          t->Points[i - 1].z - t->Points[i].z);
        t->Length = t->Length + d;
    }
}

int drivetarget_get_route_and_route_point(DriveTarget *t, int i,
                                          TrackRoute **route,
                                          TrackRoutePoint **pt)
{
    // 0x0020a7a8. Five ways to fail before the manager is touched, and
    // then a sixth -- a null test on a pointer that has just had 1064
    // added to it -- that can never fire.
    TrackRoute *tr;
    int rn;

    *route = 0;
    *pt = 0;
    if (i < 0) return 0;
    if (!(i < t->NumPoints)) return 0;
    if (t->Route[i] == -1) return 0;
    if (t->RoutePointNumber[i] == -1) return 0;

    // The image is `bltz` then a raw `lw` off pTrackRoutes: the negative
    // case is handled and nothing checks the top. Route[i] is an int8_t,
    // so 100..127 would index past the hundred-entry table -- into
    // whatever the linker put next, which is not the same thing here as
    // it was on the disc. trmgr_get_route's bound is used instead and the
    // divergence is written down rather than silently inherited.
    tr = t->Route[i] < 0 ? 0 : trmgr_get_route(&TheTrackRouteManager, t->Route[i]);
    if (tr == 0) return 0;

    // RoutePointNumber is re-read here rather than reused -- `lh v0,0(v1)`
    // a second time -- and multiplied by 112 with a three-operand mult.
    rn = t->RoutePointNumber[i];
    *route = tr;
    *pt = &tr->TrackRoutePointTable[rn];
    return 1;
}

int8_t drivetarget_get_first_point(DriveTarget *t, CarState *cs)
{
    // 0x002091f0. Cached for the frame against WorldTimer, so the second
    // call in a frame is four instructions.
    bVector2 vel, d, dn;
    float thresh;
    int best, i, n;

    if (WorldTimer == t->WhichPointIPickedCalculationTime)
        return t->WhichPointIPicked;

    n = t->NumPoints;
    if (n <= 0) {
        // The store is in a branch-likely delay slot, so it only happens
        // on this arm -- and the time stamp is cleared rather than set,
        // which means an empty target re-answers every call.
        t->WhichPointIPicked = 0;
        t->WhichPointIPickedCalculationTime = 0;
        return t->WhichPointIPicked;
    }

    // Above 30 m/s the cone opens all the way out: any point that is not
    // behind the car will do.
    thresh = K_AHEAD_DOT;
    best = n - 1;
    if (K_FAST_CAR < cs->ForwardSpeed) thresh = 0.0f;

    vel.x = cs->Velocity.x;
    vel.y = cs->Velocity.y;
    bNormalize2(&vel, &vel);

    // NumPoints is read again here, after the normalise, and again at the
    // bottom of every pass.
    for (i = 0; i < t->NumPoints; i++) {
        d.x = t->Points[i].x - cs->Position.x;
        d.y = t->Points[i].y - cs->Position.y;
        bNormalize2(&dn, &d);

        if (thresh < (dn.x * vel.x + dn.y * vel.y)) {
            // The length test uses the *unnormalised* delta, which is
            // still sitting on the stack.
            if (DriveTargetMinDistanceToPointSquared < (d.x * d.x + d.y * d.y)) {
                best = i;
                break;
            }
        }
    }

    t->WhichPointIPicked = (int8_t)best;
    t->WhichPointIPickedCalculationTime = WorldTimer;
    return t->WhichPointIPicked;
}

// ------------------------------------------------------------- the editors

void drivetarget_set_point3(DriveTarget *t, int i, const bVector3 *p,
                            int8_t route, int16_t rpn, int8_t dl, float speed)
{
    // 0x0020a6d0. The three narrow arguments arrive widened and are
    // sign-extended back before anything else happens, which is why they
    // are typed here rather than taken as int.
    if (i < 0) return;
    if (!(i < t->NumPoints)) return;

    t->Points[i] = *p;              // lqc2/sqc2: all sixteen bytes
    t->Route[i] = route;
    t->RoutePointNumber[i] = rpn;
    t->DrivingLine[i] = dl;
    t->CalculatedSpeed[i] = speed;
    t->WhichPointIPickedCalculationTime = 0;
    drivetarget_recalculate_length(t);
}

void drivetarget_set_point2(DriveTarget *t, int i, const bVector2 *p,
                            int8_t route, int16_t rpn, int8_t dl, float speed)
{
    // 0x0020a688. x, y, z = 0, and w left where it was -- see the file
    // header. The tail call means the wide form does the bounds check.
    bVector3 v;

    v.x = p->x;
    v.y = p->y;
    v.z = 0.0f;
    v.pad = 0.0f;   // STACK-W
    drivetarget_set_point3(t, i, &v, route, rpn, dl, speed);
}

void drivetarget_shift_right(DriveTarget *t, int n)
{
    // 0x0020a478. Opens n slots at the front. The copy runs downwards so
    // it can overlap, and the blank it leaves behind is partial: position,
    // RoutePointNumber and CalculatedSpeed are cleared, Route and
    // DrivingLine are not, and neither is Points[i].pad -- the three stores
    // are `sw zero,24` / `sw zero,16` / `sw zero,20`, x, y and z only.
    int i, m;

    if (!(n < DRIVETARGET_MAX_POINTS)) return;

    for (i = t->NumPoints - n - 1; i >= 0; i--) {
        int d = i + n;

        t->Points[d] = t->Points[i];
        t->Route[d] = t->Route[i];
        t->RoutePointNumber[d] = t->RoutePointNumber[i];
        t->DrivingLine[d] = t->DrivingLine[i];
        t->CalculatedSpeed[d] = t->CalculatedSpeed[i];
    }

    // The store happens in the branch's delay slot and is then overwritten
    // on the clamped arm, so the truncation to int8_t is visible either
    // way. m is the unsigned byte plus n, exactly as the image computes it.
    m = (uint8_t)t->NumPoints + n;
    t->NumPoints = (int8_t)m;
    if (!((int8_t)m < 21)) t->NumPoints = DRIVETARGET_MAX_POINTS;

    if (n > 0) {
        for (i = 0; i < n; i++) {
            t->Points[i].z = 0.0f;
            t->Points[i].x = 0.0f;
            t->Points[i].y = 0.0f;
            t->RoutePointNumber[i] = -1;
            t->CalculatedSpeed[i] = 0.0f;
        }
    }

    t->WhichPointIPickedTime = 0;
    t->WhichPointIPickedCalculationTime = 0;
}

void drivetarget_shift_left(DriveTarget *t, int n, int recalc)
{
    // 0x0020a5a8. Drops the first n. The loop bound is recomputed from the
    // record on every pass -- `lb v0,0(t2) ; subu v0,v0,t3` -- though
    // nothing in the body writes NumPoints.
    int i;
    uint8_t m;

    if (!(n < t->NumPoints)) return;

    m = (uint8_t)t->NumPoints;
    if (t->NumPoints - n > 0) {
        for (i = 0; i < t->NumPoints - n; i++) {
            int s = i + n;

            t->Points[i] = t->Points[s];
            t->Route[i] = t->Route[s];
            t->RoutePointNumber[i] = t->RoutePointNumber[s];
            t->DrivingLine[i] = t->DrivingLine[s];
            t->CalculatedSpeed[i] = t->CalculatedSpeed[s];
            m = (uint8_t)t->NumPoints;
        }
    }

    t->WhichPointIPickedCalculationTime = 0;
    t->NumPoints = (int8_t)(m - n);
    t->WhichPointIPickedTime = 0;
    if (recalc) drivetarget_recalculate_length(t);
}

// ---------------------------------------------------------- adding a point

void drivetarget_add_point3(DriveTarget *t, const bVector3 *p, int8_t route,
                            int16_t rpn, int8_t dl, int check, Car *car)
{
    // 0x00209048, the one everything else funnels into.
    int n = t->NumPoints;
    int ok = 1;

    if (!(n < DRIVETARGET_MAX_POINTS)) return;

    if (check) {
        if (n < 2) {
            // With fewer than two points there is no direction in the
            // target to compare against, so the car supplies one -- and
            // with no car the point is simply accepted.
            if (car != 0) ok = ai_is_point_ahead_of_car((const bVector2 *)p, car, 0.0f);
        } else {
            // Does the new leg double back on the last one? Three lanes,
            // and the test is strict.
            float ax = t->Points[n - 1].x - t->Points[n - 2].x;
            float ay = t->Points[n - 1].y - t->Points[n - 2].y;
            float az = t->Points[n - 1].z - t->Points[n - 2].z;
            float bx = p->x - t->Points[n - 1].x;
            float by = p->y - t->Points[n - 1].y;
            float bz = p->z - t->Points[n - 1].z;

            if ((ax * bx + ay * by) + az * bz < 0.0f) ok = 0;
        }
    }
    if (!ok) return;

    // NumPoints is re-read before each of the five stores. Nothing in
    // between can change it, but the reloads are what the listing does.
    t->Points[t->NumPoints] = *p;
    t->Route[t->NumPoints] = route;
    t->RoutePointNumber[t->NumPoints] = rpn;
    t->DrivingLine[t->NumPoints] = dl;
    t->WhichPointIPickedCalculationTime = 0;
    t->WhichPointIPickedTime = 0;
    t->CalculatedSpeed[t->NumPoints] = 0.0f;

    if (t->NumPoints > 0) {
        int k = t->NumPoints;

        t->Length = t->Length + dt_len3(p->x - t->Points[k - 1].x,
                                        p->y - t->Points[k - 1].y,
                                        p->z - t->Points[k - 1].z);
    }
    t->NumPoints = (int8_t)((uint8_t)t->NumPoints + 1);
}

void drivetarget_add_point2(DriveTarget *t, const bVector2 *p, int8_t route,
                            int16_t rpn, int8_t dl, int check, Car *car)
{
    // 0x00208f58. z is zeroed in the tail call's delay slot; w is not
    // written at all.
    bVector3 v;

    v.x = p->x;
    v.y = p->y;
    v.z = 0.0f;
    v.pad = 0.0f;   // STACK-W
    drivetarget_add_point3(t, &v, route, rpn, dl, check, car);
}

void drivetarget_add_point3_dl(DriveTarget *t, const bVector3 *p,
                               DrivingLocation *loc, int check, Car *car)
{
    // 0x00208e60. IsClear is called three separate times -- the compiler
    // did not common them up -- and the second and third can only ever
    // answer what the first did, because nothing between them writes the
    // location. The -1 arms they guard are unreachable.
    int8_t route;
    int16_t rpn;
    int8_t dl;

    if (drivinglocation_is_clear(loc)) return;

    route = drivinglocation_is_clear(loc) ? -1 : (int8_t)loc->pRoute->RouteNumber;

    if (drivinglocation_is_clear(loc)) {
        rpn = -1;
    } else {
        // The image divides the byte offset by 112 with the magic
        // multiply (x * 0xB6DB6DB7) >> 4 -- 0xB6DB6DB7 is 7's inverse mod
        // 2^32 and 112 is 16 * 7, so it is exact for any offset that is a
        // whole number of route points, which this always is. Pointer
        // subtraction is the same arithmetic without the trick.
        rpn = (int16_t)(loc->pRoutePoint - loc->pRoute->TrackRoutePointTable);
    }

    // `lb`: the word's low byte, sign-extended.
    dl = (int8_t)loc->DrivingLine;
    drivetarget_add_point3(t, p, route, rpn, dl, check, car);
}

void drivetarget_add_point2_dl(DriveTarget *t, const bVector2 *p,
                               DrivingLocation *loc, int check, Car *car)
{
    // 0x00208e30. z is stored before the two loads rather than after,
    // which changes nothing; w is left alone as usual.
    bVector3 v;

    v.z = 0.0f;
    v.y = p->y;
    v.x = p->x;
    v.pad = 0.0f;   // STACK-W
    drivetarget_add_point3_dl(t, &v, loc, check, car);
}

// -------------------------------------------------------- the path walkers

int drivetarget_interpolate_point(DriveTarget *t, Car *car, float dist,
                                  bVector3 *out)
{
    // 0x00208b98. The cumulative-distance array is indexed by point number
    // rather than packed, so entries below `first` are never written and
    // never read.
    float cum[DRIVETARGET_MAX_POINTS];
    bVector3 d;
    int n = t->NumPoints;
    int first, i, last;

    if (n == 0) return -1;   // `out` is not written on this arm

    if (n == 1) {
        // One point: strike out towards it and stop at `dist`, whether or
        // not that overshoots. All four lanes, so pad rides through the
        // subtract, the normalise -- which leaves it alone -- and the add.
        d.x = t->Points[0].x - car->State.Position.x;
        d.y = t->Points[0].y - car->State.Position.y;
        d.z = t->Points[0].z - car->State.Position.z;
        d.pad = t->Points[0].pad - car->State.Position.pad;
        bNormalize3To(&d, &d, dist);
        out->x = car->State.Position.x + d.x;
        out->y = car->State.Position.y + d.y;
        out->z = car->State.Position.z + d.z;
        out->pad = car->State.Position.pad + d.pad;
        return 0;
    }

    first = drivetarget_get_first_point(t, &car->State);
    i = first;
    cum[i] = dt_len3(t->Points[i].x - car->State.Position.x,
                     t->Points[i].y - car->State.Position.y,
                     t->Points[i].z - car->State.Position.z);

    if (cum[i] < dist) {
        for (i = first + 1; i < t->NumPoints; i++) {
            float seg = dt_len3(t->Points[i].x - t->Points[i - 1].x,
                                t->Points[i].y - t->Points[i - 1].y,
                                t->Points[i].z - t->Points[i - 1].z);

            cum[i] = seg + cum[i - 1];
            // DummyFunction (0x00208b90) is a bare `jr ra` in the shipped
            // image -- a debug hook that survived as a call site.
            if (dist <= cum[i]) break;
        }
    }

    last = t->NumPoints - 1;
    if (last < i) {
        // Ran off the end: keep going past the last point in the
        // direction of the last leg.
        d.x = t->Points[last].x - t->Points[last - 1].x;
        d.y = t->Points[last].y - t->Points[last - 1].y;
        d.z = t->Points[last].z - t->Points[last - 1].z;
        d.pad = t->Points[last].pad - t->Points[last - 1].pad;
        bNormalize3To(&d, &d, dist - cum[last]);
        out->x = t->Points[last].x + d.x;
        out->y = t->Points[last].y + d.y;
        out->z = t->Points[last].z + d.z;
        out->pad = t->Points[last].pad + d.pad;
        return last;
    }

    {
        // Lerp across the segment that contains `dist`. The base is the
        // car itself on the first segment and the previous point after
        // that, which is also what the return value distinguishes.
        const bVector3 *base;
        float prev, s;
        int ret;

        if (first < i) {
            prev = cum[i - 1];
            base = &t->Points[i - 1];
            ret = i - 1;
        } else {
            prev = 0.0f;
            base = &car->State.Position;
            ret = -1;
        }

        d.x = t->Points[i].x - base->x;
        d.y = t->Points[i].y - base->y;
        d.z = t->Points[i].z - base->z;
        d.pad = t->Points[i].pad - base->pad;
        s = (dist - prev) / (cum[i] - prev);
        out->x = d.x * s + base->x;
        out->y = d.y * s + base->y;
        out->z = d.z * s + base->z;
        out->pad = d.pad * s + base->pad;
        return ret;
    }
}

void drivetarget_clear(DriveTarget *t, Car *car, float speed)
{
    // 0x00208980, retail 0x0021bbb0. Everything the AI decided last frame is thrown away
    // except the part of the path that is still in front of the car.
    bVector3 p;
    int n, i, r;

    n = t->NumPoints;
    if (n == 0) {
        t->Length = 0.0f;
        goto done;
    }

    // Standing still, or reversing, means there is no path worth keeping.
    if (fabsf(speed) <= K_CLEAR_EPS || speed < 0.0f) {
        t->NumPoints = 0;
        t->Length = 0.0f;
        goto done;
    }

    // Walk forward to the first point the car is still heading towards.
    // The comparison is against the raw velocity, not a normalised one,
    // and it is strict.
    for (i = 0; i < (int8_t)(uint8_t)n; i++) {
        float dx = t->Points[i].x - car->State.Position.x;
        float dy = t->Points[i].y - car->State.Position.y;

        if (0.0f < (car->State.Velocity.x * dx + car->State.Velocity.y * dy))
            break;
    }
    if (!(i < (int8_t)(uint8_t)n)) {
        // Every point is behind the car.
        t->NumPoints = 0;
        t->Length = 0.0f;
        goto done;
    }

    if (i > 0) drivetarget_shift_left(t, i, 0);

    r = drivetarget_interpolate_point(t, car, speed, &p);
    if (r < t->NumPoints - 1) {
        if (r >= 0) {
            // Truncate to the interpolated point and re-close the length.
            t->NumPoints = (int8_t)(r + 1);
            drivetarget_add_point3(t, &p, t->Route[r], t->RoutePointNumber[r],
                                   t->DrivingLine[r], 0, 0);
            drivetarget_recalculate_length(t);
            goto done;
        }
    } else if (r >= 0) {
        goto done;
    }

    // r < 0: the interpolated point is on the first leg, so the whole
    // target collapses to it. The route data is read out of the slot
    // GetFirstPoint chose *before* NumPoints is zeroed.
    {
        int f = drivetarget_get_first_point(t, &car->State);
        int8_t route = t->Route[f];
        int16_t rpn = t->RoutePointNumber[f];
        int8_t dl = t->DrivingLine[f];

        t->NumPoints = 0;
        drivetarget_add_point3(t, &p, route, rpn, dl, 0, 0);
        drivetarget_recalculate_length(t);
    }

done:
    // Every way out ends here. Retail's tail (0x0021bd98) is the demo's two
    // stores with LastPointToScore's -1 between them, so a target the AI
    // clears scores every corner again until something sets it.
    t->WhichPointIPickedTime = 0;
    t->LastPointToScore = -1;
    t->WhichPointIPickedCalculationTime = 0;
}

void drivetarget_resample(DriveTarget *t, Car *car)
{
    // 0x00209358. Respaces the points evenly along the path they already
    // describe -- same shape, same total length, uniform spacing. The Car
    // is taken and never read.
    bVector3 out[DRIVETARGET_MAX_POINTS];
    bVector3 seg[DRIVETARGET_MAX_POINTS];
    float len[DRIVETARGET_MAX_POINTS];
    uint8_t raw;
    int n, k, j, limit;
    float step, emitted, travelled, next;

    (void)car;
    if (t->NumPoints < 3) return;
    raw = (uint8_t)t->NumPoints;
    n = (int8_t)raw;

    // Two more twenty-iteration nop loops, the array constructors again.
    t->Length = 0.0f;
    for (k = 0; k < n - 1; k++) {
        seg[k].x = t->Points[k + 1].x - t->Points[k].x;
        seg[k].y = t->Points[k + 1].y - t->Points[k].y;
        seg[k].z = t->Points[k + 1].z - t->Points[k].z;
        seg[k].pad = t->Points[k + 1].pad - t->Points[k].pad;
        len[k] = dt_len3(seg[k].x, seg[k].y, seg[k].z);
        t->Length = t->Length + len[k];
    }

    // The last segment is a copy of the one before it, so the walk has
    // somewhere to go if it reaches the end.
    seg[n - 1] = seg[n - 2];
    len[n - 1] = len[n - 2];
    step = t->Length / (float)(n - 1);

    k = 0;
    emitted = 0.0f;    // f1, the distance the next point will sit at
    travelled = 0.0f;  // f2, how far into segment k we are
    next = 0.0f;       // f3, the distance the point just emitted sits at
    limit = n;

    if (n <= 0) goto done;
    if (!(0.0f <= t->Length)) goto done;

    j = 0;
    for (;;) {
        float frac;

        next = emitted;
        emitted = next + step;
        frac = travelled / len[k];
        out[j].x = t->Points[k].x + seg[k].x * frac;
        out[j].y = t->Points[k].y + seg[k].y * frac;
        out[j].z = t->Points[k].z + seg[k].z * frac;
        out[j].pad = t->Points[k].pad + seg[k].pad * frac;
        travelled = travelled + step;
        j++;

        if (!(emitted <= t->Length)) break;
        if (!(k < n)) goto done_keep;
        if (len[k] <= travelled) {
            // Step over as many whole segments as the accumulator covers.
            for (;;) {
                if (!(emitted <= t->Length)) goto tail;
                travelled = travelled - len[k];
                k++;
                if (!(k < limit)) goto done;
                if (!(len[k] <= travelled)) goto tail;
            }
        }
tail:
        if (!(k < n)) goto done_keep;
        if (!(emitted <= t->Length)) goto done;
    }

done:
done_keep:
    // Length becomes the distance of the *last* point emitted, not the
    // path length it started from.
    t->Length = next;
    memcpy(&t->Points[0], out, (size_t)((int8_t)raw * 16));
    t->WhichPointIPickedTime = 0;
    t->WhichPointIPickedCalculationTime = 0;
}

// -------------------------------------------------------------- the scoring

int drivetarget_calculate_max_speed_v(DriveTarget *t, Car *car,
                                      const bVector2 *v1, const bVector2 *v2,
                                      float dist, float speed, float *pOut)
{
    // Retail 0x0021d130, new in retail: the demo's CalculateMaxSpeed from
    // its third test on. Two velocity vectors, the acceleration between
    // them, and the question of whether its lateral part fits inside the
    // grip.
    bVector2 dv, acc, par, perp;
    float time, inv, k, mag, grip;

    dv.x = v2->x - v1->x;
    dv.y = v2->y - v1->y;

    time = drivetarget_calculate_time(t, dist, speed, *pOut);
    if (fabsf(time) <= K_MAXSPEED_V_EPS) {
        *pOut = speed;
        return 1;
    }

    // The reciprocal is taken once and multiplied twice, which is not the
    // same as dividing twice.
    inv = 1.0f / time;
    acc.y = dv.y * inv;
    acc.x = dv.x * inv;

    // The divide is ee_div's. drivetarget_calculate_max_speed_from_car has
    // no early answers, so a car standing still hands its zero velocity in
    // as v1 and this is 0/0: FLT_MAX on the console, whose products with
    // v1's zeroes are zeroes, so the lateral part is the whole of the
    // acceleration. IEEE's NaN would refuse every corner instead.
    k = ee_div(v1->x * acc.x + v1->y * acc.y, v1->x * v1->x + v1->y * v1->y);
    par.y = v1->y * k;
    par.x = v1->x * k;
    perp.y = acc.y - par.y;
    perp.x = acc.x - par.x;

    mag = dt_len2(perp.x, perp.y);

    // The parallel magnitude is computed here too -- two multiplies, an
    // add and a sqrt -- and never used. Dead in the shipped image.
    (void)dt_len2(par.x, par.y);

    grip = drivetarget_get_max_lateral_acceleration(t, car);
    if (mag < grip) return 1;
    if (fabsf(mag - grip) <= K_MAXSPEED_V_EPS) return 1;
    return 0;
}

int drivetarget_calculate_max_speed(DriveTarget *t, Car *car,
                                    const bVector2 *p0, const bVector2 *p1,
                                    const bVector2 *p2, float dist,
                                    float speed, float *pOut)
{
    // 0x00209cf0, retail 0x0021cfe8. The two early answers and the two
    // velocities; the rest is drivetarget_calculate_max_speed_v's.
    bVector2 v1, v2;

    if (fabsf(speed) <= K_MAXSPEED_EPS) return 1;
    if (fabsf(dist) <= K_MAXSPEED_EPS) {
        *pOut = speed;
        return 1;
    }

    v1.x = p1->x - p0->x;
    v1.y = p1->y - p0->y;
    bNormalize2To(&v1, &v1, speed);

    v2.x = p2->x - p1->x;
    v2.y = p2->y - p1->y;
    bNormalize2To(&v2, &v2, *pOut);

    return drivetarget_calculate_max_speed_v(t, car, &v1, &v2, dist, speed,
                                             pOut);
}

int drivetarget_calculate_max_speed_from_car(DriveTarget *t, Car *car,
                                             const bVector2 *p, float *pOut,
                                             float factor)
{
    // Retail 0x0021cf38, new in retail. v1 is the velocity itself, not
    // scaled; v2 points from the car to `p` at the speed wanted there.
    bVector2 d;
    float dist = factor * fabsf(car->State.ForwardSpeed);

    d.x = p->x - car->State.Position.x;
    d.y = p->y - car->State.Position.y;
    bNormalize2To(&d, &d, *pOut);

    return drivetarget_calculate_max_speed_v(
        t, car, (const bVector2 *)&car->State.Velocity, &d, dist,
        car->State.VelocityMagnitude, pOut);
}

int8_t drivetarget_get_last_corner_to_score(DriveTarget *t)
{
    // Retail 0x0021bdc8, new in retail. Both arms narrow through
    // `sll 24 ; sra 24`.
    if (t->LastPointToScore == -1) return (int8_t)(t->NumPoints - 2);
    return (int8_t)(t->LastPointToScore - 1);
}

float drivetarget_estimate_score(DriveTarget *t, Car *car)
{
    // 0x002096b0, retail 0x0021c920. Fills CalculatedSpeed with the car's
    // current speed, walks the points in three nested passes asking whether
    // each corner fits, and returns the distance-weighted mean of the
    // speeds it ends up with -- or -1.0f if any corner did not fit.
    // The image leaves this stack array untouched below `first`, and there
    // is one path that can then read an entry nothing wrote: a stale
    // WhichPointIPicked cache whose value is past NumPoints skips the fill
    // loop entirely. That cannot happen to a target the AI built, but it is
    // undefined behaviour rather than a wrong number, so the array is
    // zeroed here and the divergence noted.
    float dist[DRIVETARGET_MAX_POINTS] = { 0.0f };
    CarState *cs;
    int ok = 1, bail = 0, maxSpeedOK = 1;
    int first, i, s0, outer, last;
    float leg = 0.0f;
    float acc, total;

    if (t->NumPoints == 0) return -1.0f;

    cs = &car->State;
    if (t->NumPoints == 1) {
        // A single point is scored off the car's own speed and bails
        // before any of the corner tests.
        float dx, dy;

        t->CalculatedSpeed[0] = cs->VelocityMagnitude;
        dx = car->State.Position.x - t->Points[0].x;
        dy = car->State.Position.y - t->Points[0].y;
        dist[0] = dt_len2(dx, dy);
        bail = 1;
    }

    first = drivetarget_get_first_point(t, cs);
    if (first < t->NumPoints && !bail) {
        for (i = first;;) {
            float dx, dy;

            t->CalculatedSpeed[i] = cs->VelocityMagnitude;
            if (first < i) {
                dx = t->Points[i].x - t->Points[i - 1].x;
                dy = t->Points[i].y - t->Points[i - 1].y;
            } else {
                dx = t->Points[i].x - car->State.Position.x;
                dy = t->Points[i].y - car->State.Position.y;
            }
            dist[i] = dt_len2(dx, dy);
            i++;
            if (!(i < t->NumPoints)) break;
            if (bail) break;
        }
    }
    if (bail) goto final;

    // Pass one: from the chosen point, skip forward while the car reaches
    // the next point inside the first threshold.
    s0 = first;
    if (drivetarget_calculate_time(t, dist[first], cs->VelocityMagnitude,
                                   t->CalculatedSpeed[first]) < K_SCORE_T1) {
        if (first < t->NumPoints) {
            for (s0 = first + 1;;) {
                float dx = car->State.Position.x - t->Points[s0].x;
                float dy = car->State.Position.y - t->Points[s0].y;

                leg = dt_len2(dx, dy);
                if (!(drivetarget_calculate_time(t, leg, cs->VelocityMagnitude,
                                                 t->CalculatedSpeed[s0])
                      < K_SCORE_T2))
                    break;
                if (!(s0 < t->NumPoints)) break;
                s0++;
            }
        }
    }

    // The first corner is the point the walk stopped on, taken from the
    // car's velocity over half a second of its forward speed. The demo
    // asked CalculateMaxSpeed instead, from the car's position through
    // that point to the next.
    if (s0 + 1 < t->NumPoints)
        maxSpeedOK = drivetarget_calculate_max_speed_from_car(
            t, car, (const bVector2 *)&t->Points[s0], &t->CalculatedSpeed[s0],
            K_FIRST_CORNER);
    if (maxSpeedOK == 0) {
        ok = 0;
        bail = 1;
    }

    // Read before the bail is tested, as the image does.
    last = drivetarget_get_last_corner_to_score(t);
    s0 = s0 + 1;
    if (bail) goto final;
    if (last < s0) goto final;

    // Pass two: the same question for every corner up to `last`, with the
    // same skip-ahead inside it.
    do {
        outer = s0;
        leg = dt_len2(t->Points[outer - 1].x - t->Points[outer].x,
                      t->Points[outer - 1].y - t->Points[outer].y);

        if (drivetarget_calculate_time(t, leg, t->CalculatedSpeed[outer - 1],
                                       t->CalculatedSpeed[outer]) < K_SCORE_T3) {
            if (s0 < t->NumPoints) {
                // The inner walk always measures back to Points[outer-1],
                // which stays put while s0 runs forward.
                for (;;) {
                    s0++;
                    leg = dt_len2(t->Points[outer - 1].x - t->Points[s0].x,
                                  t->Points[outer - 1].y - t->Points[s0].y);
                    if (!(drivetarget_calculate_time(t, leg,
                                                     t->CalculatedSpeed[outer - 1],
                                                     t->CalculatedSpeed[s0])
                          < K_SCORE_T3))
                        break;
                    if (!(s0 < t->NumPoints)) break;
                }
            }
        }

        // A walk that ran past `last` stops the pass without asking, and
        // without failing it.
        if (last < s0) {
            bail = 1;
        } else {
            maxSpeedOK = drivetarget_calculate_max_speed(
                t, car, (const bVector2 *)&t->Points[outer - 1],
                (const bVector2 *)&t->Points[s0],
                (const bVector2 *)&t->Points[s0 + 1],
                leg, t->CalculatedSpeed[outer - 1], &t->CalculatedSpeed[s0]);
            s0++;
        }

        if (maxSpeedOK == 0) {
            ok = 0;
            bail = 1;
        }
    } while (!bail && !(last < s0));

final:
    if (!ok) return -1.0f;

    // The score itself: a trapezoid sum of speed against distance divided
    // by the distance, which is the mean speed weighted by how long the
    // car spends at it.
    total = dist[first];
    acc = (dist[first] * 0.5f) * (t->CalculatedSpeed[first] + cs->VelocityMagnitude);
    for (i = first + 1; i < t->NumPoints; i++) {
        total = total + dist[i];
        acc = acc + (dist[i] * 0.5f)
                    * (t->CalculatedSpeed[i] + t->CalculatedSpeed[i - 1]);
        if (!ok) break;
    }

    if (0.0f < total) return acc / total;
    return -1.0f;
}

// ------------------------------------------------------- the two predictors

void drivetarget_fill_with_current_acceleration(DriveTarget *t, Car *car)
{
    // 0x00209fb0. Where the car would go if it kept accelerating exactly
    // as it is now. The acceleration is sampled once and held.
    bVector2 pos, vel, acc, newVel, newPos;
    float look, travelled = 0.0f;

    drivetarget_clear(t, 0, 0.0f);
    look = ai_calculate_look_ahead_distance(car);

    pos.x = car->State.Position.x;
    pos.y = car->State.Position.y;
    vel.x = car->State.Velocity.x;
    vel.y = car->State.Velocity.y;
    acc.x = car->State.Acceleration.x;
    acc.y = car->State.Acceleration.y;

    // An acceleration past three quarters of the speed is not trusted to
    // integrate, and a straight line along the velocity is used instead.
    // `c.lt.s` then `bc1f` past the StraightLinePredict call: the strict
    // test, so exactly three quarters integrates. A car with no speed and
    // no acceleration integrates too, and the twenty-point wall stops it.
    if (dt_len2(vel.x, vel.y) * K_ACC_DOMINATES < dt_len2(acc.x, acc.y)) {
        ai_straight_line_predict(car, t);
        return;
    }

    if (!(0.0f < look)) return;
    if (!(t->NumPoints < DRIVETARGET_MAX_POINTS)) return;

    for (;;) {
        bScaleAdd2(&newVel, &vel, &acc, K_PREDICT_DT);
        bScaleAdd2(&newPos, &pos, &newVel, K_PREDICT_DT);
        drivetarget_add_point2(t, &newPos, -1, -1, -1, 1, 0);

        travelled = travelled + dt_len2(pos.x - newPos.x, pos.y - newPos.y);

        // The turn-back test is against the car's *original* velocity,
        // re-read out of the CarState every pass, not against the running
        // one.
        {
            float dot = newVel.x * car->State.Velocity.x
                        + newVel.y * car->State.Velocity.y;

            pos = newPos;
            vel = newVel;
            if (dot < 0.0f) return;
        }
        if (!(travelled < look)) return;
        if (!(t->NumPoints < DRIVETARGET_MAX_POINTS)) return;
    }
}

void drivetarget_blend_with_current_acceleration(DriveTarget *t, Car *car)
{
    // 0x0020a1d8. The same integration, but instead of replacing the
    // points it drags each one part of the way towards where the car is
    // actually heading -- all the way at t = 0, not at all by 0.75s.
    bVector2 pos, vel, acc, newVel, newPos;
    bVector3 blended;
    float velMag, accTime = 0.0f;
    int i;

    if (t->WhichPointIPickedTime == WorldTimer) return;
    if (car->pPlayer != 0) return;   // a human's target is left alone
    t->WhichPointIPickedTime = WorldTimer;

    pos.x = car->State.Position.x;
    pos.y = car->State.Position.y;
    vel.x = car->State.Velocity.x;
    vel.y = car->State.Velocity.y;
    acc.x = car->State.Acceleration.x;
    acc.y = car->State.Acceleration.y;
    velMag = car->State.VelocityMagnitude;

    i = drivetarget_get_first_point(t, &car->State);
    if (velMag < 1.0f) return;
    if (!(i < t->NumPoints)) return;

    for (;;) {
        float dx, dy, dt, blend, inv;

        // The leg is measured from the car for the point GetFirstPoint
        // chose and from the previous point for everything after it.
        // WhichPointIPicked is re-read every pass.
        if (i == t->WhichPointIPicked) {
            dx = car->State.Position.x - t->Points[i].x;
            dy = car->State.Position.y - t->Points[i].y;
        } else {
            dx = t->Points[i - 1].x - t->Points[i].x;
            dy = t->Points[i - 1].y - t->Points[i].y;
        }

        dt = dt_len2(dx, dy) / velMag;
        accTime = accTime + dt;
        bScaleAdd2(&newVel, &vel, &acc, dt);
        bScaleAdd2(&newPos, &pos, &newVel, dt);

        blend = accTime * K_BLEND_SCALE;
        if (1.0f < blend) blend = 1.0f;
        inv = 1.0f - blend;

        blended.x = t->Points[i].x * blend + newPos.x * inv;
        blended.y = t->Points[i].y * blend + newPos.y * inv;
        blended.z = 0.0f;
        blended.pad = 0.0f;   // STACK-W

        {
            int8_t route = t->Route[i];
            int16_t rpn = t->RoutePointNumber[i];
            int8_t dl = t->DrivingLine[i];

            vel = newVel;
            pos = newPos;
            drivetarget_set_point3(t, i, &blended, route, rpn, dl, 0.0f);
        }
        i++;

        if (!(accTime < K_BLEND_WINDOW)) return;
        if (!(i < t->NumPoints)) return;
    }
}

// ------------------------------------------------------------------- debug

void drivetarget_dump(DriveTarget *t, Car *car, int checkCamera, int unused)
{
    // 0x002095f8. In the shipped image the prints are gone: what is left
    // transforms every point into car space and drops the answer on the
    // floor. It is kept because the guard is the observable part -- and
    // because CameraFollowDefaultCar ships as 1, so the guard turns the
    // whole thing off before the first point is even read.
    bVector3 local;
    int i;

    (void)unused;
    if (checkCamera) {
        if (CameraFollowDefaultCar != 0) return;
        if (car->DriverNumber != CameraFollowThisCarInstead) return;
    }

    for (i = 0; i < t->NumPoints; i++) {
        if (car == 0) {
            local = t->Points[i];
        } else {
            carstate_world_to_car2(&car->State, (bVector2 *)&local,
                                   (const bVector2 *)&t->Points[i]);
            local.z = t->Points[i].z;
        }
    }
    (void)local;
}
