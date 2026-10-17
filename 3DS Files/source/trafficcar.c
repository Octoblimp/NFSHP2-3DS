// trafficcar -- see trafficcar.h.

#include "trafficcar.h"

#include <math.h>
#include <stddef.h>

#include "bmath.h"
#include "cardriver.h"
#include "carmodes.h"          // gTrafficCarCtorFn
#include "carstate.h"
#include "cartypeinfo.h"
#include "eefpu.h"
#include "replay.h"
#include "vtable.h"

// ------------------------------------------------------------ the tuning

// The .lit4 constants, gp-30556 .. gp-30516. tools/trafficcar_check.py
// reads each back out of the pool.
#define TC_BAM_TO_RAD      9.58738e-05f    // gp-30556  38c90fdb  (and -30548)
#define TC_HALF_PI         1.5707965f      // gp-30552  3fc90fdc  (and -30532)
#define TC_PI              3.14159f        // gp-30544  40490fd0
#define TC_TWO_PI          6.28318f        // gp-30540  40c90fd0
#define TC_STRAIGHT        0.01f           // gp-30536  3c23d70a
#define TC_MAX_SPEED       24.5865f        // gp-30528  41c4b127  (and -30516)
#define TC_RAD_TO_BAM      10430.378f      // gp-30524  4622f983
#define TC_YAW_BAM_TO_RAD  9.5873795e-05f  // gp-30520  38c90fda

// The Tables' data, retail 0x002fad40, 0x002fad68 and 0x002fad90, with the
// image's bits: a gentler push the faster the car goes, a harder brake,
// and the distance it takes to stop.
static const float TrafficAccelerationTable[4] = {
    3.5762181f, 2.6821637f, 2.0116227f, 1.3410819f,  // 4064e0c2 402ba892 ...
};
static const float TrafficBrakingTable[4] = {
    6.705409f, 13.410818f, 20.116226f, 26.821636f,   // 40d692b6 415692b6 ...
};
static const float StoppingDistanceBySpeed[61] = {
    0.0f, 0.018f, 0.063f, 0.133f, 0.225f,            // 00000000 3c9374bc ...
    0.337f, 0.468f, 0.617f, 0.783f, 0.963f,
    1.157f, 1.365f, 1.585f, 1.816f, 2.059f,
    2.312f, 2.574f, 2.845f, 3.125f, 3.414f,
    3.71f, 4.013f, 4.324f, 4.641f, 4.965f,
    5.295f, 5.63f, 5.972f, 6.318f, 6.67f,
    7.027f, 7.388f, 7.754f, 8.125f, 8.499f,
    8.878f, 9.26f, 9.647f, 10.037f, 10.43f,
    10.827f, 11.228f, 11.631f, 12.037f, 12.447f,
    12.859f, 13.274f, 13.692f, 14.113f, 14.536f,
    14.962f, 15.39f, 15.82f, 16.253f, 16.687f,
    17.124f, 17.564f, 18.005f, 18.448f, 18.893f,
    19.34f,
};

Table TrafficAcceleration;
Table TrafficBraking;
Table StoppingDistanceTable;

void trafficcar_static_init(void)
{
    // 0x00167fe0, the demo's 0x001635f0.
    table_init(&TrafficAcceleration, TrafficAccelerationTable, 4, 0.0f,
               TC_MAX_SPEED);
    table_init(&TrafficBraking, TrafficBrakingTable, 4, 0.0f, TC_MAX_SPEED);
    table_init(&StoppingDistanceTable, StoppingDistanceBySpeed, 61, 0.0f,
               TC_MAX_SPEED);
}

// ------------------------------------------------------------ the class

TrafficCar *trafficcar_init(TrafficCar *m, Car *car)
{
    m->Mover._vtable = TRAFFICCAR_VTABLE;
    m->pCar = car;
    m->Position.x = car->State.Position.x;
    m->Position.y = car->State.Position.y;
    m->Angle = (float)(int32_t)car->State.Angle * TC_BAM_TO_RAD;
    m->Speed = car->State.VelocityMagnitude;
    m->Pitch = 0.0f;
    m->Roll = 0.0f;
    return m;
}

CarMover *trafficcar_construct(void *mem, Car *car)
{
    return &trafficcar_init((TrafficCar *)mem, car)->Mover;
}

void trafficcar_destroy(TrafficCar *m, int32_t flags)
{
    m->Mover._vtable = TRAFFICCAR_VTABLE;
    // `j _$_8CarMover` with this call's flags: the delete is CarMover's.
    carmover_destroy(&m->Mover, flags);
}

float trafficcar_move(TrafficCar *m, float dt)
{
    Car *car;
    CarState *cs;
    const CarTypeInfo *cti;
    CarDriver *drv;
    bVector2 fwd, side, front, center;
    bVector3 old, pos, vel;
    float wb, rear, dist, steer, limit, r, turn, c, s, rx, ry, nx, ny;
    float push, brake, speed, w;
    uint16_t newA, oldA;
    int32_t i, k;

    cti = m->pCar->pCarTypeInfo;
    dist = m->Speed * dt;
    rear = cti->Wheels[3].PositionX;
    wb = cti->Wheels[0].PositionX + -rear;

    // The heading, and to its left.
    c = bSinF(m->Angle + TC_HALF_PI);
    s = bSinF(m->Angle);
    fwd.x = c;
    fwd.y = s;
    side.x = -s;
    side.y = c;

    // The steering as an angle, -pi .. pi.
    steer = (float)(int32_t)car_get_steering(m->pCar) * TC_BAM_TO_RAD;
    if (TC_PI < steer)
        steer = steer - TC_TWO_PI;

    limit = wb * TC_STRAIGHT;
    if (steer < limit && -limit < steer) {
        // Nearly straight: on along the heading.
        m->Position.x = m->Position.x + fwd.x * dist;
        m->Position.y = m->Position.y + fwd.y * dist;
    } else {
        // Round the circle of radius wheelbase / steer, whose centre is
        // that far to the left of the rear axle: `rear` (Wheels[3]'s x,
        // below 0 on every car) along the heading.
        r = ee_div(wb, steer);
        bScaleAdd2(&front, &m->Position, &fwd, rear);
        turn = ee_div(dist, r);
        bScaleAdd2(&center, &front, &side, r);
        c = bSinF(turn + TC_HALF_PI);
        s = bSinF(turn);
        rx = m->Position.x - center.x;
        ry = m->Position.y - center.y;
        nx = c * rx - s * ry;
        ny = s * rx + c * ry;
        m->Position.x = center.x + nx;
        m->Position.y = center.y + ny;
        m->Angle = m->Angle + turn;
    }

    // The pedals, through the Tables, and the speed held to 0 .. 55 mph.
    drv = m->Mover.Driver;
    push = (dt * drv->Throttle)
           * table_get_value(&TrafficAcceleration, m->Speed);
    brake = (dt * drv->Brake) * table_get_value(&TrafficBraking, m->Speed);
    speed = m->Speed + (push - brake);
    m->Speed = speed;
    if (speed < 0.0f)
        m->Speed = 0.0f;
    else if (TC_MAX_SPEED < speed)
        m->Speed = TC_MAX_SPEED;

    // The car where the mover has it, at the height it had, then down
    // onto the road. The image's fourth word is a stack word Move never
    // writes; the port keeps the old one.
    car = m->pCar;
    cs = &car->State;
    old = cs->Position;
    pos.x = m->Position.x;
    pos.y = m->Position.y;
    pos.z = old.z;
    pos.pad = old.pad;
    cs->Position = pos;
    car_put_flat_on_track(m->pCar);

    // The velocity: the step, the speed long. bNormalize writes x, y and
    // z, so its fourth lane is the step's.
    vel.x = cs->Position.x - old.x;
    vel.y = cs->Position.y - old.y;
    vel.z = cs->Position.z - old.z;
    vel.pad = cs->Position.pad - old.pad;
    bNormalize3To(&vel, &vel, m->Speed);
    cs->Velocity = vel;
    cs->VelocityMagnitude = sqrtf((vel.x * vel.x + vel.y * vel.y)
                                  + vel.z * vel.z);
    cs->ForwardSpeed = m->Speed;
    oldA = cs->Angle;
    cs->MatrixValid = 0;

    // The heading in BAM, and the yaw rate from its change. The image's
    // fourth word is the stack's; the port's is 0.
    newA = (uint16_t)ee_trunc_w(m->Angle * TC_RAD_TO_BAM);
    cs->Angle = newA;
    cs->AngularVelocity.x = 0.0f;
    cs->AngularVelocity.y = 0.0f;
    cs->AngularVelocity.z = ee_div(
        (float)(int16_t)(uint16_t)(newA - oldA) * TC_YAW_BAM_TO_RAD, dt);
    cs->AngularVelocity.pad = 0.0f;
    cs->SteeringAngle = car_get_steering(m->pCar);

    // Every wheel rolls at the speed, on the road, with nothing on it.
    // The image clears all four bottom-out magnitudes each time round.
    for (i = 0; i < 4; i++) {
        w = ee_div(m->Speed, cti->Wheels[i].Radius);
        cs->WheelAngularVelocity[i] = w;
        cs->WheelAngle[i] = cs->WheelAngle[i] + w * dt;
        cs->WheelSuspensionHeight[i] = 0.0f;
        carstate_set_wheel_touching_ground(cs, i, 1);
        carstate_set_wheel_terrain(cs, i, TERRAIN_DEFAULT);
        cs->WheelSlip[i].x = 0.0f;
        cs->WheelSlip[i].y = 0.0f;
        cs->WheelTractionUsage[i] = 0.0f;
        cs->WheelZForce[i] = 0.0f;
        for (k = 3; k >= 0; k--)
            cs->WheelBottomOutMagnitude[k] = 0.0f;
    }

    carstate_calculate_wheel_matrices(cs);
    carstate_calculate_geometry_position(cs);
    car_compute_fake_rpm(m->pCar);
    return dt;
}

float trafficcar_calculate_stop_distance(TrafficCar *m, float unused,
                                         float speed)
{
    (void)m;
    (void)unused;
    return table_get_value(&StoppingDistanceTable, speed);
}

// ------------------------------------------------------------ the entries

static void vt_TrafficCar_dtor(void *self, int32_t flags)
{
    trafficcar_destroy((TrafficCar *)self, flags);
}

static float vt_TrafficCar_Move(void *self, float dt)
{
    return trafficcar_move((TrafficCar *)self, dt);
}

void trafficcar_do_snapshot(TrafficCar *m, ReplaySnapshot *s)
{
    ReplaySnapshot_BeginNamedSection(s, "TrafficCar");
    ReplaySnapshot_MoveData(s, &m->Position, 8, -1, 0);
    ReplaySnapshot_MoveFloat(s, &m->Angle);
    ReplaySnapshot_MoveFloat(s, &m->Speed);
    ReplaySnapshot_MoveFloat(s, &m->Pitch);
    ReplaySnapshot_MoveFloat(s, &m->Roll);
    carmover_do_snapshot(&m->Mover, s);
    ReplaySnapshot_EndSection(s);
}

static const VtEntry trafficcar_vt[TRAFFICCAR_VT_ENTRIES] = {
    { 0, 0, NULL },
    { 0, 0, (VtFn)vt_TrafficCar_dtor },     //  8  0x00168088
    { 0, 0, (VtFn)vt_TrafficCar_Move },     // 16  0x00167af8
    { 0, 0, (VtFn)trafficcar_do_snapshot }, // 24  0x00167a60
};

void trafficcar_install_vtables(void)
{
    vt_install(TRAFFICCAR_VTABLE, trafficcar_vt, TRAFFICCAR_VT_ENTRIES);
}

void trafficcar_install_seams(void)
{
    gTrafficCarCtorFn = trafficcar_construct;
}
