// aerodynamics -- see aerodynamics.h.

#include "aerodynamics.h"

#include <math.h>

#include "replay.h"

float OffThrottleDragFactor       = 2.0f;
float OffThrottleDragCenterHeight = -0.100000001f;

bVector4 FrontDownforceLocation;
bVector4 RearDownforceLocation;

void aerodynamics_static_init(void)
{
    // 0x001a4de8. x of each first, then z, z, y, y -- the w lanes are
    // never written.
    FrontDownforceLocation.x = 1.0f;
    RearDownforceLocation.x  = -1.0f;
    RearDownforceLocation.z  = 0.0f;
    FrontDownforceLocation.z = 0.0f;
    FrontDownforceLocation.y = 0.0f;
    RearDownforceLocation.y  = 0.0f;
}

// -------------------------------------------------------------- VU idioms

// `vmul.xyz` then `vaddy.x` then `vaddz.x`, bracketed ((x + y) + z).
static float dot3(const bVector4 *a, const bVector4 *b)
{
    float xx = a->x * b->x;
    float yy = a->y * b->y;
    float zz = a->z * b->z;
    return (xx + yy) + zz;
}

// `vmulx.xyzw`: all four lanes.
static void scale4(bVector4 *o, const bVector4 *v, float s)
{
    o->x = v->x * s;
    o->y = v->y * s;
    o->z = v->z * s;
    o->w = v->w * s;
}

// ------------------------------------------------------------ the object

void aerodynamics_init(Aerodynamics *a, RigidBody *body, const AeroInfo *ai)
{
    a->AI           = ai;
    a->pBody        = body;
    a->Boost        = 1.0f;
    a->Draft        = 1.0f;
    a->Throttle     = 0.0f;
    a->GroundEffect = 0.0f;
}

void aerodynamics_set_boost(Aerodynamics *a, float f)    { a->Boost = f; }
void aerodynamics_set_draft(Aerodynamics *a, float f)    { a->Draft = f; }
void aerodynamics_set_throttle(Aerodynamics *a, float f) { a->Throttle = f; }
void aerodynamics_set_ground_effect(Aerodynamics *a, float f)
{
    a->GroundEffect = f;
}

void aerodynamics_resolve_forces(Aerodynamics *a, float *out)
{
    RigidBody *rb = a->pBody;
    const bVector4 *vel = &rb->Velocity;
    bVector4 force, at, dir, front, rear;
    float speed, s, drag, k, off, up, c, w, fd, rd;

    // ---- drag
    speed = sqrtf(dot3(vel, vel));
    s     = speed / a->Boost;
    drag  = (s * a->Draft) * a->AI->Drag;
    off   = 1.0f - a->Throttle;
    k     = drag + (drag * (OffThrottleDragFactor - 1.0f)) * off;
    scale4(&force, vel, -k);

    // The image writes x, y and z of the point and leaves w to whatever
    // the stack held, which ApplyForce then carries into
    // MomentAccumulator.w. The port zeroes it, as RigidBody's port does
    // the accumulators' own w lanes.
    at.x = 0.0f;
    at.y = 0.0f;
    at.z = 0.0f;
    at.w = 0.0f;
    if (AERODYNAMICS_GROUND_EFFECT <= a->GroundEffect)
        at.z = OffThrottleDragCenterHeight * off;
    rigidbody_apply_force(rb, &force, &at);

    // ---- downforce
    up = rb->State.R.v2.z;           // body+72
    if (up < 0.0f)
        up = 0.0f;
    if (AERODYNAMICS_GROUND_EFFECT <= a->GroundEffect)
        up = 1.0f;

    dir.x = 1.0f;
    dir.y = 0.0f;
    dir.z = 0.0f;
    dir.w = 0.0f;     // unwritten in the image; dot3 never reads it
    if (AERODYNAMICS_MIN_SPEED < s)
        scale4(&dir, vel, 1.0f / s);

    c = dot3(&dir, &rb->State.R.v0);  // body+32, the forward axis
    if (c < 0.0f)
        c = 0.0f;
    c = c * c;
    c = c * c;

    if (a->GroundEffect == 0.0f) {
        float fs  = s * AERODYNAMICS_FRONT_SHARE;
        float rs  = s * AERODYNAMICS_REAR_SHARE;
        float sum;

        w   = c * up;
        fs  = fs * w;
        rs  = rs * w;
        sum = a->AI->FrontDownforce + a->AI->RearDownforce;
        rd  = rs * sum;
        fd  = fs * sum;
    } else {
        w  = c * up;
        rd = (s * a->AI->RearDownforce) * w;
        fd = (s * a->AI->FrontDownforce) * w;
    }

    // x and y zeroed, z the push; the w lanes are unwritten in the image
    // and bMulMatrixVec3 replaces them before anything reads one.
    front.x = 0.0f;
    front.y = 0.0f;
    front.z = -fd;
    front.w = 0.0f;
    rear.x  = 0.0f;
    rear.y  = 0.0f;
    rear.z  = -rd;
    rear.w  = 0.0f;
    rigidbody_apply_force_in_frame(rb, &front, &FrontDownforceLocation);
    rigidbody_apply_force_in_frame(rb, &rear, &RearDownforceLocation);

    if (out)
        *out = fd + rd;
}

float aerodynamics_get_downforce_at_speed(const Aerodynamics *a, float speed)
{
    // `max.s f1, zero, f12`.
    float m = speed > 0.0f ? speed : 0.0f;

    return m * (a->AI->FrontDownforce + a->AI->RearDownforce);
}

void aerodynamics_do_snapshot(Aerodynamics *a, ReplaySnapshot *s)
{
    if (s->TakingSnapshotFlag || s->RestoringSnapshotFlag) {
        a->GroundEffect = 0.0f;
        a->Boost        = 0.0f;
        a->Throttle     = 0.0f;
    }
}
