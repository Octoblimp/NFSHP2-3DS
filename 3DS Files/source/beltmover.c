// beltmover -- see beltmover.h.

#include "beltmover.h"

#include <math.h>
#include <stddef.h>

#include "aicarcontroller.h"   // OffBeltTimer
#include "bmath.h"
#include "bmem.h"
#include "cardriver.h"
#include "carmodes.h"          // CAR_MEMORY_POOL and the two seams
#include "carstate.h"
#include "cartypeinfo.h"
#include "drivetarget.h"
#include "eefpu.h"
#include "nearbycar.h"         // ai_calculate_max_acceleration, the third
#include "physcomp.h"          // wheel_new
#include "physicssystem.h"     // PhysicsDtorFn
#include "replay.h"
#include "vtable.h"
#include "world.h"

// ------------------------------------------------------------ the tuning

// The .lit4 constants, gp-27744 .. gp-27684, and the gravity the physics
// shares, gp-19912. tools/beltmover_check.py reads each back out of the
// pool.
#define BM_SPIN_SCALE         0.4f      // gp-27744  3ecccccd
#define BM_SLIDE_DURATION     0.3f      // gp-27740  3e99999a
#define BM_PARAM_TOLERANCE    0.005f    // gp-27736  3ba3d70a
#define BM_SPEED_FRACTION     0.899f    // gp-27732  3f6624dd
#define BM_ANGLE_DURATION     0.4f      // gp-27728  3ecccccd
#define BM_KNEE_LOW           0.9f      // gp-27724  3f666666
#define BM_KNEE_HIGH          1.1f      // gp-27720  3f8ccccd
#define BM_SLIDE_END_DURATION 0.3f      // gp-27716  3e99999a
#define BM_SLIDE_END_RATE     1.6f      // gp-27712  3fcccccd
#define BM_AIR_STEP           0.1f      // gp-27708  3dcccccd
#define BM_AIR_SCALE          0.1f      // gp-27704  3dcccccd
#define BM_AIR_THRESHOLD      0.002f    // gp-27700  3b03126f
#define BM_OFF_BELT_TICKS     2400.5f   // gp-27696  45160800, SetTime(0.6)
#define BM_SLIDE_LOOK_AHEAD   0.3f      // gp-27692  3e99999a
#define BM_BAM_TO_RAD         9.587379463482648e-05f // gp-27688 38c90fda
#define BM_MIN_DT             0.0001f   // gp-27684  38d1b717
#define BM_GRAVITY            9.8f      // gp-19912  411ccccd

// 0x0031b9d0 and 0x0031b9f0, which the start-up code fills, gp-27680 ..
// gp-27668 among them. SlideCoef moves points 1 to 3 along x.
static bVector2 BeltSlidePoints[4] = {
    { 0.0f, 0.0f }, { 18.0f, 0.1f }, { 22.0f, 0.4f }, { 30.0f, 0.7f }
};
static bVector2 BeltSlidingPoints[4] = {
    { 0.0f, 0.0f }, { 14.5f, 0.4f }, { 16.5f, 0.6f }, { 30.0f, 1.0f }
};
Graph BeltSlideGraph   = { BeltSlidePoints, 4 };
Graph BeltSlidingGraph = { BeltSlidingPoints, 4 };

// --------------------------------------------------------- VU idioms

// `vmul.xyz ; vaddy.x ; vaddz.x`: (x*x + y*y) + z*z, left to right.
static float dot3(const bVector3 *a, const bVector3 *b)
{
    return (a->x * b->x + a->y * b->y) + a->z * b->z;
}

// `vopmula.xyz ACC,vfA,vfB` / `vopmsub.xyz vfA,vfB,vfA`, A cross B, with
// A's w lane kept.
static void cross3(bVector3 *o, const bVector3 *a, const bVector3 *b)
{
    float x = a->y * b->z - b->y * a->z;
    float y = a->z * b->x - b->z * a->x;
    float z = a->x * b->y - b->x * a->y;

    o->x = x;
    o->y = y;
    o->z = z;
    o->pad = a->pad;
}

// `vrsqrt Q,vf00w,vf01x ; vaddq.x ; vmulx.xyzw`: all four lanes over the
// length of three. A tangent of length 0 -- a belt of repeated points, or
// one standing straight up under the cross product -- divides the EE's way.
static void normalize4(bVector3 *v)
{
    float inv = 0.0f + ee_div(1.0f, sqrtf(dot3(v, v)));

    v->x = v->x * inv;
    v->y = v->y * inv;
    v->z = v->z * inv;
    v->pad = v->pad * inv;
}

static void scale4(bVector3 *o, const bVector3 *v, float k)
{
    o->x = v->x * k;
    o->y = v->y * k;
    o->z = v->z * k;
    o->pad = v->pad * k;
}

// QuickSpline::GetPoint into a bVector3's sixteen bytes.
static void spline_point(QuickSpline *s, bVector3 *out, float t, int32_t basis)
{
    bVector4 q;

    quickspline_get_point(s, &q, t, basis);
    out->x = q.x;
    out->y = q.y;
    out->z = q.z;
    out->pad = q.w;
}

// tCubic1D's inline SetVal, SetdVal and SetValDesired: the store, then a
// new seek when it differs from its partner.
static void cubic_set_val(BSpline *c, float f)
{
    c->val = f;
    if (f != c->valDesired)
        c->state = 2;
}

static void cubic_set_dval(BSpline *c, float f)
{
    c->dval = f;
    if (f != c->dvalDesired)
        c->state = 2;
}

static void cubic_set_val_desired(BSpline *c, float f)
{
    c->valDesired = f;
    if (f != c->val)
        c->state = 2;
}

// The tCubic1D constructor, inline in BeltMover's: the four values 0, flags
// 1, duration and threshold 1, state 0. The time and the coefficients are
// left as bMalloc gave them; the first seek is a new one and writes both.
static void cubic_init(BSpline *c)
{
    c->val = 0.0f;
    c->dval = 0.0f;
    c->valDesired = 0.0f;
    c->dvalDesired = 0.0f;
    c->flags = 1;
    c->duration = 1.0f;
    c->arrivalThreshold = 1.0f;
    c->state = 0;
}

// The driver's GetDesiredSpeed (136) and GetDesiredTimeToSpeed (144).
typedef float (*DriverFloatFn)(void *self);

static float driver_float(CarDriver *d, int32_t slot)
{
    const VtEntry *e = vt_slot(d->_vtable, slot);

    return ((DriverFloatFn)e->fn)(vt_this(d, e));
}

#define BM_VT_GET_DESIRED_TIME_TO_SPEED 144

// ------------------------------------------------------------ the class

BeltMover *beltmover_init(BeltMover *m, Car *car)
{
    const CarTypeInfo *cti;
    const CarState *cs;
    BSpline2D *c2;
    bVector2 val, dval;
    float s, lat;
    uint16_t a, b;
    int32_t i;

    m->pCar = car;
    m->ddv = 0.0f;
    m->dv = 0.0f;
    m->v = 0.0f;
    m->fScale = 0.0f;
    m->fTime = 0.0f;
    m->bSliding = 0;
    m->Mover._vtable = BELTMOVER_VTABLE;

    m->pAvgAccel = average_init(
        (Average *)bMalloc((int)sizeof(Average), BELTMOVER_FILE, 124,
                           CAR_MEMORY_POOL), 30);
    m->pSpline = quickspline_init(
        (QuickSpline *)bMalloc((int)sizeof(QuickSpline), BELTMOVER_FILE, 126,
                               CAR_MEMORY_POOL),
        QUICKSPLINE_EXTRAPOLATED, QUICKSPLINE_OVERHAUSER, 20);

    m->pCubicU = (BSpline *)bMalloc((int)sizeof(BSpline), BELTMOVER_FILE, 127,
                                    CAR_MEMORY_POOL);
    cubic_init(m->pCubicU);
    c2 = (BSpline2D *)bMalloc((int)sizeof(BSpline2D), BELTMOVER_FILE, 128,
                              CAR_MEMORY_POOL);
    cubic_init(&c2->x);
    cubic_init(&c2->y);
    m->pCubicAng = c2;
    c2 = (BSpline2D *)bMalloc((int)sizeof(BSpline2D), BELTMOVER_FILE, 129,
                              CAR_MEMORY_POOL);
    cubic_init(&c2->x);
    cubic_init(&c2->y);
    m->pCubicSlide = c2;

    // The heading's cubic starts on the car's velocity along its heading,
    // turning at the speed times the yaw rate. The image divides 360 by
    // nothing on the way (`beql a2,zero ; break`, with a2 360): a check the
    // compiler left and nothing reaches.
    cs = &m->pCar->State;
    s = cs->VelocityMagnitude;
    a = cs->Angle;
    lat = s * (cs->AngularVelocity.z * BM_SPIN_SCALE);
    b = (uint16_t)(cs->Angle + 16384);
    val.x = s * bCosBam(a);
    val.y = s * bSinBam(a);
    dval.x = lat * bCosBam(b);
    dval.y = lat * bSinBam(b);
    bspline2d_set_val(m->pCubicAng, &val);
    bspline2d_set_dval(m->pCubicAng, &dval);

    m->pCubicSlide->y.duration = BM_SLIDE_DURATION;
    m->pCubicSlide->x.duration = BM_SLIDE_DURATION;

    // Wheel's operator new is `bOMalloc` on its pool, the WheelSlotPool.
    cti = m->pCar->pCarTypeInfo;
    for (i = 0; i < 4; i++)
        m->pWheels[i] = wheel_init(wheel_new(), &cti->Wheels[i],
                                   &cti->Tires[i / 2], &cti->Control,
                                   &m->pCar->State);

    beltmover_clear_calculated_variables(m);
    return m;
}

CarMover *beltmover_construct(void *mem, Car *car)
{
    return &beltmover_init((BeltMover *)mem, car)->Mover;
}

void beltmover_destroy(BeltMover *m, int32_t flags)
{
    int32_t i;

    m->Mover._vtable = BELTMOVER_VTABLE;
    if (m->pAvgAccel != NULL)
        average_destroy(m->pAvgAccel, 3);
    if (m->pSpline != NULL)
        quickspline_destroy(m->pSpline, 3);

    // `__builtin_delete`, which is bFree, on each, unchecked.
    bFree(m->pCubicU);
    bFree(m->pCubicAng);
    bFree(m->pCubicSlide);

    // The pointers are left as they were.
    for (i = 0; i < 4; i++) {
        Wheel *w = m->pWheels[i];
        if (w != NULL) {
            const VtEntry *e = vt_slot(w->_vtable, PHYSICSCOMPONENT_VT_DTOR);
            ((PhysicsDtorFn)e->fn)(vt_this(w, e), 3);
        }
    }

    // `j _$_8CarMover` with this call's flags: the delete is CarMover's.
    carmover_destroy(&m->Mover, flags);
}

void beltmover_clear_calculated_variables(BeltMover *m)
{
    (void)m;
}

float beltmover_dot(BeltMover *m, const bVector3 *pos, bVector3 *a,
                    bVector3 *b, float t)
{
    spline_point(m->pSpline, a, t, 0);
    spline_point(m->pSpline, b, t, 1);
    a->x = a->x - pos->x;
    a->y = a->y - pos->y;
    a->z = a->z - pos->z;
    a->pad = a->pad - pos->pad;
    return dot3(a, b);
}

float beltmover_get_acceleration_due_to_gravity(BeltMover *m)
{
    bVector3 t;

    if (m->pSpline->NumControlPoints == 0)
        return 0.0f;
    spline_point(m->pSpline, &t, m->v, 1);
    normalize4(&t);
    return -BM_GRAVITY * t.z;
}

float beltmover_get_maximum_acceleration(BeltMover *m)
{
    return ai_calculate_max_acceleration(m->pCar, ee_div(m->dv, m->fScale));
}

void beltmover_find_coordinates(BeltMover *m)
{
    CarDriver *drv = m->pCar->pCarDriver;
    bVector3 a, b, up, side;
    float t, f, mx, da, dvel;
    int32_t i;

    // A DriveTarget with no length -- no points, or all on one spot --
    // makes the scale the EE's quotient.
    m->fTime = 0.0f;
    m->fScale = ee_div((float)m->pSpline->NumControlPoints,
                       drv->MyDriveTarget.Length);

    i = quickspline_find_closest_control_point_from(m->pSpline,
                                                    &m->pCar->State.Position,
                                                    0);
    t = quickspline_find_closest_param(m->pSpline, &m->pCar->State.Position,
                                       (float)i, BM_PARAM_TOLERANCE);
    beltmover_dot(m, &m->pCar->State.Position, &a, &b, t);
    m->v = t;
    normalize4(&b);

    m->dv = m->fScale * m->pCar->State.VelocityMagnitude;
    f = (m->fScale * driver_float(drv, CARDRIVER_VT_GET_DESIRED_SPEED))
        * BM_SPEED_FRACTION - m->dv;
    if (0.0f < driver_float(drv, BM_VT_GET_DESIRED_TIME_TO_SPEED))
        m->ddv = f / driver_float(drv, BM_VT_GET_DESIRED_TIME_TO_SPEED);
    else
        m->ddv = f / 0.5f;

    mx = m->fScale * beltmover_get_maximum_acceleration(m);
    if (mx < m->ddv) {
        m->ddv = mx;
    } else {
        mx = m->fScale * -20.0f;
        if (m->ddv < mx)
            m->ddv = mx;
    }

    // The image stores three words of `up` and leaves the fourth to the
    // stack; the cross product keeps the tangent's w, so it is never read.
    up.x = 0.0f;
    up.y = 0.0f;
    up.z = 1.0f;
    up.pad = 0.0f;
    cross3(&side, &b, &up);
    da = dot3(&a, &side);
    dvel = dot3(&m->pCar->State.Velocity, &side);

    cubic_set_val(m->pCubicU, -da);
    cubic_set_dval(m->pCubicU, dvel * 0.5f);
    m->pCubicU->duration = 0.5f;
    m->pCubicAng->y.duration = BM_ANGLE_DURATION;
    m->pCubicAng->x.duration = BM_ANGLE_DURATION;
}

void beltmover_set_belt(BeltMover *m)
{
    DriveTarget *dt = &m->pCar->pCarDriver->MyDriveTarget;
    int32_t i;

    m->pCubicU->flags = 0;
    drivetarget_resample(dt, m->pCar);
    quickspline_set_num_control_points(m->pSpline, dt->NumPoints);
    for (i = 0; i < dt->NumPoints; i++) {
        QuickSpline *s = m->pSpline;
        bVector4 *cp = &s->pControlPoints[i];

        cp->x = dt->Points[i].x;
        cp->y = dt->Points[i].y;
        cp->z = dt->Points[i].z;
        cp->w = 0.0f;
        s->ControlPointsDirty = 1;
    }
    beltmover_find_coordinates(m);
}

float beltmover_slide_coef(BeltMover *m, float accel)
{
    const CarTypeInfo *cti = m->pCar->pCarTypeInfo;
    const TireInfo *front = &cti->Tires[0];
    const TireInfo *rear = &cti->Tires[1];
    float mag, sign, need, down, grip, hold;
    Graph *g;
    bVector2 *p;
    int32_t sliding;

    // A belt as straight as a ruler averages no sideways acceleration at
    // all, and the sign is the EE's 0/0.
    mag = fabsf(accel);
    sign = ee_div(accel, mag);
    need = (cti->Body.Mass * mag)
           * ((rear->ForceScale + front->ForceScale) * 0.5f);
    down = ee_div(m->dv, m->fScale)
           * ((cti->Aero.FrontDownforce + cti->Aero.RearDownforce) * 0.5f);
    if (m->bSliding)
        grip = (rear->DynamicFrictionCoefficient
                + front->DynamicFrictionCoefficient) * 0.5f;
    else
        grip = (rear->StaticFrictionCoefficient
                + front->StaticFrictionCoefficient) * 0.5f;

    // The Graph is picked by the flag as it was on the way in.
    g = m->bSliding ? &BeltSlidingGraph : &BeltSlideGraph;
    hold = (down + BM_GRAVITY * cti->Body.Mass) * grip;
    p = (bVector2 *)g->pPoints;
    p[1].x = hold * BM_KNEE_LOW;
    p[2].x = hold * BM_KNEE_HIGH;
    p[3].x = hold * 1.5f;

    sliding = (hold < need);
    if (m->bSliding != sliding) {
        if (sliding) {
            m->pCubicSlide->y.duration = 1.0f;
            m->pCubicSlide->x.duration = 1.0f;
        } else {
            bVector2 d;

            m->pCubicSlide->y.duration = BM_SLIDE_END_DURATION;
            m->pCubicSlide->x.duration = BM_SLIDE_END_DURATION;
            bspline2d_get_dval(m->pCubicSlide, &d);
            d.x = d.x * BM_SLIDE_END_RATE;
            d.y = d.y * BM_SLIDE_END_RATE;
            bspline2d_set_dval(m->pCubicSlide, &d);
        }
        m->bSliding = sliding;
    }
    return sign * graph_get_value(g, need);
}

float beltmover_average_air(BeltMover *m, float dt)
{
    const CarTypeInfo *cti = m->pCar->pCarTypeInfo;
    bVector3 p, d;
    float g, ng, sum, last, pz, dz;
    int32_t i;

    // The car falls at 9.8 plus what the downforce at its speed adds.
    g = ee_div(m->dv, m->fScale)
        * ((cti->Aero.FrontDownforce + cti->Aero.RearDownforce) * 0.5f);
    g = g / cti->Body.Mass + BM_GRAVITY;

    beltmover_get_point(m, &p, m->fTime);
    beltmover_get_derivative(m, &d, m->fTime);
    ng = -g;
    pz = p.z;
    dz = d.z;
    sum = 0.0f;
    last = 0.0f;
    for (i = 1; i < 10; i++) {
        float s = (dt * (float)i) * BM_AIR_STEP;
        float tau = s - last;
        float t = m->fTime + s;
        float z = tau * (tau * ng + dz) + pz;
        float h;

        beltmover_get_point(m, &p, t);
        h = z - p.z;
        if (0.0f < h) {
            sum = sum + h;
        } else {
            // Back on the belt: the next throw starts here.
            beltmover_get_derivative(m, &d, t);
            last = s;
            pz = p.z;
            dz = d.z;
        }
    }
    return sum * BM_AIR_SCALE;
}

float beltmover_move(BeltMover *m, float dt)
{
    Car *car;
    CarState *cs;
    const CarTypeInfo *cti;
    bVector3 old, d, up, side, dd, s, pos, vel;
    bVector2 xy;
    float speed, slide, k, mag, lng, lat, t;
    uint16_t newA, oldA;
    int32_t i;

    if (m->pSpline->NumControlPoints < 2)
        beltmover_set_belt(m);

    car = m->pCar;
    cs = &car->State;
    old = car->State.Position;

    // Leaving the belt's ground: the controller keeps the car off the
    // belt for 0.6 s (Timer::SetTime(0.6), folded).
    if (BM_AIR_THRESHOLD < beltmover_average_air(m, 0.5f))
        car_ai_controller(m->pCar)->OffBeltTimer.PackedTime =
            (uint32_t)ee_trunc_w(BM_OFF_BELT_TICKS);

    m->fTime = m->fTime + dt;
    speed = ee_div(m->dv + m->ddv * m->fTime, m->fScale);

    // The heading: the tangent half a second on, eased.
    beltmover_get_derivative(m, &d, m->fTime + 0.5f);
    xy.x = d.x;
    xy.y = d.y;
    bspline2d_set_val_desired(m->pCubicAng, &xy);
    bspline2d_seek(m->pCubicAng, dt);
    bspline2d_get_val(m->pCubicAng, &xy);
    d.x = xy.x;
    d.y = xy.y;

    // The slide: across the belt 0.3 s on, by how hard it turns there.
    // The image's `up` leaves its w to the stack, which the cross products
    // never read.
    t = m->fTime + BM_SLIDE_LOOK_AHEAD;
    up.x = 0.0f;
    up.y = 0.0f;
    up.z = 1.0f;
    up.pad = 0.0f;
    beltmover_get_derivative(m, &dd, t);
    cross3(&side, &dd, &up);
    normalize4(&side);
    beltmover_get_second_derivative(m, &dd, t);
    average_record(m->pAvgAccel, dot3(&side, &dd));

    // GetddVal of the across-belt cubic, at its own time, and the answer
    // dropped.
    (void)bspline_get_ddval(m->pCubicU,
                            m->pCubicU->time / m->pCubicU->duration);

    slide = beltmover_slide_coef(m, m->pAvgAccel->fAverage);
    k = speed * (slide * BM_SLIDE_LOOK_AHEAD);
    scale4(&s, &side, k);
    xy.x = s.x;
    xy.y = s.y;
    bspline2d_set_val_desired(m->pCubicSlide, &xy);
    bspline2d_seek(m->pCubicSlide, dt);
    bspline2d_get_val(m->pCubicSlide, &xy);
    s.x = xy.x;
    s.y = xy.y;

    d.x = d.x + s.x;
    d.y = d.y + s.y;
    d.z = d.z + s.z;
    d.pad = d.pad + s.pad;
    newA = (uint16_t)bATan(d.x, d.y);
    oldA = cs->Angle;
    cs->Angle = newA;

    // Across the belt, by the cubic the slide steers.
    beltmover_get_derivative(m, &dd, m->fTime);
    cross3(&side, &dd, &up);
    normalize4(&side);
    cubic_set_val_desired(m->pCubicU, -slide);
    bspline_seek(m->pCubicU, dt);
    k = m->pCubicU->val;
    beltmover_get_point(m, &pos, m->fTime);
    scale4(&side, &side, k);
    pos.x = side.x + pos.x;
    pos.y = side.y + pos.y;
    pos.z = side.z + pos.z;
    pos.pad = side.pad + pos.pad;
    car->State.Position = pos;
    car_put_flat_on_track(m->pCar);
    carstate_calculate_geometry_position(cs);

    // The yaw rate from the heading's change. The image's fourth word is
    // the stack's; the port's is 0.
    car->State.AngularVelocity.x = 0.0f;
    car->State.AngularVelocity.y = 0.0f;
    car->State.AngularVelocity.z =
        ee_div((float)(int16_t)(uint16_t)(newA - oldA) * BM_BAM_TO_RAD, dt);
    car->State.AngularVelocity.pad = 0.0f;

    vel.x = m->pCar->State.Position.x - old.x;
    vel.y = m->pCar->State.Position.y - old.y;
    vel.z = m->pCar->State.Position.z - old.z;
    vel.pad = m->pCar->State.Position.pad - old.pad;
    if (fabsf(dt) <= BM_MIN_DT)
        bNormalize3To(&vel, &vel, speed);
    else
        scale4(&vel, &vel, 1.0f / dt);
    cs->Velocity = vel;
    mag = sqrtf(dot3(&vel, &vel));
    cs->ForwardSpeed = mag;
    cs->VelocityMagnitude = mag;
    cs->MatrixValid = 0;

    // Every wheel turns at the belt's speed, with the slip the body has
    // against its velocity.
    lng = speed - dot3(&vel, (const bVector3 *)(const void *)
                              &m->pCar->State.BodyMatrix.v0);
    lat = -dot3(&vel, (const bVector3 *)(const void *)
                      &m->pCar->State.BodyMatrix.v1);
    cti = m->pCar->pCarTypeInfo;
    for (i = 0; i < 4; i++) {
        Wheel *w = m->pWheels[i];
        float angle, steer;

        angle = cs->WheelAngle[i] + cs->WheelAngularVelocity[i] * m->fTime;
        steer = 0.0f;
        if (w->WI->WheelNumber < 2)
            steer = (float)m->pCar->pCarDriver->Steering;
        wheel_set_state_from_car_state(w, cs, (void *)cti, angle,
                                       speed / cti->Wheels[i].Radius,
                                       (uint16_t)ee_trunc_w(steer), 0.0f);

        w = m->pWheels[i];
        cs->WheelSlip[i].x = lng;
        cs->WheelSlip[i].y = lat;
        cs->WheelTractionUsage[i] = 0.0f;
        if (!(w->WI->WheelNumber < 2)) {
            w->Slip[0] = lng;
            w->Slip[1] = lat;
            w->Slipping = (uint8_t)m->bSliding;
            w->CurrentSlip = lng;
        }
    }

    if (car_should_visual_effects_be_generated(m->pCar)
        && world_get_distance_to_closest_player(pCurrentWorld,
                                                &m->pCar->State.Position)
           < 200.0f)
        for (i = 0; i < 4; i++)
            wheel_maybe_make_skids(m->pWheels[i], m->pCar, dt);

    car_compute_fake_rpm(m->pCar);
    return dt;
}

bVector3 *beltmover_get_point(BeltMover *m, bVector3 *out, float t)
{
    float u = t * (t * m->ddv + m->dv) + m->v;

    spline_point(m->pSpline, out, u, 0);

    // Before the first control point the belt is held up to it.
    if (u < 0.0f) {
        float z0 = m->pSpline->pControlPoints[0].z;
        if (out->z < z0)
            out->z = z0;
    }
    return out;
}

bVector3 *beltmover_get_derivative(BeltMover *m, bVector3 *out, float t)
{
    float du = (t + t) * m->ddv + m->dv;
    float u = t * (t * m->ddv + m->dv) + m->v;

    spline_point(m->pSpline, out, u, 1);
    scale4(out, out, du);
    return out;
}

bVector3 *beltmover_get_second_derivative(BeltMover *m, bVector3 *out,
                                          float t)
{
    float dd = m->ddv + m->ddv;
    float du = (t + t) * m->ddv + m->dv;
    float u = t * (t * m->ddv + m->dv) + m->v;
    bVector3 a, b;

    spline_point(m->pSpline, &a, u, 1);
    scale4(&a, &a, dd);
    spline_point(m->pSpline, &b, u, 2);
    scale4(&b, &b, du * du);
    out->x = a.x + b.x;
    out->y = a.y + b.y;
    out->z = a.z + b.z;
    out->pad = a.pad + b.pad;
    return out;
}

// ------------------------------------------------------------- the replay

void beltmover_do_snapshot(BeltMover *m, ReplaySnapshot *s)
{
    // 0x00204468. The three cubics go as their raw records, the spline as
    // three floats a point, and ClearCalculatedVariables (`jr ra`) runs
    // when taking or restoring.
    int32_t i;

    ReplaySnapshot_BeginNamedSection(s, "BeltMover");
    carmover_do_snapshot(&m->Mover, s);
    ReplaySnapshot_MoveFloat(s, &m->v);
    ReplaySnapshot_MoveFloat(s, &m->dv);
    ReplaySnapshot_MoveFloat(s, &m->ddv);
    ReplaySnapshot_MoveFloat(s, &m->fTime);
    ReplaySnapshot_MoveFloat(s, &m->fScale);
    ReplaySnapshot_MoveBool(s, &m->bSliding, 1);
    ReplaySnapshot_MoveData(s, m->pCubicU, 48, -1, 0);
    ReplaySnapshot_MoveData(s, m->pCubicAng, 96, -1, 0);
    ReplaySnapshot_MoveData(s, m->pCubicSlide, 96, -1, 0);
    quickspline_do_snapshot(m->pSpline, s, 3);
    average_do_snapshot(m->pAvgAccel, s);
    for (i = 0; i < 4; i++)
        wheel_do_snapshot(m->pWheels[i], s);
    if (s->TakingSnapshotFlag || s->RestoringSnapshotFlag)
        beltmover_clear_calculated_variables(m);
    ReplaySnapshot_EndNamedSection(s);
}

// ------------------------------------------------------------ the entries

static void vt_BeltMover_dtor(void *self, int32_t flags)
{
    beltmover_destroy((BeltMover *)self, flags);
}

static float vt_BeltMover_Move(void *self, float dt)
{
    return beltmover_move((BeltMover *)self, dt);
}

static const VtEntry beltmover_vt[BELTMOVER_VT_ENTRIES] = {
    { 0, 0, NULL },
    { 0, 0, (VtFn)vt_BeltMover_dtor },     //  8  0x002043a0
    { 0, 0, (VtFn)vt_BeltMover_Move },     // 16  0x00204d78
    { 0, 0, (VtFn)beltmover_do_snapshot }, // 24  0x00204468
};

void beltmover_install_vtables(void)
{
    vt_install(BELTMOVER_VTABLE, beltmover_vt, BELTMOVER_VT_ENTRIES);
}

static void set_belt_seam(CarMover *m)
{
    beltmover_set_belt((BeltMover *)(void *)m);
}

static float gravity_seam(CarMover *m)
{
    return beltmover_get_acceleration_due_to_gravity((BeltMover *)(void *)m);
}

void beltmover_install_seams(void)
{
    gBeltMoverCtorFn = beltmover_construct;
    gBeltMoverSetBeltFn = set_belt_seam;
    gBeltMoverGravityFn = gravity_seam;
}
