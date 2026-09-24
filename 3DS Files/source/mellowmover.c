// mellowmover -- see mellowmover.h.

#include "mellowmover.h"

#include <math.h>
#include <stddef.h>

#include "bmath.h"
#include "bmatrix.h"
#include "bticker.h"
#include "bvector.h"
#include "eefpu.h"
#include "emath.h"
#include "physcomp.h"
#include "suspension.h"   // gUglyTimestepHack, gGroundPenaltyImpulse
#include "vtable.h"

// ------------------------------------------------------------ the tuning

Graph MellowForceFeedbackGraph;               // 0x00324a38  the initialiser's
float MaxiMellowTimeStep = 0.0084f;           // 0x00324a40  3c09a027
Graph MellowJumpStabilization;                // 0x00324a48  the initialiser's

// 0x00327858 (.bss) and 0x00313c48 (.data, overwritten), which the two
// Graphs alias.
static bVector2 MellowForceFeedbackData[2];
static bVector2 MellowJumpStabilizationGraph[3];

// 0x00313c60. Each wheel's partner across its axle.
static const int32_t SwayBarTable[4] = { 1, 0, 3, 2 };

// The .lit4 constants, gp-27792 .. gp-27724. HALF_PI is not the float
// nearest pi/2 but the one above it, and a one-ulp slip in either of the
// angle constants moves a wheel's heading far enough to move bSin's
// truncated angle by one: tools/mellowmover_check.py reads every one of
// these back out of the pool.
#define MV_MS_TO_MPH          2.237f              // gp-27792  400f2b02
#define MV_HIGH_SPEED_FRICTION 0.7f               // gp-27788  3f333333
#define MV_UPRIGHT            0.1f                // gp-27784  3dcccccd
#define MV_GRAVITY            9.8f                // gp-27780  411ccccd
#define MV_IDLE_THROTTLE      0.05f               // gp-27776  3d4ccccd
#define MV_SPIN_SCALE         124.99999237060547f // gp-27772  42f9ffff
#define MV_LOCK_BRAKE         0.95f               // gp-27768  3f733333
#define MV_UNLOCK_BRAKE       0.2f                // gp-27764  3e4ccccd
#define MV_RADS_TO_RPM_HALF   4.774652004241943f  // gp-27760  4098c9f3, 15/pi
#define MV_MIN_COS            0.001f              // gp-27756  3a83126f
#define MV_MIN_DT             0.0001f             // gp-27752  38d1b717
#define MV_BAM_TO_RAD         9.58738019107841e-05f // gp-27748 38c90fdb
#define MV_HALF_PI            1.5707964897155762f // gp-27744  3fc90fdc
#define MV_SLIP_KNEE          0.05f               // gp-27740  3d4ccccd
#define MV_HOLD_BRAKE         0.4f                // gp-27736  3ecccccd
#define MV_HOLD_SPEED         0.1f                // gp-27732  3dcccccd
#define MV_FEEDBACK_Y0        0.4f                // gp-27728  3ecccccd
#define MV_JUMP_KNEE          0.1f                // gp-27724  3dcccccd

void mellowmover_static_init(void)
{
    MellowForceFeedbackData[0].x = 0.0f;
    MellowForceFeedbackData[0].y = MV_FEEDBACK_Y0;
    MellowForceFeedbackData[1].x = 20.0f;
    MellowForceFeedbackData[1].y = 0.5f;
    graph_init(&MellowForceFeedbackGraph, MellowForceFeedbackData, 2);

    MellowJumpStabilizationGraph[0].x = 0.0f;
    MellowJumpStabilizationGraph[0].y = 0.0f;
    MellowJumpStabilizationGraph[1].x = MV_JUMP_KNEE;
    MellowJumpStabilizationGraph[1].y = 0.0f;
    MellowJumpStabilizationGraph[2].y = 20.0f;
    MellowJumpStabilizationGraph[2].x = 2.0f;
    graph_init(&MellowJumpStabilization, MellowJumpStabilizationGraph, 3);
}

// --------------------------------------------------------- VU idioms

// `vmul.xyz ; vaddy.x ; vaddz.x`: (x*x + y*y) + z*z, left to right.
static float dot3(const void *a, const void *b)
{
    const float *p = (const float *)a;
    const float *q = (const float *)b;
    return (p[0] * q[0] + p[1] * q[1]) + p[2] * q[2];
}

static float len2(const void *v)
{
    return dot3(v, v);
}

// `vopmula.xyz ACC,vfA,vfB` / `vopmsub.xyz vfD,vfB,vfA`, A cross B. It
// writes xyz only, and each destination here is A's register, so the w
// lane is A's.
static void cross3(bVector4 *o, const bVector4 *a, const bVector4 *b)
{
    float x = a->y * b->z - b->y * a->z;
    float y = a->z * b->x - b->z * a->x;
    float z = a->x * b->y - b->x * a->y;
    o->x = x;
    o->y = y;
    o->z = z;
    o->w = a->w;
}

// `vrsqrt Q,vf00w,vf01x ; vaddq.x ; vmulx.xyzw`: all four lanes over the
// length of three. The VU divides a zero length the EE's way -- FLT_MAX --
// and a car falling straight down, with no speed across the ground, gives
// JumpStabilizer exactly that. So the divide is ee_div's.
static void normalize4(bVector4 *v)
{
    float inv = 0.0f + ee_div(1.0f, sqrtf(len2(v)));
    v->x = v->x * inv;
    v->y = v->y * inv;
    v->z = v->z * inv;
    v->w = v->w * inv;
}

static void quad_to3(bVector3 *o, const bVector4 *v)
{
    o->x = v->x;
    o->y = v->y;
    o->z = v->z;
    o->pad = v->w;
}

// `min.s` and `max.s`. No NaN reaches either, and the zero of either sign
// only ever feeds a product that is the same for both.
static float min_s(float a, float b)
{
    return (b < a) ? b : a;
}

static float max_s(float a, float b)
{
    return (a < b) ? b : a;
}

// `lqc2 vf1,272(cti) ; vsub.xyzw vf01,vf00,vf01 ; vadd.xyzw` with the
// wheel's record: the hub relative to the centre of gravity, in body frame.
// The four lanes are the four words of each, so w is (1 - CoG.pad) + Radius;
// both matrix routines this is fed to force w to 1 and never read it.
static void hub(bVector3 *o, const CarTypeInfo *cti, int32_t i)
{
    const bVector3 *c = &cti->CenterOfGravity;
    const WheelInfo *w = &cti->Wheels[i];

    o->x = (0.0f - c->x) + w->PositionX;
    o->y = (0.0f - c->y) + w->PositionY;
    o->z = (0.0f - c->z) + w->PositionZ;
    o->pad = (1.0f - c->pad) + w->Radius;
}

// GetElevation(TC, pos, NULL, normal, NULL), through wheel.h's seam. With
// no topology the ground is at 0 and straight up, as it is for Wheel.
static float ground(TopologyCoordinate *tc, const bVector3 *pos,
                    bVector3 *normal)
{
    if (gTopologyGetElevationFn != NULL)
        return gTopologyGetElevationFn(tc, pos, NULL, normal);
    normal->x = 0.0f;
    normal->y = 0.0f;
    normal->z = 1.0f;
    normal->pad = 0.0f;
    return 0.0f;
}

// 0x002076a0, `GetGearNumber(Gear)`: `addiu v0,a0,-1`.
static int32_t gear_number(Gear g)
{
    return g - 1;
}

// ------------------------------------------------------------ Mellovator

Mellovator *mellovator_new(void)
{
    return (Mellovator *)bSlotOMalloc(MellovatorSlotPool);
}

void mellovator_delete(void *p)
{
    bSlotFree(MellovatorSlotPool, p);
}

Mellovator *mellovator_init(Mellovator *m, const CarTypeInfo *cti,
                            RigidBody *body, TopologyCoordinate *tc)
{
    // Three bVector2/bVector3 array constructors come first in the image,
    // each a four-pass loop of nops: nothing is stored.
    m->_vtable = MELLOVATOR_VTABLE;
    table_init(&m->TorqueCurve, cti->Engine.TorqueCurveTable, 9,
               cti->Engine.IdleRPM, cti->Engine.MaxRPM);
    table_init(&m->EngineBraking, cti->Engine.EngineBrakingTable, 3,
               cti->Engine.IdleRPM, cti->Engine.MaxRPM);
    m->CTI = cti;
    drivetrain_calculate_shift_points(&cti->DriveTrain, &cti->Engine,
                                      m->ShiftUpRPM, m->ShiftDownRPM, 1.0f);
    m->pBody        = body;
    m->TC           = tc;
    m->CurrentBoost = 1.0f;
    m->CurrentGear  = FIRST_GEAR;
    return m;
}

void mellovator_destroy(Mellovator *m, int32_t flags)
{
    m->_vtable = MELLOVATOR_VTABLE;
    physicscomponent_fini(m);
    if (flags & 1)
        mellovator_delete(m);
}

void mellovator_calibrate(Mellovator *m, float downforce)
{
    const CarTypeInfo *cti = m->CTI;
    float cog, a, b, load, rear, front;

    cog = UseNewSuspensionCalibration ? cti->CenterOfGravity.x : 0.0f;
    a = cti->Wheels[0].PositionX - cog;
    b = cti->Wheels[3].PositionX - cog;

    load  = m->pBody->Mass * MV_GRAVITY
            + cti->Aero.AutoBalanceDownforce * downforce;
    rear  = (a / (a - b)) * 0.5f;
    front = 0.5f - rear;

    m->RestLoad[3] = load * rear;
    m->RestLoad[2] = load * rear;
    m->RestLoad[1] = load * front;
    m->RestLoad[0] = load * front;
}

void mellovator_set_state4(Mellovator *m, float w0, float w1, float w2,
                           float w3)
{
    int32_t i;

    m->State.ww[0] = w0;
    m->State.ww[1] = w1;
    m->State.ww[2] = w2;
    m->State.ww[3] = w3;
    for (i = 0; i < 4; i++) {
        m->BrakeLocked[i] = 0;
        m->SuspensionPosition[i] = 0.0f;
    }
}

void mellovator_set_state(Mellovator *m, const float *in)
{
    int32_t i;

    for (i = 0; i < 4; i++)
        m->State.ww[i] = in[i];
}

void mellovator_get_state(const Mellovator *m, float *out)
{
    int32_t i;

    for (i = 0; i < 4; i++)
        out[i] = m->State.ww[i];
}

float *mellovator_state(Mellovator *m)
{
    return m->State.ww;
}

int32_t mellovator_get_size(const Mellovator *m)
{
    (void)m;
    return 4;
}

float *mellovator_get_derivative(Mellovator *m, float *d)
{
    int32_t i;

    for (i = 0; i < 4; i++) {
        float acc = 0.0f;

        if (!m->BrakeLocked[i]) {
            int32_t front = (i < 2);
            float drive = 0.0f;
            float brake, k1, k2, g;

            if (!front) {
                const CarTypeInfo *cti;
                float rpm, t, eb, tq;

                rpm = m->RPM / m->CurrentBoost;
                t  = table_get_value(&m->TorqueCurve, rpm);
                eb = table_get_value(&m->EngineBraking, rpm);
                tq = m->Throttle * t - (1.0f - m->Throttle) * eb;

                // A closed throttle at exactly idle makes no torque at all:
                // neither the idle drive nor the engine braking.
                cti = m->CTI;
                if (m->Throttle < MV_IDLE_THROTTLE
                    && m->RPM == cti->Engine.IdleRPM)
                    tq = 0.0f;

                drive = (tq * cti->DriveTrain.FinalDrive[1])
                        * (cti->DriveTrain.GearRatios[m->CurrentGear] * 0.5f);
            }

            brake = m->Brake * (min_s(m->State.ww[i], 20.0f) * -0.5f);

            k1 = 1.0f;
            k2 = 1.25f;
            if (1.0f < m->CurrentBoost) {
                k2 = ((m->CurrentBoost - 1.0f) * 2.5f + 1.0f) * 1.25f;
                k1 = (m->CurrentBoost - 1.0f) * 3.0f + 1.0f;
            }

            g = graph_get_value(&MellowForceFeedbackGraph,
                                sqrtf(len2(&m->pBody->Velocity)));
            if (!front)
                g = g / (k1 * k2);

            acc = (drive * k1 + brake) - m->WheelForce[i].x * g;
        }
        d[i] = acc * MV_SPIN_SCALE;
    }
    return d;
}

void mellovator_compute_auxiliaries(Mellovator *m)
{
    const CarTypeInfo *cti;
    Gear gear, desired;
    float brake, w, rpm;
    int32_t i;

    mellovator_compute_suspension_forces(m);

    cti     = m->CTI;
    gear    = m->CurrentGear;
    desired = m->DesiredGear;
    brake   = m->Brake;
    for (i = 0; i < 4; i++) {
        if (MV_LOCK_BRAKE < brake && fabsf(m->State.ww[i]) < 30.0f) {
            m->State.ww[i] = 0.0f;
            m->BrakeLocked[i] = 1;
        }
        if (brake < MV_UNLOCK_BRAKE)
            m->BrakeLocked[i] = 0;
    }

    // The engine turns with the rear axle. The speed is taken in the gear
    // the box was in at entry, so a car that comes in below first is
    // shifted up to it without the RPM following until the loops below.
    w = (cti->DriveTrain.FinalDrive[1] * (m->State.ww[2] + m->State.ww[3]))
        * MV_RADS_TO_RPM_HALF;
    rpm = w * cti->DriveTrain.GearRatios[gear];

    if (desired == AUTOMATIC) {
        if (gear < FIRST_GEAR)
            m->CurrentGear = FIRST_GEAR;
        while (gear_number(m->CurrentGear) < cti->DriveTrain.NumGears
               && m->ShiftUpRPM[m->CurrentGear] < rpm) {
            m->CurrentGear = m->CurrentGear + 1;
            rpm = w * cti->DriveTrain.GearRatios[m->CurrentGear];
        }
        while (!(gear_number(m->CurrentGear) < 2)
               && rpm < m->ShiftDownRPM[m->CurrentGear]) {
            m->CurrentGear = m->CurrentGear - 1;
            rpm = w * cti->DriveTrain.GearRatios[m->CurrentGear];
        }
    } else if (desired == REVERSE) {
        rpm = w * cti->DriveTrain.GearRatios[0];
        m->CurrentGear = REVERSE;
    }

    if (rpm < cti->Engine.IdleRPM)
        rpm = cti->Engine.IdleRPM;
    else if (cti->Engine.MaxRPM < rpm)
        rpm = cti->Engine.MaxRPM;
    m->RPM = rpm;
}

void mellovator_get_ground_height_and_wheel_pos(Mellovator *m, bVector3 *pos,
                                                float *height)
{
    int32_t i;

    for (i = 0; i < 4; i++) {
        const RigidBody *rb = m->pBody;
        bVector3 r;

        hub(&r, m->CTI, i);
        eMulVector3(&pos[i], &rb->State.R, &r);
        pos[i].x   = pos[i].x + rb->State.X.x;
        pos[i].y   = pos[i].y + rb->State.X.y;
        pos[i].z   = pos[i].z + rb->State.X.z;
        pos[i].pad = pos[i].pad + rb->State.X.w;

        height[i] = ground(m->TC, &pos[i], &m->GroundNormal[i]);
    }
}

void mellovator_compute_suspension_forces(Mellovator *m)
{
    bVector3 pos[4];
    float height[4];
    const CarTypeInfo *cti;
    const RigidBody *rb;
    int32_t i;

    mellovator_get_ground_height_and_wheel_pos(m, pos, height);

    cti = m->CTI;
    rb  = m->pBody;
    for (i = 0; i < 4; i++) {
        const SuspensionInfo *si = &cti->Suspension[i / 2];
        float c, x, old, p, v, f;

        // The compression along the body's up axis: the ground's height
        // over the hub, over the cosine between that axis and the ground's
        // normal. Past 0.001 of a cosine the wheel is off the ground.
        c = dot3(&m->GroundNormal[i], &rb->State.R.v2);
        if (c < MV_MIN_COS)
            x = -100.0f;
        else
            x = (height[i] - pos[i].z) / c;
        x = x + cti->Wheels[i].Radius;

        old = m->SuspensionPosition[i];
        if (x < si->BumpStop[1]) {
            m->SuspensionPosition[i] = si->BumpStop[1];
            m->TouchingGround[i]     = 0;
            m->GroundPenetration[i]  = 0.0f;
        } else if (si->BumpStop[0] < x) {
            m->SuspensionPosition[i] = si->BumpStop[0];
            m->TouchingGround[i]     = 1;
            m->GroundPenetration[i]  = x - si->BumpStop[0];
        } else {
            m->SuspensionPosition[i] = x;
            m->TouchingGround[i]     = 1;
            m->GroundPenetration[i]  = 0.0f;
        }

        p = m->SuspensionPosition[i];
        v = (p - old) / max_s(gUglyTimestepHack, MV_MIN_DT);
        m->SuspensionVelocity[i] = v;

        // The sway bar reads its partner as it stands: wheels 1 and 3 see
        // 0 and 2 already updated, 0 and 2 see 1 and 3 from the last call.
        f = 0.0f;
        if (m->TouchingGround[i]) {
            f = m->RestLoad[i]
                + p * (si->Stiffness * (max_s(p, 0.0f) * si->Progression
                                        + 1.0f));
            f = f + v * si->Damping[(v <= 0.0f) ? 1 : 0];
            f = f + si->SwayBarStiffness
                    * (p - m->SuspensionPosition[SwayBarTable[i]]);
            if (f < 0.0f)
                f = 0.0f;
        }
        m->SuspensionForce[i] = f;
    }
}

void mellovator_resolve_forces(Mellovator *m)
{
    // The image's frame keeps all four body-frame forces in one array.
    // Their w lanes are never stored; bMulMatrixVec3 forces w to 1 before
    // it reads, so the zero here is never seen.
    bVector3 F[4];
    int32_t i;

    for (i = 0; i < 4; i++) {
        RigidBody *rb = m->pBody;
        const bMatrix4 *R = &rb->State.R;
        int32_t front = (i < 2);
        bVector3 tmp, r, W;

        hub(&tmp, m->CTI, i);
        bMulMatrixVec3(&r, R, &tmp);
        m->bSlipping[i] = 0;

        if (m->TouchingGround[i]) {
            float h, c, s, lng, lat, slip, mag, grip, sf, fl, flat, ang;

            // The contact patch's velocity over the ground, from the yaw
            // rate alone.
            W.x = rb->Velocity.x - rb->AngularVelocity.z * r.y;
            W.y = rb->Velocity.y + rb->AngularVelocity.z * r.x;

            // Into the wheel's heading: the body's, plus the steering for a
            // front wheel.
            h = (float)bATan(R->v0.x, R->v0.y) * MV_BAM_TO_RAD;
            if (front)
                h = h + (float)m->Steering * MV_BAM_TO_RAD;
            c = bSinF(h + MV_HALF_PI);
            s = bSinF(h);
            lng = W.x * c + W.y * s;
            lat = -W.x * s + W.y * c;

            slip = lng - m->State.ww[i] * m->CTI->Wheels[i].Radius;
            m->WheelSlip[i].x = slip;
            m->WheelSlip[i].y = lat;

            mag  = sqrtf(slip * slip + lat * lat);
            grip = 1.0f;
            if (m->CurrentFrictionBoost * MV_SLIP_KNEE < mag)
                grip = m->CurrentFrictionBoost * 0.25f;
            if (6.0f < mag)
                m->bSlipping[i] = 1;

            // Against the slip, in the wheel's frame, then turned back into
            // the body's by the steering alone.
            sf   = m->SuspensionForce[i] * 1.25f;
            fl   = (-slip * grip) * sf;
            flat = (-lat * grip) * sf;
            ang  = 0.0f;
            if (front)
                ang = (float)m->Steering * MV_BAM_TO_RAD;
            c = bSinF(ang + MV_HALF_PI);
            s = bSinF(ang);
            F[i].x = c * fl - s * flat;
            F[i].y = s * fl + c * flat;
        } else {
            F[i].y = 0.0f;
            F[i].x = 0.0f;
        }
        F[i].z   = m->SuspensionForce[i];
        F[i].pad = 0.0f;
        bMulMatrixVec3(&W, R, &F[i]);

        if (m->TouchingGround[i]) {
            float len, lim, q, kb, cb;

            // The friction circle, in the world's xy.
            len = sqrtf(W.x * W.x + W.y * W.y);
            lim = (m->SuspensionForce[i] * 1000.0f) * m->CurrentFrictionBoost;
            if (lim < len) {
                q = lim / len;
                W.y = W.y * q;
                W.x = W.x * q;
            }

            cb = m->CurrentBoost - 1.0f;
            kb = 1.0f;
            if (0.0f < cb)
                kb = cb * 2.5f + 1.0f;
            W.y = W.y * kb;
            W.x = W.x * kb;

            // The hold. Locked, or braked hard and all but stopped, the
            // wheel cancels the slope's pull along the ground outright;
            // inside the circle it cancels it in proportion to how far the
            // body is banked.
            if (m->BrakeLocked[i]
                || (MV_HOLD_BRAKE < m->Brake
                    && sqrtf(len2(&rb->Velocity)) < MV_HOLD_SPEED)) {
                q = m->SuspensionForce[i] / R->v2.z;
                W.x = W.x + -R->v2.x * q;
                W.y = W.y + -R->v2.y * q;
            } else if (len < lim) {
                q = m->SuspensionForce[i] / R->v2.z;
                W.x = W.x + (-R->v2.x * fabsf(R->v1.x)) * q;
                W.y = W.y + (-R->v2.y * fabsf(R->v1.y)) * q;
            }
        }

        rigidbody_apply_force(rb, (const bVector4 *)&W, (const bVector4 *)&r);
        m->WheelForce[i].x = F[i].x;
        m->WheelForce[i].y = F[i].y;
    }
}

float mellovator_bottom_out(Mellovator *m, CarState *cs)
{
    float total = 0.0f;
    int32_t i;

    for (i = 0; i < 4; i++) {
        RigidBody *rb;
        bVector3 tmp, p;
        bVector4 pv, j;
        const bVector3 *n;
        float k;

        if (!(0.0f < m->GroundPenetration[i]))
            continue;

        rb = m->pBody;
        hub(&tmp, m->CTI, i);
        tmp.z = tmp.z + m->SuspensionPosition[i];
        bMulMatrixVec3(&p, &rb->State.R, &tmp);
        suspension_get_point_velocity(&pv, &rb->Velocity, &rb->AngularVelocity,
                                      (const bVector4 *)&p);

        n = &m->GroundNormal[i];
        k = -dot3(&pv, n);
        if (!(0.0f < k))
            continue;

        k = k * gGroundPenaltyImpulse;
        k = k * rb->Mass;
        j.x = n->x * k;
        j.y = n->y * k;
        j.z = n->z * k;
        j.w = n->pad * k;
        total = total + k;
        rigidbody_apply_impulse(rb, &j, (const bVector4 *)&p);
        cs->WheelBottomOutMagnitude[i] = cs->WheelBottomOutMagnitude[i] + k;
    }
    return total;
}

void mellovator_set_throttle(Mellovator *m, float f)        { m->Throttle = f; }
void mellovator_set_brake(Mellovator *m, float f)           { m->Brake = f; }
void mellovator_set_steering(Mellovator *m, uint16_t bam)   { m->Steering = bam; }
void mellovator_set_desired_gear(Mellovator *m, Gear g)     { m->DesiredGear = g; }
void mellovator_set_current_boost(Mellovator *m, float f)   { m->CurrentBoost = f; }
void mellovator_set_current_friction_boost(Mellovator *m, float f)
{
    m->CurrentFrictionBoost = f;
}

float mellovator_get_rpm(const Mellovator *m)         { return m->RPM; }
Gear  mellovator_get_current_gear(const Mellovator *m) { return m->CurrentGear; }

int32_t mellovator_get_touching_ground(const Mellovator *m, int32_t i)
{
    return m->TouchingGround[i];
}

float mellovator_get_suspension_force(const Mellovator *m, int32_t i)
{
    return m->SuspensionForce[i];
}

float mellovator_get_suspension_position(const Mellovator *m, int32_t i)
{
    return m->SuspensionPosition[i];
}

float mellovator_get_wheel_angular_velocity(const Mellovator *m, int32_t i)
{
    return m->State.ww[i];
}

bVector2 *mellovator_get_wheel_slip(Mellovator *m, int32_t i)
{
    return &m->WheelSlip[i];
}

int32_t mellovator_get_wheel_slipping(const Mellovator *m, int32_t i)
{
    return m->bSlipping[i];
}

// ----------------------------------------------------------- MellowMover

MellowMover *mellowmover_new(void)
{
    return (MellowMover *)bSlotOMalloc(MellowMoverSlotPool);
}

void mellowmover_delete(void *p)
{
    bSlotFree(MellowMoverSlotPool, p);
}

MellowMover *mellowmover_init(MellowMover *mm, Car *car,
                              const CarTypeInfo *cti, CarDriver *driver,
                              CarState *cs)
{
    int32_t i;

    // CarMover's constructor inlined, then PhysicsVehicle's, as in
    // PhysicsCar's.
    mm->Mover._vtable = CARMOVER_VTABLE;
    physicssystem_init(&mm->Vehicle);
    mm->Vehicle._vtable = PHYSICSVEHICLE_VTABLE;

    mm->pCar            = car;
    mm->CTI             = cti;
    mm->Mover.Driver    = driver;
    mm->State           = cs;
    mm->Vehicle._vtable = MELLOWMOVER_VEHICLE_VTABLE;
    mm->Mover._vtable   = MELLOWMOVER_VTABLE;

    mm->pBody = rigidbody_init(rigidbody_new(), &mm->CTI->Body);
    physicssystem_add_component(&mm->Vehicle, (PhysicsComponent *)mm->pBody);

    mm->pMellovator = mellovator_init(mellovator_new(), mm->CTI, mm->pBody,
                                      cs->pTopologyCoordinate);
    physicssystem_add_component(&mm->Vehicle,
                                (PhysicsComponent *)mm->pMellovator);

    // Aerodynamics' constructor, inlined; not a component.
    mm->pAerodynamics = aerodynamics_new();
    aerodynamics_init(mm->pAerodynamics, mm->pBody, &mm->CTI->Aero);
    mm->pBody->SpeedLimiter = mm->CTI->Control.SpeedLimiter;

    // Before the wheels: Calibrate does not touch them.
    mellowmover_calibrate(mm);

    // The wheels are the Car's to draw and skid with, not components, and
    // they are placed from the Car's own CarState rather than `cs`.
    for (i = 0; i < 4; i++)
        mm->pWheels[i] = wheel_init(wheel_new(), &mm->CTI->Wheels[i],
                                    &mm->CTI->Tires[i / 2],
                                    &mm->CTI->Control, &mm->pCar->State);

    mellowmover_initialize_state_from_car(mm);
    mellowmover_compute_auxiliaries(mm);
    return mm;
}

void mellowmover_destroy(MellowMover *mm, int32_t flags)
{
    int32_t i;

    mm->Vehicle._vtable = MELLOWMOVER_VEHICLE_VTABLE;
    mm->Mover._vtable   = MELLOWMOVER_VTABLE;

    // `__dl__12AerodynamicsPv`, not null-checked.
    aerodynamics_delete(mm->pAerodynamics);

    // The wheels are not the system's, so they go by hand, each through
    // its own table. The pointers are left as they were.
    for (i = 0; i < 4; i++) {
        Wheel *w = mm->pWheels[i];
        if (w != NULL) {
            const VtEntry *e = vt_slot(w->_vtable, PHYSICSCOMPONENT_VT_DTOR);
            ((PhysicsDtorFn)e->fn)(vt_this(w, e), 3);
        }
    }

    // ~PhysicsVehicle, which is ~PhysicsSystem: the body and the
    // Mellovator go with it. Then ~CarMover with the delete bit clear,
    // and this class's own delete, which is its pool's.
    physicssystem_fini(&mm->Vehicle, 0);
    carmover_destroy(&mm->Mover, 0);
    if (flags & 1)
        mellowmover_delete(mm);
}

void mellowmover_calibrate(MellowMover *mm)
{
    rigidbody_calibrate(mm->pBody,
                        (const bVector4 *)&mm->CTI->CenterOfGravity);
    rigidbody_calculate_inertia_tensor(mm->pBody);
    mellovator_calibrate(mm->pMellovator,
                         aerodynamics_get_downforce_at_speed(
                             mm->pAerodynamics, mm->pCar->State.ForwardSpeed));
}

void mellowmover_initialize_state_from_car(MellowMover *mm)
{
    const CarDriver *d = mm->Mover.Driver;
    Mellovator *m = mm->pMellovator;
    CarState *cs = mm->State;
    const VtEntry *e;

    m->Throttle    = d->Throttle;
    m->Brake       = d->Brake;
    m->Steering    = d->Steering;
    m->DesiredGear = d->DesiredGear;
    rigidbody_set_state(mm->pBody, (const bVector4 *)&cs->Position,
                        &cs->BodyMatrix, (const bVector4 *)&cs->Velocity,
                        (const bVector4 *)&cs->AngularVelocity);

    cs = mm->State;
    mellovator_set_state4(mm->pMellovator,
                          cs->WheelAngularVelocity[0],
                          cs->WheelAngularVelocity[1],
                          cs->WheelAngularVelocity[2],
                          cs->WheelAngularVelocity[3]);

    e = vt_slot(mm->Vehicle._vtable, PHYSICSSYSTEM_VT_COMPUTE_AUXILIARIES);
    ((PhysicsVoidFn)e->fn)(vt_this(&mm->Vehicle, e));
}

void mellowmover_update_car(MellowMover *mm, float dt)
{
    CarState *cs = mm->State;
    const RigidBody *rb = mm->pBody;
    int32_t i;

    quad_to3(&cs->Position, &rb->State.X);
    cs->BodyMatrix = rb->State.R;
    carstate_calculate_geometry_position(cs);

    rb = mm->pBody;
    quad_to3(&cs->Velocity, &rb->Velocity);
    cs->VelocityMagnitude = sqrtf(len2(&rb->Velocity));
    cs->MatrixValid = 0;
    quad_to3(&cs->AngularVelocity, &rb->AngularVelocity);

    rb = mm->pBody;
    cs->Angle = (uint16_t)bATan(rb->State.R.v0.x, rb->State.R.v0.y);
    cs->ClutchEngaged = 1;
    cs->SkidLeft  = 0.0f;
    cs->SkidRight = 0.0f;
    cs->ForwardSpeed = dot3(&cs->Velocity, &mm->pBody->State.R.v0);

    for (i = 0; i < 4; i++) {
        Mellovator *m = mm->pMellovator;
        Wheel *w = mm->pWheels[i];
        float angle, steer;

        // Nothing integrates these wheels, so the angle is advanced here by
        // the Mellovator's speed over the whole frame. The steering goes
        // through a float and back: `cvt.s.w` of the halfword, then
        // `cvt.w.s`, which is the same number.
        angle = cs->WheelAngle[i] + dt * m->State.ww[i];
        steer = 0.0f;
        if (w->WI->WheelNumber < 2)
            steer = (float)mm->Mover.Driver->Steering;
        wheel_set_state_from_car_state(w, cs, (void *)mm->CTI, angle,
                                       m->State.ww[i],
                                       (uint16_t)ee_trunc_w(steer),
                                       m->SuspensionPosition[i]);
        carstate_set_wheel_touching_ground(cs, i,
                                           (int8_t)m->TouchingGround[i]);

        m = mm->pMellovator;
        w = mm->pWheels[i];
        cs->WheelSlip[i].y        = m->WheelSlip[i].y;
        cs->WheelSlip[i].x        = m->WheelSlip[i].x;
        cs->WheelTractionUsage[i] = 0.0f;
        cs->WheelZForce[i]        = m->SuspensionForce[i];
        w->TouchingGround         = (m->TouchingGround[i] != 0);

        m = mm->pMellovator;
        w = mm->pWheels[i];
        w->Slip[0]     = m->WheelSlip[i].x;
        w->Slip[1]     = m->WheelSlip[i].y;
        w->Slipping    = (uint8_t)m->bSlipping[i];
        w->CurrentSlip = m->WheelSlip[i].x;

        if (car_should_visual_effects_be_generated(mm->pCar))
            wheel_maybe_make_skids(mm->pWheels[i], dt);
    }

    cs->CurrentGear = mm->pMellovator->CurrentGear;
    cs->RPM         = mm->pMellovator->RPM;
}

void mellowmover_compute_auxiliaries(MellowMover *mm)
{
    const VtEntry *e;

    physicssystem_compute_auxiliaries(&mm->Vehicle);
    if (0.0f < mellovator_bottom_out(mm->pMellovator, mm->State))
        physicssystem_compute_auxiliaries(&mm->Vehicle);

    e = vt_slot(mm->Vehicle._vtable, PHYSICSSYSTEM_VT_RESOLVE_FORCES);
    ((PhysicsVoidFn)e->fn)(vt_this(&mm->Vehicle, e));
}

void mellowmover_resolve_forces(MellowMover *mm)
{
    Mellovator *m = mm->pMellovator;
    const VtEntry *e;

    e = vt_slot(m->_vtable, PHYSICSCOMPONENT_VT_RESOLVE_FORCES);
    ((PhysicsVoidFn)e->fn)(vt_this(m, e));
    aerodynamics_resolve_forces(mm->pAerodynamics, NULL);
    mellowmover_jump_stabilizer(mm);
}

void mellowmover_set_boost(MellowMover *mm, float f)
{
    Car *car = mm->pCar;
    float fb;

    mm->pAerodynamics->Boost = car->State.BoostFactor;
    mm->pAerodynamics->Draft = 1.0f - car->DraftFactor;
    mm->pBody->CatchUpMultiplier = f;

    fb = f;
    if (30.0f < car->State.ForwardSpeed * MV_MS_TO_MPH
        && car->State.DriverMode == 1)
        fb = f * MV_HIGH_SPEED_FRICTION;
    mellovator_set_current_friction_boost(mm->pMellovator, fb);
    mellovator_set_current_boost(mm->pMellovator, f);
}

void mellowmover_jump_stabilizer(MellowMover *mm)
{
    const Car *car = mm->pCar;
    int32_t n = car->State.nWheelsTouchingGround;

    if (n < 2) {
        const RigidBody *rb = mm->pBody;
        const bVector4 *w = &rb->AngularVelocity;
        bVector4 m;
        float k;

        k = rb->Mass * graph_get_value(&MellowJumpStabilization,
                                       sqrtf(len2(w)));
        k = -k;
        w = &mm->pBody->AngularVelocity;
        m.x = w->x * k;
        m.y = w->y * k;
        m.z = w->z * k;
        m.w = w->w * k;
        rigidbody_apply_moment(mm->pBody, &m);
    }

    if (n != 0)
        return;
    car = mm->pCar;
    if (!(MV_UPRIGHT < car->State.BodyMatrix.v2.z))
        return;

    {
        const bMatrix4 *bm = &car->State.BodyMatrix;
        bVector4 h, u, s, m;
        float k;

        // Yaw the nose into the direction of travel across the ground: the
        // axis is heading x forward, the size how far apart they are.
        h.x = car->State.Velocity.x;
        h.y = car->State.Velocity.y;
        h.z = 0.0f;
        h.w = car->State.Velocity.pad;
        normalize4(&h);
        cross3(&m, &h, &bm->v0);
        k = mm->pBody->Mass * ((dot3(&h, &bm->v0) - 1.0f) * 100.0f);
        bNormalize3To((bVector3 *)&m, (const bVector3 *)&m, k);
        rigidbody_apply_moment(mm->pBody, &m);

        // Level the side axis against the horizontal one under the nose.
        // The image stores three words of `u` and leaves the fourth to the
        // stack; the port zeroes it, and it reaches the moment's w lane.
        car = mm->pCar;
        bm = &car->State.BodyMatrix;
        u.x = 0.0f;
        u.y = 0.0f;
        u.z = 1.0f;
        u.w = 0.0f;
        cross3(&s, &u, &bm->v0);
        normalize4(&s);
        cross3(&m, &s, &bm->v1);
        k = mm->pBody->Mass * ((dot3(&s, &bm->v1) - 1.0f) * 100.0f);
        bNormalize3To((bVector3 *)&m, (const bVector3 *)&m, k);
        rigidbody_apply_moment(mm->pBody, &m);
    }
}

float mellowmover_move(MellowMover *mm, float dt)
{
    const CarDriver *d;
    Mellovator *m;
    CarState *cs;
    Aerodynamics *a;
    float step;
    int32_t n, i;

    (void)bGetTicker();
    mellowmover_calibrate(mm);

    d  = mm->Mover.Driver;
    m  = mm->pMellovator;
    cs = mm->State;
    a  = mm->pAerodynamics;
    m->Throttle     = d->Throttle;
    m->Brake        = d->Brake;
    a->GroundEffect = (float)cs->nWheelsTouchingGround * 0.25f;
    m->Steering     = d->Steering;
    m->DesiredGear  = d->DesiredGear;
    a->Throttle     = d->Throttle;
    for (i = 3; i >= 0; i--)
        cs->WheelBottomOutMagnitude[i] = 0.0f;

    mellowmover_set_boost(mm, mm->pCar->State.BoostFactor);

    // As many equal steps as keep each at or under MaxiMellowTimeStep --
    // one more than the quotient truncates to, so an exact multiple takes
    // an extra step.
    n = ee_trunc_w(dt / MaxiMellowTimeStep) + 1;
    step = dt / (float)n;
    for (i = 0; i < n; i++) {
        uint32_t t;

        gUglyTimestepHack = step;
        t = bGetTicker();
        physicssystem_integrate_euler(&mm->Vehicle, step);
        eOrthonormalizeMatrix(&mm->pBody->State.R, &mm->pBody->State.R);
        (void)bGetTickerDifference(t, bGetTicker());
        if (RigidBodyDebugInfo)
            rigidbody_print_current_state(mm->pBody);
    }

    mellowmover_update_car(mm, dt);
    return dt;
}

// ------------------------------------------------------------ the entries

static void vt_Mellovator_dtor(void *self, int32_t flags)
{
    mellovator_destroy((Mellovator *)self, flags);
}

static int32_t vt_Mellovator_GetSize(void *self)
{
    return mellovator_get_size((const Mellovator *)self);
}

static float *vt_Mellovator_GetState(void *self)
{
    return mellovator_state((Mellovator *)self);
}

static void vt_Mellovator_GetState_Pf(void *self, float *a)
{
    mellovator_get_state((const Mellovator *)self, a);
}

static void vt_Mellovator_SetState_Pf(void *self, float *a)
{
    mellovator_set_state((Mellovator *)self, a);
}

static void vt_Mellovator_ResolveForces(void *self)
{
    mellovator_resolve_forces((Mellovator *)self);
}

static float *vt_Mellovator_GetDerivative_Pf(void *self, float *out)
{
    return mellovator_get_derivative((Mellovator *)self, out);
}

static void vt_Mellovator_ComputeAuxiliaries(void *self)
{
    mellovator_compute_auxiliaries((Mellovator *)self);
}

static void vt_MellowMover_dtor(void *self, int32_t flags)
{
    mellowmover_destroy((MellowMover *)self, flags);
}

static float vt_MellowMover_Move(void *self, float dt)
{
    return mellowmover_move((MellowMover *)self, dt);
}

static void vt_MellowMover_ComputeAuxiliaries(void *self)
{
    mellowmover_compute_auxiliaries((MellowMover *)self);
}

static void vt_MellowMover_ResolveForces(void *self)
{
    mellowmover_resolve_forces((MellowMover *)self);
}

// ------------------------------------------------------------ the tables

static const VtEntry mellovator_vt[MELLOVATOR_VT_ENTRIES] = {
    { 0, 0, NULL },
    { 0, 0, (VtFn)vt_Mellovator_dtor },
    { 0, 0, (VtFn)vt_Mellovator_GetSize },
    { 0, 0, (VtFn)vt_Mellovator_GetState },
    { 0, 0, (VtFn)vt_Mellovator_GetState_Pf },
    { 0, 0, (VtFn)vt_Mellovator_SetState_Pf },
    { 0, 0, (VtFn)vt_Mellovator_ResolveForces },
    { 0, 0, (VtFn)vt_Mellovator_GetDerivative_Pf },
    { 0, 0, (VtFn)vt_Mellovator_ComputeAuxiliaries },
};

// DoSnapshot is not ported yet; see mellowmover.h.
static const VtEntry mellowmover_vt[MELLOWMOVER_VT_ENTRIES] = {
    { 0, 0, NULL },
    { 0, 0, (VtFn)vt_MellowMover_dtor },
    { 0, 0, (VtFn)vt_MellowMover_Move },
    { 0, 0, NULL },
};

#define VEHICLE_DELTA ((int16_t)-(int)offsetof(MellowMover, Vehicle))
static const VtEntry mellowmover_vehicle_vt[MELLOWMOVER_VT_ENTRIES] = {
    { VEHICLE_DELTA, 0, NULL },
    { VEHICLE_DELTA, 0, (VtFn)vt_MellowMover_dtor },
    { VEHICLE_DELTA, 0, (VtFn)vt_MellowMover_ComputeAuxiliaries },
    { VEHICLE_DELTA, 0, (VtFn)vt_MellowMover_ResolveForces },
};

void mellowmover_install_vtables(void)
{
    vt_install(MELLOVATOR_VTABLE, mellovator_vt, MELLOVATOR_VT_ENTRIES);
    vt_install(MELLOWMOVER_VTABLE, mellowmover_vt, MELLOWMOVER_VT_ENTRIES);
    vt_install(MELLOWMOVER_VEHICLE_VTABLE, mellowmover_vehicle_vt,
               MELLOWMOVER_VT_ENTRIES);
}
