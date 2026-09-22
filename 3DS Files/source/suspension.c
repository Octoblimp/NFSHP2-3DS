// suspension -- see suspension.h.

#include "suspension.h"

#include "bmath.h"

// The shipped values, read out of .sdata in the ELF.
float   gLoadFactor               = 0.8f;
int32_t gWheelForceFrame          = 1;
float   gTireForceEllipseRatio    = 1.5f;
float   gNoSlipCorrectionFactor   = 0.1f;
float   gUglyTimestepHack         = 1.0f;
float   gGroundPenaltyImpulse     = 0.2f;
float   gGroundPenaltyForce       = 0.0f;
float   gMaxGroundPenetration     = 0.15f;
float   gProgressiveDampingFactor = 0.1f;
int32_t gNoWheels                 = 0;

// gWheelFindDrivingSurfaceFn and gWheelExchangeZForcesFn were defined here
// while Wheel was only a layout. They are Wheel's methods and wheel.c
// defines them now, along with wheel_install_seams to point them at the
// real ones; this file is just a caller. Anything that links suspension.c
// therefore links wheel.c too.

// `max.s $f1,$f4,$f22` against a register the function zeroed. Written as
// the comparison it is rather than as fmaxf, which would drag in a NaN
// rule the R5900 instruction does not have.
static float max_s(float a, float b)
{
    return a > b ? a : b;
}

// --------------------------------------------------------------- lifetime

Suspension *suspension_init(Suspension *s, int32_t wheelPosition,
                            RigidBody *body, Wheel *wheel,
                            Steering *steering, const SuspensionInfo *si)
{
    s->WheelPosition = wheelPosition;
    s->pBody = body;
    s->_vtable = SUSPENSION_VTABLE;
    s->pWheel = wheel;
    s->pSteering = steering;
    s->SI = si;
    s->pSwayBar = NULL;
    return s;
}

void suspension_fini(Suspension *s)
{
    s->_vtable = PHYSICSCOMPONENT_VTABLE;
}

void suspension_calibrate(Suspension *s, float load)
{
    const WheelInfo *wi = s->pWheel->WI;
    const bVector4 *cog = &s->pBody->CenterOfGravity;

    s->RestLoad = load;

    // A quadword subtract off the front of WheelInfo. The fourth lane is
    // Radius, which is the field behind Position, not a w of its own --
    // see the note in suspension.h.
    s->RestPosition.x = wi->PositionX - cog->x;
    s->RestPosition.y = wi->PositionY - cog->y;
    s->RestPosition.z = wi->PositionZ - cog->z;
    s->RestPosition.w = wi->Radius - cog->w;
}

// ------------------------------------------------------------- the state

void suspension_set_state(Suspension *s)
{
    s->State.v = 0.0f;
    s->State.z = 0.0f;
}

void suspension_get_state_array(const Suspension *s, float *out)
{
    out[0] = s->State.z;
    out[1] = s->State.v;
}

void suspension_set_state_array(Suspension *s, const float *in)
{
    s->State.z = in[0];
    s->State.v = in[1];
}

SuspensionState *suspension_get_state(Suspension *s)
{
    return &s->State;
}

int32_t suspension_get_size(const Suspension *s)
{
    (void)s;
    return SUSPENSION_STATE_FLOATS;
}

float *suspension_get_derivative(Suspension *s, float *out)
{
    (void)s;
    out[0] = 0.0f;
    out[1] = 0.0f;
    return out;
}

// --------------------------------------------------------- the main pass

void suspension_get_point_velocity(bVector4 *out, const bVector4 *v,
                                   const bVector4 *w, const bVector4 *r)
{
    // vopmula.xyz / vopmsub.xyz: the cross product writes xyz and leaves
    // the w lane of `w` where it was, and the add that follows is xyzw.
    bVector4 c;
    c.x = w->y * r->z - w->z * r->y;
    c.y = w->z * r->x - w->x * r->z;
    c.z = w->x * r->y - w->y * r->x;
    c.w = w->w;

    out->x = v->x + c.x;
    out->y = v->y + c.y;
    out->z = v->z + c.z;
    out->w = v->w + c.w;
}

void suspension_compute_auxiliaries(Suspension *s)
{
    RigidBody *body = s->pBody;
    Wheel *wheel = s->pWheel;
    const SuspensionInfo *si = s->SI;
    bVector4 world;
    bVector4 r;
    bMatrix4 m;
    bMatrix4 spin;
    float penetration = 0.0f;
    float oldZ;
    float surface;

    // The rest position, rotated into the world and offset by the body,
    // is where the wheel would sit with no travel. bMulMatrixVec3 forces
    // w to 1, which is the affine point transform the image calls.
    bMulMatrixVec3((bVector3 *)&world, &body->State.R,
                   (const bVector3 *)&s->RestPosition);
    world.x += body->State.X.x;
    world.y += body->State.X.y;
    world.z += body->State.X.z;
    world.w += body->State.X.w;

    surface = gWheelFindDrivingSurfaceFn
                  ? gWheelFindDrivingSurfaceFn(wheel, &world, &body->State.R)
                  : 0.0f;

    oldZ = s->State.z;
    surface += wheel->WI->Radius;

    if (si->BumpStop[0] < surface) {
        // Past the bump stop: the height clamps and the excess becomes a
        // penetration. An excess bigger than gMaxGroundPenetration is
        // treated as nonsense and thrown away rather than clamped.
        penetration = surface - si->BumpStop[0];
        s->State.z = si->BumpStop[0];
        s->TouchingGround = 1;
        if (gMaxGroundPenetration < penetration)
            penetration = 0.0f;
    } else if (surface < si->BumpStop[1]) {
        // Fully extended: the wheel has left the ground.
        s->State.z = si->BumpStop[1];
        s->TouchingGround = 0;
    } else {
        s->State.z = surface;
        s->TouchingGround = 1;
    }

    if (SUSPENSION_TIMESTEP_EPSILON < gUglyTimestepHack)
        s->State.v = (s->State.z - oldZ) / gUglyTimestepHack;

    // The wheel centre is the rest position lifted by the travel, and the
    // matrix is that as a pure translation.
    s->Position = s->RestPosition;
    s->Position.z += s->State.z;

    bIdentity(&s->Matrix);
    s->Matrix.v3 = s->Position;
    s->Matrix.v3.w = 1.0f;

    if (s->pSteering) {
        // `o = m2 * m1`: steer first, then the translation.
        bMulMatrix(&m, &s->Matrix,
                   &s->pSteering->SteeringMatrix[s->WheelPosition]);
    } else {
        m = s->Matrix;
    }

    // A damaged wheel wobbles about z, with the damage as the amplitude
    // and the wheel's own rotation as the phase.
    if (wheel->Damage != 0.0f) {
        float angle = wheel->Damage * bSinF(wheel->State.a);
        float c = bSinF(angle + SUSPENSION_IMAGE_HALF_PI);
        float sn = bSinF(angle);

        bIdentity(&spin);
        spin.v0.x = c;
        spin.v0.y = sn;
        spin.v1.x = -sn;
        spin.v1.y = c;
        bMulMatrix(&m, &m, &spin);
    }

    wheel->CarMatrix = m;

    // The contact point's velocity: v + w x r, with r the wheel centre
    // rotated into the world.
    bMulMatrixVec3((bVector3 *)&r, &body->State.R,
                   (const bVector3 *)&s->Position);
    suspension_get_point_velocity(&wheel->Velocity, &body->Velocity,
                                  &body->AngularVelocity, &r);

    bMulMatrix(&m, &body->Matrix, &m);
    wheel->WorldMatrix = m;

    if (!s->TouchingGround) {
        s->Force = 0.0f;
        return;
    }

    {
        float z = s->State.z;
        float v = s->State.v;
        float spring;
        float damping;
        float f;

        // z * (max(z, 0) * Progression * Stiffness + Stiffness) -- the
        // progression term only stiffens the spring in compression, but
        // the whole product is scaled by a z that can be either sign.
        spring = max_s(z, 0.0f) * si->Progression * si->Stiffness;
        spring += si->Stiffness;
        spring *= z;

        damping = v * (v <= 0.0f ? si->Damping[1] : si->Damping[0]);

        f = s->RestLoad + spring + damping;
        f += si->SwayBarStiffness * (z - s->pSwayBar->State.z);
        f += penetration * gGroundPenaltyForce;

        s->Force = f < 0.0f ? 0.0f : f;
    }
}

void suspension_resolve_forces(Suspension *s, float extra)
{
    float z = s->Force;

    if (s->TouchingGround)
        z += extra;

    s->GroundForce = gWheelExchangeZForcesFn
                         ? gWheelExchangeZForcesFn(s->pWheel,
                                                   s->TouchingGround, z)
                         : 0.0f;
}

void suspension_resolve_more_forces(Suspension *s)
{
    bVector4 at;

    if (!s->TouchingGround)
        return;

    // Computed before the flag is tested, so gNoWheels skips the force
    // and not the arithmetic.
    at.x = s->pWheel->ContactPoint.x - s->pBody->State.X.x;
    at.y = s->pWheel->ContactPoint.y - s->pBody->State.X.y;
    at.z = s->pWheel->ContactPoint.z - s->pBody->State.X.z;
    at.w = s->pWheel->ContactPoint.w - s->pBody->State.X.w;

    if (gNoWheels)
        return;

    rigidbody_apply_force(s->pBody, &s->pWheel->WorldGroundForce, &at);
}

float suspension_apply_ground_penalty_impulse(Suspension *s)
{
    bVector4 at;
    bVector4 pv;
    bVector4 n;
    bVector4 impulse;
    float approach;
    float j;

    bMulMatrixVec3((bVector3 *)&at, &s->pBody->State.R,
                   (const bVector3 *)&s->Position);
    suspension_get_point_velocity(&pv, &s->pBody->Velocity,
                                  &s->pBody->AngularVelocity, &at);

    n = s->pWheel->ContactNormal;

    // vmul.xyz then two vadd lanes into x: a three-lane dot product, so
    // the w lanes the cross product left behind do not reach it.
    approach = -(pv.x * n.x + pv.y * n.y + pv.z * n.z);
    if (approach < 0.0f)
        return 0.0f;

    j = approach * gGroundPenaltyImpulse * s->pBody->Mass;

    // vmulx.xyzw: the scale broadcasts across all four lanes.
    impulse.x = n.x * j;
    impulse.y = n.y * j;
    impulse.z = n.z * j;
    impulse.w = n.w * j;

    if (gNoWheels)
        return j;

    rigidbody_apply_impulse(s->pBody, &impulse, &at);
    return j;
}

// ------------------------------------------------------------- accessors

float suspension_get_sway_bar_stiffness(const Suspension *s)
{
    return s->SI->SwayBarStiffness;
}

float suspension_get_stiffness(const Suspension *s)
{
    return s->SI->Stiffness;
}

float suspension_get_progression(const Suspension *s)
{
    return s->SI->Progression;
}

float suspension_get_damping(const Suspension *s)
{
    return s->State.v <= 0.0f ? s->SI->Damping[1] : s->SI->Damping[0];
}

float suspension_get_compression_hack_offset(const Suspension *s)
{
    float max = s->SI->MaxRenderingCompression;

    if (s->State.z < max)
        return 0.0f;
    return max - s->State.z;
}

int32_t suspension_is_bottomed_out(const Suspension *s)
{
    return s->State.z == s->SI->BumpStop[0] ? 1 : 0;
}

float suspension_get_height(const Suspension *s)
{
    return s->State.z;
}

float suspension_get_velocity(const Suspension *s)
{
    return s->State.v;
}

int32_t suspension_get_wheel_position(const Suspension *s)
{
    return s->WheelPosition;
}

bVector4 *suspension_get_rest_position(Suspension *s)
{
    return &s->RestPosition;
}

bMatrix4 *suspension_get_matrix(Suspension *s)
{
    return &s->Matrix;
}

void suspension_set_sway_bar(Suspension *s, Suspension *other)
{
    s->pSwayBar = other;
}

void suspension_set_magic_force(Suspension *s, float f)
{
    s->MagicForce = f;
}
