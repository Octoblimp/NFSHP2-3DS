// rigidbody -- see rigidbody.h.

#include "rigidbody.h"

#include <math.h>

#include "physicssystem.h"
#include "replay.h"
#include "vtable.h"

// ------------------------------------------------------------- the tables

const float RigidBodyAngularMomentumDampingValues[6] = {
    0.0500000007f, 0.0500000007f, 0.25f, 0.699999988f, 2.0f, 5.0f
};

const float RigidBodyMotionDampingValues[8] = {
    1.5f, 1.0f, 0.600000024f, 0.219999999f,
    0.0599999987f, 0.0299999993f, 0.0149999997f, 0.0f
};

Table RigidBodyAngularMomentumDampingTable;
Table RigidBodyMotionDampingTable;

void rigidbody_static_init(void)
{
    // The static initialiser also zeroes two file-scope bVector3s at
    // 0x00308cd0 and 0x00308ce0 that nothing in the object ever reads --
    // default-constructed statics the compiler kept. Not ported.
    table_init(&RigidBodyAngularMomentumDampingTable,
               RigidBodyAngularMomentumDampingValues, 6, 0.0f, 10.0f);
    table_init(&RigidBodyMotionDampingTable,
               RigidBodyMotionDampingValues, 8, 0.0f, 1.0f);
}

// -------------------------------------------------------------- VU idioms

// `vmul.xyz` then `vaddy.x` then `vaddz.x`: the sum is bracketed
// ((x*x + y*y) + z*z), which is not the same float as x*x + (y*y + z*z).
static float len3(const bVector4 *v)
{
    float xx = v->x * v->x;
    float yy = v->y * v->y;
    float zz = v->z * v->z;
    return sqrtf((xx + yy) + zz);
}

static float dot3(const bVector4 *a, const bVector4 *b)
{
    float xx = a->x * b->x;
    float yy = a->y * b->y;
    float zz = a->z * b->z;
    return (xx + yy) + zz;
}

// `if (cap < |v|) v *= cap / |v|`, scaling all four lanes because the
// multiply is a vmulx.xyzw.
static void clamp3(bVector4 *v, float cap)
{
    float len = len3(v);
    if (cap < len) {
        float s = cap / len;
        v->x *= s;
        v->y *= s;
        v->z *= s;
        v->w *= s;
    }
}

// `vopmula.xyz` / `vopmsub.xyz`: the cross product writes xyz only, so
// the destination register's w lane survives. Every caller in this object
// has the *position* vector in that register, so the moment's w comes
// from the position rather than from the product.
static void cross3(bVector4 *o, const bVector4 *a, const bVector4 *b,
                   float keep_w)
{
    float x = a->y * b->z - a->z * b->y;
    float y = a->z * b->x - a->x * b->z;
    float z = a->x * b->y - a->y * b->x;
    o->x = x;
    o->y = y;
    o->z = z;
    o->w = keep_w;
}

static void scale4(bVector4 *o, const bVector4 *v, float s)
{
    o->x = v->x * s;
    o->y = v->y * s;
    o->z = v->z * s;
    o->w = v->w * s;
}

static void add4(bVector4 *o, const bVector4 *a, const bVector4 *b)
{
    o->x = a->x + b->x;
    o->y = a->y + b->y;
    o->z = a->z + b->z;
    o->w = a->w + b->w;
}

// ------------------------------------------------------- PhysicsComponent

void physicscomponent_init(void *pc)
{
    ((RigidBody *)pc)->_vtable = PHYSICSCOMPONENT_VTABLE;
}

void physicscomponent_fini(void *pc)
{
    // 0x00192438 writes the same word and then tail-calls ~bNode, which
    // is `jr ra` with the list pointers left alone.
    ((RigidBody *)pc)->_vtable = PHYSICSCOMPONENT_VTABLE;
}

// -------------------------------------------------------------- the object

void rigidbody_calculate_inertia_tensor(RigidBody *rb)
{
    const RigidBodyInfo *rbi = rb->RBI;

    // `lwc1 $f1,0(a1)` before `addiu a1,a1,16` -- the mass is read first
    // and there is no guard against it being zero.
    rb->Mass = rbi->Mass;
    rb->Mass_inv = 1.0f / rbi->Mass;
    bInvertMatrix(&rb->I_body_inv, &rbi->InertiaTensor);
}

RigidBody *rigidbody_init(RigidBody *rb, const RigidBodyInfo *rbi)
{
    rb->_vtable = RIGIDBODY_VTABLE;

    // Three `sw zero` per vector: the w lanes are left as they were
    // found, here and everywhere else in this constructor.
    rb->State.X.x = 0.0f;
    rb->State.X.y = 0.0f;
    rb->State.X.z = 0.0f;

    rb->RBI = rbi;              // in the delay slot of the bIdentity call
    bIdentity(&rb->State.R);

    rb->State.P.x = 0.0f;
    rb->State.P.y = 0.0f;
    rb->State.P.z = 0.0f;
    rb->State.L.x = 0.0f;
    rb->State.L.y = 0.0f;
    rb->State.L.z = 0.0f;
    rb->State.MotionDampingFactor = 0.0f;

    rb->Velocity.x = 0.0f;
    rb->Velocity.y = 0.0f;
    rb->Velocity.z = 0.0f;
    rb->AngularVelocity.x = 0.0f;
    rb->AngularVelocity.y = 0.0f;
    rb->AngularVelocity.z = 0.0f;

    rb->ForceAccumulator.x = 0.0f;
    rb->ForceAccumulator.y = 0.0f;
    rb->ForceAccumulator.z = 0.0f;
    rb->MomentAccumulator.x = 0.0f;
    rb->MomentAccumulator.y = 0.0f;
    rb->MomentAccumulator.z = 0.0f;

    rb->MaxMomentZ = 0.0f;
    rb->SpeedLimiter = 0.0f;
    rb->IsHP = 0;
    rb->CatchUpMultiplier = 1.0f;
    rb->MotionDamping = 1;      // in the delay slot of the call below

    rigidbody_calculate_inertia_tensor(rb);
    return rb;
}

void rigidbody_fini(RigidBody *rb)
{
    // No store of RigidBody's own vtable first -- the base destructor's
    // write is the only one, so a destroyed body carries
    // PhysicsComponent's.
    physicscomponent_fini(rb);
}

void rigidbody_calibrate(RigidBody *rb, const bVector4 *cog)
{
    if (cog == NULL)
        return;
    rb->CenterOfGravity = *cog;
}

void rigidbody_set_state(RigidBody *rb, const bVector4 *x, const bMatrix4 *r,
                         const bVector4 *p, const bVector4 *omega)
{
    bMatrix4 ibody, rt, t1, t2;

    rb->State.X = *x;
    rb->State.R = *r;
    scale4(&rb->State.P, p, rb->Mass);

    // The body tensor is rebuilt by reciprocating the *diagonal* of the
    // inverse tensor -- three divides, not a matrix inversion -- so a
    // tensor with off-diagonal terms does not survive the round trip.
    bIdentity(&ibody);
    ibody.v0.x = 1.0f / rb->I_body_inv.v0.x;
    ibody.v1.y = 1.0f / rb->I_body_inv.v1.y;
    ibody.v2.z = 1.0f / rb->I_body_inv.v2.z;

    bTransposeMatrix(&rt, &rb->State.R);
    bMulMatrix(&t1, &rb->State.R, &ibody);
    bMulMatrix(&t2, &t1, &rt);
    bMulMatrixVec3((bVector3 *)&rb->State.L, &t2, (const bVector3 *)omega);
}

void rigidbody_apply_force(RigidBody *rb, const bVector4 *f,
                           const bVector4 *at)
{
    bVector4 v = *f;
    bVector4 m;

    clamp3(&v, RIGIDBODY_MAX_FORCE);
    add4(&rb->ForceAccumulator, &rb->ForceAccumulator, &v);

    // **The moment uses the unclamped force.** `lqc2 vf1,0(a1)` reloads
    // it from the caller's memory after the accumulator has already had
    // the clamped copy added. ApplyImpulse does the opposite.
    cross3(&m, at, f, at->w);
    clamp3(&m, RIGIDBODY_MAX_MOMENT);
    add4(&rb->MomentAccumulator, &rb->MomentAccumulator, &m);
}

void rigidbody_apply_force_in_frame(RigidBody *rb, const bVector4 *f,
                                    const bVector4 *at)
{
    bVector4 wf, wat;

    bMulMatrixVec3((bVector3 *)&wf, &rb->State.R, (const bVector3 *)f);
    bMulMatrixVec3((bVector3 *)&wat, &rb->State.R, (const bVector3 *)at);
    rigidbody_apply_force(rb, &wf, &wat);
}

void rigidbody_apply_moment(RigidBody *rb, const bVector4 *m)
{
    add4(&rb->MomentAccumulator, &rb->MomentAccumulator, m);
}

void rigidbody_apply_impulse(RigidBody *rb, const bVector4 *j,
                             const bVector4 *at)
{
    bVector4 v = *j;
    bVector4 m;

    clamp3(&v, RIGIDBODY_MAX_IMPULSE);
    add4(&rb->State.P, &rb->State.P, &v);

    // Here the cross *does* use the clamped copy -- it is reloaded from
    // the stack slot, not from the argument.
    cross3(&m, at, &v, at->w);
    clamp3(&m, RIGIDBODY_MAX_ANG_IMPULSE);
    add4(&rb->State.L, &rb->State.L, &m);
}

void rigidbody_apply_impulse_scaled(RigidBody *rb, const bVector4 *j,
                                    const bVector4 *at, float scale)
{
    bVector4 v = *j;
    bVector4 m;

    clamp3(&v, RIGIDBODY_MAX_IMPULSE);
    add4(&rb->State.P, &rb->State.P, &v);

    cross3(&m, at, &v, at->w);
    clamp3(&m, RIGIDBODY_MAX_ANG_IMPULSE);
    scale4(&m, &m, scale);       // scaled after the clamp, not before
    add4(&rb->State.L, &rb->State.L, &m);
}

void rigidbody_test_impulse(RigidBody *rb, bVector4 *outV, bVector4 *outOmega,
                            const bVector4 *j, const bVector4 *at)
{
    bVector4 p, l, m;
    bMatrix4 rt, t1, t2;

    // No clamps anywhere in this one.
    cross3(&m, at, j, at->w);
    add4(&p, &rb->State.P, j);
    add4(&l, &rb->State.L, &m);

    // Three scalar stores, not a quadword: outV->w is not written.
    outV->x = p.x * rb->Mass_inv;
    outV->y = p.y * rb->Mass_inv;
    outV->z = p.z * rb->Mass_inv;

    bTransposeMatrix(&rt, &rb->State.R);
    bMulMatrix(&t1, &rb->State.R, &rb->I_body_inv);
    bMulMatrix(&t2, &t1, &rt);
    bMulMatrixVec3((bVector3 *)outOmega, &t2, (const bVector3 *)&l);
}

float rigidbody_get_energy(const RigidBody *rb)
{
    float lin = dot3(&rb->State.P, &rb->Velocity);
    float ang = dot3(&rb->State.L, &rb->AngularVelocity);

    // Each half is scaled before the add: 0.5*a + 0.5*b, not 0.5*(a+b).
    return lin * 0.5f + ang * 0.5f;
}

float rigidbody_get_test_impulse_energy(RigidBody *rb, const bVector4 *j,
                                        const bVector4 *at)
{
    bVector4 p, l, m, v, omega;
    bMatrix4 rt, t1, t2;

    add4(&p, &rb->State.P, j);
    cross3(&m, at, j, at->w);
    add4(&l, &rb->State.L, &m);
    scale4(&v, &p, rb->Mass_inv);

    bTransposeMatrix(&rt, &rb->State.R);
    bMulMatrix(&t1, &rb->State.R, &rb->I_body_inv);
    bMulMatrix(&t2, &t1, &rt);
    bMulMatrixVec3((bVector3 *)&omega, &t2, (const bVector3 *)&l);

    return dot3(&p, &v) * 0.5f + dot3(&l, &omega) * 0.5f;
}

void VectorStarMatrix(bMatrix4 *out, const bVector4 *w, const bMatrix4 *m)
{
    const bVector4 *rows[3];
    bVector4 *orows[3];
    int i;

    rows[0] = &m->v0; rows[1] = &m->v1; rows[2] = &m->v2;
    orows[0] = &out->v0; orows[1] = &out->v1; orows[2] = &out->v2;

    for (i = 0; i < 3; i++) {
        const bVector4 *u = rows[i];
        bVector4 *o = orows[i];
        o->x = -w->z * u->y + w->y * u->z;
        o->y =  w->z * u->x - w->x * u->z;
        o->z = -w->y * u->x + w->x * u->y;
        o->w = 0.0f;
    }

    out->v3.x = 0.0f;
    out->v3.y = 0.0f;
    out->v3.z = 0.0f;
    out->v3.w = 1.0f;
}

void rigidbody_compute_auxiliaries(RigidBody *rb)
{
    bMatrix4 rt, t1, iw;
    bVector4 grav, at;

    scale4(&rb->Velocity, &rb->State.P, rb->Mass_inv);

    bTransposeMatrix(&rt, &rb->State.R);
    bMulMatrix(&t1, &rb->State.R, &rb->I_body_inv);
    bMulMatrix(&iw, &t1, &rt);
    bMulMatrixVec3((bVector3 *)&rb->AngularVelocity, &iw,
                   (const bVector3 *)&rb->State.L);

    if (rb->State.MotionDampingFactor < 0.0f)
        rb->State.MotionDampingFactor = 0.0f;

    // Matrix is R with the position in the fourth row and a hard 1 in
    // its w -- the object's world transform, rebuilt every step.
    rb->Matrix.v0 = rb->State.R.v0;
    rb->Matrix.v1 = rb->State.R.v1;
    rb->Matrix.v2 = rb->State.R.v2;
    rb->Matrix.v3 = rb->State.X;
    rb->Matrix.v3.w = 1.0f;

    // The image zeroes both accumulators from a stack quadword whose w
    // word it never wrote, so on hardware their w lanes take whatever
    // was on the stack. The port zeroes them; nothing reads that lane.
    rb->ForceAccumulator.x = 0.0f;
    rb->ForceAccumulator.y = 0.0f;
    rb->ForceAccumulator.z = 0.0f;
    rb->ForceAccumulator.w = 0.0f;
    rb->MomentAccumulator = rb->ForceAccumulator;

    grav.x = 0.0f;
    grav.y = 0.0f;
    grav.z = -RIGIDBODY_GRAVITY * rb->Mass;
    grav.w = 0.0f;
    at.x = 0.0f;
    at.y = 0.0f;
    at.z = 0.0f;
    at.w = 0.0f;
    rigidbody_apply_force(rb, &grav, &at);
}

void rigidbody_resolve_forces(RigidBody *rb)
{
    (void)rb;   // jr ra ; nop
}

void rigidbody_print_current_state(RigidBody *rb)
{
    // 0x00193c70 is not empty, but every result it computes lands in a
    // stack temporary or in $f0, and the signature is void. The printf
    // it was written around is gone. See docs/formats/rigid-body.md for
    // what it worked out.
    (void)rb;
}

float *rigidbody_get_derivative(RigidBody *rb, float *out)
{
    bVector4 *xdot = (bVector4 *)(out + 0);
    bMatrix4 *rdot = (bMatrix4 *)(out + 4);
    bVector4 *pdot = (bVector4 *)(out + 20);
    bVector4 *ldot = (bVector4 *)(out + 24);
    float slope = 0.0f;
    float damp, spin, speed;

    if (rb->SpeedLimiter != 0.0f) {
        float limit = rb->SpeedLimiter * rb->CatchUpMultiplier
                      + RIGIDBODY_LIMIT_BASE;
        float planar;

        if (rb->IsHP != 0)
            limit *= RIGIDBODY_HP_BONUS;

        // R.v0 is the body's forward axis in world space, so its z is
        // how steeply the car is pointed up or down the hill.
        slope = rb->State.R.v0.z;
        if (0.0f < slope) {
            if (RIGIDBODY_UPHILL_CLAMP < slope)
                slope = RIGIDBODY_UPHILL_CLAMP;
            limit *= 1.0f - ((1.0f - RIGIDBODY_UPHILL_FLOOR) * slope)
                            / RIGIDBODY_UPHILL_CLAMP;
        } else {
            slope = -slope;
            if (RIGIDBODY_DOWNHILL_CLAMP < slope)
                slope = RIGIDBODY_DOWNHILL_CLAMP;
            limit *= ((RIGIDBODY_DOWNHILL_CEIL - 1.0f) * slope)
                     / RIGIDBODY_DOWNHILL_CLAMP + 1.0f;
        }

        // Ground speed only: z is left out of the magnitude.
        planar = sqrtf(rb->Velocity.x * rb->Velocity.x
                       + rb->Velocity.y * rb->Velocity.y)
                 * RIGIDBODY_SPEED_SCALE;

        if (limit < planar
            && 0.0f < dot3(&rb->State.R.v0, &rb->ForceAccumulator)) {
            bMatrix4 rt;
            bVector4 local, world;
            float brake;

            bTransposeMatrix(&rt, &rb->State.R);
            bMulMatrixVec3((bVector3 *)&local, &rt,
                           (const bVector3 *)&rb->ForceAccumulator);

            brake = -slope * RIGIDBODY_BRAKE_GAIN;
            if (RIGIDBODY_BRAKE_FLOOR < brake)
                brake = RIGIDBODY_BRAKE_FLOOR;
            local.x = brake;

            bMulMatrixVec3((bVector3 *)&world, &rb->State.R,
                           (const bVector3 *)&local);
            rb->ForceAccumulator = world;
        }
    }

    *xdot = rb->Velocity;
    VectorStarMatrix(rdot, &rb->AngularVelocity, &rb->State.R);
    *pdot = rb->ForceAccumulator;
    *ldot = rb->MomentAccumulator;

    // Angular momentum damping, off the six-entry table.
    spin = len3(&rb->AngularVelocity);
    {
        float d = -table_get_value(&RigidBodyAngularMomentumDampingTable,
                                   spin);
        bVector4 t;
        scale4(&t, &rb->State.L, d);
        add4(ldot, ldot, &t);
    }

    // The damping factor's own derivative: a slow rise to the table's
    // value and a fast fall away from it.
    speed = len3(&rb->Velocity);
    damp = speed / RIGIDBODY_DAMP_SPEED_DIV;
    spin = spin / RIGIDBODY_DAMP_SPIN_DIV;
    if (damp < spin)
        damp = spin;
    damp = table_get_value(&RigidBodyMotionDampingTable, damp);
    out[28] = (rb->State.MotionDampingFactor < damp)
              ? RIGIDBODY_DAMP_RISE : -RIGIDBODY_DAMP_FALL;

    if (rb->MotionDamping != 0) {
        bVector4 t;
        scale4(&t, &rb->State.L,
               -RIGIDBODY_DAMP_L_GAIN * rb->State.MotionDampingFactor);
        add4(ldot, ldot, &t);
        scale4(&t, &rb->State.P,
               -RIGIDBODY_DAMP_P_GAIN * rb->State.MotionDampingFactor);
        add4(pdot, pdot, &t);
    }

    // Ldot.z clamped to +/- MaxMomentZ, and the clamp is skipped
    // entirely when MaxMomentZ is zero rather than pinning Ldot.z to it.
    // Note it reads MomentAccumulator.z, not the Ldot.z it writes, so
    // the damping terms above are not seen by the comparison.
    if (rb->MaxMomentZ != 0.0f) {
        float mz = rb->MomentAccumulator.z;
        if (rb->MaxMomentZ < mz) {
            out[26] = rb->MaxMomentZ;
        } else {
            float lo = -rb->MaxMomentZ;
            if (mz < lo)
                out[26] = lo;
        }
    }

    return out;
}

void rigidbody_get_state_array(const RigidBody *rb, float *out)
{
    *(bVector4 *)(out + 0) = rb->State.X;
    *(bMatrix4 *)(out + 4) = rb->State.R;
    *(bVector4 *)(out + 20) = rb->State.P;
    *(bVector4 *)(out + 24) = rb->State.L;
    out[28] = rb->State.MotionDampingFactor;
}

void rigidbody_set_state_array(RigidBody *rb, const float *in)
{
    rb->State.X = *(const bVector4 *)(in + 0);
    rb->State.R = *(const bMatrix4 *)(in + 4);
    rb->State.P = *(const bVector4 *)(in + 20);
    rb->State.L = *(const bVector4 *)(in + 24);
    rb->State.MotionDampingFactor = in[28];
}

RigidBodyState *rigidbody_get_state(RigidBody *rb) { return &rb->State; }

int32_t rigidbody_get_size(const RigidBody *rb)
{
    (void)rb;
    return RIGIDBODY_STATE_FLOATS;
}

// ----------------------------------------------------------- the accessors

void rigidbody_set_l(RigidBody *rb, const bVector4 *l) { rb->State.L = *l; }
void rigidbody_set_r(RigidBody *rb, const bMatrix4 *r) { rb->State.R = *r; }
void rigidbody_set_p(RigidBody *rb, const bVector4 *p) { rb->State.P = *p; }
void rigidbody_set_x(RigidBody *rb, const bVector4 *x) { rb->State.X = *x; }

void rigidbody_set_motion_damping(RigidBody *rb, int32_t on)
{ rb->MotionDamping = on; }
void rigidbody_set_catch_up_multiplier(RigidBody *rb, float f)
{ rb->CatchUpMultiplier = f; }
void rigidbody_set_is_hp(RigidBody *rb, int32_t b) { rb->IsHP = b; }
void rigidbody_set_speed_limiter(RigidBody *rb, float f)
{ rb->SpeedLimiter = f; }
void rigidbody_set_max_moment_z(RigidBody *rb, float f) { rb->MaxMomentZ = f; }

bMatrix4 *rigidbody_get_inverse_inertia_tensor(RigidBody *rb)
{ return &rb->I_body_inv; }
float rigidbody_get_inverse_mass(const RigidBody *rb) { return rb->Mass_inv; }
bVector4 *rigidbody_get_accumulated_forces(RigidBody *rb)
{ return &rb->ForceAccumulator; }
bVector4 *rigidbody_get_center_of_gravity(RigidBody *rb)
{ return &rb->CenterOfGravity; }
float rigidbody_get_mass(const RigidBody *rb) { return rb->Mass; }
bMatrix4 *rigidbody_get_matrix(RigidBody *rb) { return &rb->Matrix; }
bVector4 *rigidbody_get_angular_momentum(RigidBody *rb)
{ return &rb->State.L; }
bVector4 *rigidbody_get_angular_velocity(RigidBody *rb)
{ return &rb->AngularVelocity; }
bMatrix4 *rigidbody_get_rotation(RigidBody *rb) { return &rb->State.R; }
bVector4 *rigidbody_get_momentum(RigidBody *rb) { return &rb->State.P; }
bVector4 *rigidbody_get_velocity(RigidBody *rb) { return &rb->Velocity; }
bVector4 *rigidbody_get_position(RigidBody *rb) { return &rb->State.X; }

float rigidbody_get_moment_of_inertia_about_z(const RigidBody *rb)
{
    return 1.0f / rb->I_body_inv.v2.z;
}

// ---------------------------------------------------------------- the replay

// 0x0019ca70. The tests are c.eq.s, so -0 counts as zero.
void rigidbody_do_snapshot(RigidBody *rb, ReplaySnapshot *s)
{
    RigidBodyState *st = &rb->State;
    int32_t still = 0;

    ReplaySnapshot_BeginNamedSection(s, "RigidBody");
    ReplaySnapshot_MoveVector3(s, (bVector3 *)&st->X);
    ReplaySnapshot_MoveVector3(s, (bVector3 *)&st->R.v0);
    ReplaySnapshot_MoveVector3(s, (bVector3 *)&st->R.v1);
    ReplaySnapshot_MoveVector3(s, (bVector3 *)&st->R.v2);
    if (s->TakingSnapshotFlag || s->RestoringSnapshotFlag) {
        rb->MotionDamping = 1;
        st->R.v3.w = 1.0f;
        st->R.v0.w = 0.0f;
        st->R.v1.w = 0.0f;
        st->R.v2.w = 0.0f;
        st->R.v3.x = 0.0f;
        st->R.v3.y = 0.0f;
        st->R.v3.z = 0.0f;
    }
    ReplaySnapshot_MoveFloat(s, &st->MotionDampingFactor);
    if (st->P.x == 0.0f && st->P.y == 0.0f && st->P.z == 0.0f
        && st->L.x == 0.0f && st->L.y == 0.0f && st->L.z == 0.0f)
        still = 1;
    ReplaySnapshot_MoveBool(s, &still, 1);
    if (!still) {
        ReplaySnapshot_MoveVector3(s, (bVector3 *)&st->P);
        ReplaySnapshot_MoveVector3(s, (bVector3 *)&st->L);
    } else if (s->TakingSnapshotFlag || s->RestoringSnapshotFlag) {
        st->P.x = 0.0f;
        st->P.z = 0.0f;
        st->P.y = 0.0f;
        st->L.x = 0.0f;
        st->L.z = 0.0f;
        st->L.y = 0.0f;
    }
    if (s->TakingSnapshotFlag || s->RestoringSnapshotFlag) {
        const VtEntry *e = vt_slot(rb->_vtable,
                                   PHYSICSCOMPONENT_VT_COMPUTE_AUXILIARIES);

        ((PhysicsVoidFn)e->fn)(vt_this(rb, e));
    }
    ReplaySnapshot_EndNamedSection(s);
}
