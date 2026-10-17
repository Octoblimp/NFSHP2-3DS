// Transcript harness for RigidBody and the two PhysicsComponent stubs.
// Cross-checked by tools/rigidbody_check.py, which models the same
// behaviour from the disassembly without reading this file.

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "rigidbody.h"

// realtime.c's clock, which ReplaySnapshot_Init stamps; not linked here.
int32_t WorldTimer;
int32_t WorldLoopCounter;

// ------------------------------------------------------------- printing

static void pv(const char *tag, const bVector4 *v)
{
    printf("%s %.9g %.9g %.9g %.9g\n", tag, v->x, v->y, v->z, v->w);
}

static void pm(const char *tag, const bMatrix4 *m)
{
    const float *p = (const float *)m;
    int i;
    for (i = 0; i < 4; i++)
        printf("%s[%d] %.9g %.9g %.9g %.9g\n", tag, i,
               p[i * 4 + 0], p[i * 4 + 1], p[i * 4 + 2], p[i * 4 + 3]);
}

static void pf(const char *tag, float f) { printf("%s %.9g\n", tag, f); }

static unsigned fbits(float f)
{
    unsigned u;
    memcpy(&u, &f, 4);
    return u;
}

// ---------------------------------------------------------------- filling

static void fill_vec(bVector4 *v, float b)
{
    v->x = b; v->y = b + 1.0f; v->z = b + 2.0f; v->w = b + 3.0f;
}

static void fill_mat(bMatrix4 *m, float b)
{
    float *p = (float *)m;
    int i;
    for (i = 0; i < 16; i++)
        p[i] = b + (float)i;
}

// Every field given a distinct value, so anything the constructor leaves
// alone is visible as its old value rather than as a plausible zero.
static void dirty(RigidBody *rb, float b)
{
    rb->pNext = 0xaaaa1111u;
    rb->pPrev = 0xbbbb2222u;
    rb->_vtable = 0xcccc3333u;
    rb->RBI = NULL;
    fill_vec(&rb->State.X, b + 10.0f);
    fill_mat(&rb->State.R, b + 100.0f);
    fill_vec(&rb->State.P, b + 20.0f);
    fill_vec(&rb->State.L, b + 30.0f);
    rb->State.MotionDampingFactor = b + 40.0f;
    fill_vec(&rb->Velocity, b + 50.0f);
    fill_vec(&rb->AngularVelocity, b + 60.0f);
    fill_mat(&rb->Matrix, b + 200.0f);
    fill_vec(&rb->ForceAccumulator, b + 70.0f);
    fill_vec(&rb->MomentAccumulator, b + 80.0f);
    rb->MotionDamping = 7;
    rb->IsHP = 9;
    rb->Mass = b + 90.0f;
    rb->Mass_inv = b + 91.0f;
    fill_mat(&rb->I_body_inv, b + 300.0f);
    fill_vec(&rb->CenterOfGravity, b + 400.0f);
    rb->MaxMomentZ = b + 500.0f;
    rb->SpeedLimiter = b + 501.0f;
    rb->CatchUpMultiplier = b + 502.0f;
}

static void dump(const char *p, const RigidBody *rb)
{
    char t[64];
#define T(s) (sprintf(t, "%s." s, p), t)
    printf("%s.links %08x %08x\n", p, rb->pNext, rb->pPrev);
    printf("%s.vtable %08x\n", p, rb->_vtable);
    printf("%s.rbi_null %d\n", p, rb->RBI == NULL);
    pv(T("X"), &rb->State.X);
    pm(T("R"), &rb->State.R);
    pv(T("P"), &rb->State.P);
    pv(T("L"), &rb->State.L);
    pf(T("mdf"), rb->State.MotionDampingFactor);
    pv(T("V"), &rb->Velocity);
    pv(T("W"), &rb->AngularVelocity);
    pm(T("M"), &rb->Matrix);
    pv(T("FA"), &rb->ForceAccumulator);
    pv(T("MA"), &rb->MomentAccumulator);
    printf("%s.md %d\n", p, rb->MotionDamping);
    printf("%s.ishp %d\n", p, rb->IsHP);
    pf(T("mass"), rb->Mass);
    pf(T("massinv"), rb->Mass_inv);
    pm(T("Ibi"), &rb->I_body_inv);
    pv(T("cog"), &rb->CenterOfGravity);
    pf(T("maxmz"), rb->MaxMomentZ);
    pf(T("speedlim"), rb->SpeedLimiter);
    pf(T("catchup"), rb->CatchUpMultiplier);
#undef T
}

// The inertia tensors the scenarios build bodies from. Diagonal ones
// round-trip through SetState's three reciprocals; the last one does
// not, on purpose.
static RigidBodyInfo *make_info(float mass, float ix, float iy, float iz,
                                float offdiag)
{
    RigidBodyInfo *ri = calloc(1, sizeof(RigidBodyInfo));
    ri->Mass = mass;
    ri->Xdim = 1.75f;
    ri->Ydim = 4.25f;
    ri->Zdim = 1.25f;
    bIdentity(&ri->InertiaTensor);
    ri->InertiaTensor.v0.x = ix;
    ri->InertiaTensor.v1.y = iy;
    ri->InertiaTensor.v2.z = iz;
    ri->InertiaTensor.v0.y = offdiag;
    ri->InertiaTensor.v1.z = offdiag * 0.5f;
    return ri;
}

// ------------------------------------------------------------- the layout

static void scenario_layout(void)
{
    printf("[layout]\n");
    printf("sizeof_host RigidBody %zu\n", sizeof(RigidBody));
    printf("sizeof RigidBodyState %zu\n", sizeof(RigidBodyState));
    printf("sizeof RigidBodyInfo %zu\n", sizeof(RigidBodyInfo));
    printf("slack %zu\n", RIGIDBODY_SLACK);

#define OFF(t, f) printf("off %-24s %zu\n", #f, offsetof(t, f))
    OFF(RigidBody, pNext); OFF(RigidBody, pPrev); OFF(RigidBody, _vtable);
    OFF(RigidBody, RBI); OFF(RigidBody, State); OFF(RigidBody, Velocity);
    OFF(RigidBody, AngularVelocity); OFF(RigidBody, Matrix);
    OFF(RigidBody, ForceAccumulator); OFF(RigidBody, MomentAccumulator);
    OFF(RigidBody, MotionDamping); OFF(RigidBody, IsHP);
    OFF(RigidBody, Mass); OFF(RigidBody, Mass_inv);
    OFF(RigidBody, I_body_inv); OFF(RigidBody, CenterOfGravity);
    OFF(RigidBody, MaxMomentZ); OFF(RigidBody, SpeedLimiter);
    OFF(RigidBody, CatchUpMultiplier);
    OFF(RigidBodyState, X); OFF(RigidBodyState, R); OFF(RigidBodyState, P);
    OFF(RigidBodyState, L); OFF(RigidBodyState, MotionDampingFactor);
    OFF(RigidBodyInfo, Mass); OFF(RigidBodyInfo, Xdim);
    OFF(RigidBodyInfo, Ydim); OFF(RigidBodyInfo, Zdim);
    OFF(RigidBodyInfo, InertiaTensor);
#undef OFF

    // Widths and signedness. The two flags are words even though one is
    // a bool and the other reads as a flag, and the two list links are
    // 32-bit slots rather than host pointers.
    {
        RigidBody *w = calloc(1, sizeof(RigidBody));
        printf("width links %zu %zu\n", sizeof(w->pNext), sizeof(w->pPrev));
        printf("width MotionDamping %zu\n", sizeof(w->MotionDamping));
        printf("width IsHP %zu\n", sizeof(w->IsHP));
        w->MotionDamping = -1;
        w->IsHP = -1;
        printf("signed MotionDamping %lld\n", (long long)w->MotionDamping);
        printf("signed IsHP %lld\n", (long long)w->IsHP);
        free(w);
    }

    printf("const gravity   %08x\n", fbits(RIGIDBODY_GRAVITY));
    printf("const limitbase %08x\n", fbits(RIGIDBODY_LIMIT_BASE));
    printf("const spdscale  %08x\n", fbits(RIGIDBODY_SPEED_SCALE));
    printf("const hpbonus   %08x\n", fbits(RIGIDBODY_HP_BONUS));
    printf("const upclamp   %08x\n", fbits(RIGIDBODY_UPHILL_CLAMP));
    printf("const upfloor   %08x\n", fbits(RIGIDBODY_UPHILL_FLOOR));
    printf("const dnclamp   %08x\n", fbits(RIGIDBODY_DOWNHILL_CLAMP));
    printf("const dnceil    %08x\n", fbits(RIGIDBODY_DOWNHILL_CEIL));
    printf("const brakegain %08x\n", fbits(RIGIDBODY_BRAKE_GAIN));
    printf("const brakefloor %08x\n", fbits(RIGIDBODY_BRAKE_FLOOR));
    printf("const maxforce  %08x\n", fbits(RIGIDBODY_MAX_FORCE));
    printf("const maxmoment %08x\n", fbits(RIGIDBODY_MAX_MOMENT));
    printf("const maximpulse %08x\n", fbits(RIGIDBODY_MAX_IMPULSE));
    printf("const maxangimp %08x\n", fbits(RIGIDBODY_MAX_ANG_IMPULSE));
    printf("vtable RigidBody %08x\n", (unsigned)RIGIDBODY_VTABLE);
    printf("vtable PhysicsComponent %08x\n",
           (unsigned)PHYSICSCOMPONENT_VTABLE);

    // The two static tables, after the initialiser the image runs before
    // main. Printed as fields, so a wrong span or count shows up here
    // rather than only in a derivative twenty scenarios later.
    rigidbody_static_init();
    {
        int i;
        const Table *t[2];
        const char *n[2] = { "angdamp", "motion" };
        t[0] = &RigidBodyAngularMomentumDampingTable;
        t[1] = &RigidBodyMotionDampingTable;
        for (i = 0; i < 2; i++) {
            int j;
            printf("table %s n=%d lo=%.9g hi=%.9g mult=%.9g\n", n[i],
                   t[i]->NumEntries, t[i]->MinArg, t[i]->MaxArg,
                   t[i]->IndexMultiplier);
            for (j = 0; j < t[i]->NumEntries; j++)
                printf("table %s [%d] %.9g\n", n[i], j, t[i]->pTable[j]);
        }
    }
}

// ------------------------------------------------------------- the object

static void scenario_ctor(void)
{
    RigidBodyInfo *ri = make_info(1450.0f, 900.0f, 3200.0f, 3600.0f, 0.0f);
    RigidBody *rb = calloc(1, sizeof(RigidBody));
    int k;

    printf("[ctor]\n");
    for (k = 0; k < 2; k++) {
        RigidBody *r;
        dirty(rb, k ? 1000.0f : 0.0f);
        r = rigidbody_init(rb, ri);
        printf("run %d returns this %d\n", k, r == rb);
        printf("run %d rbi %d\n", k, rb->RBI == ri);
        dump(k ? "b" : "a", rb);
    }

    // The base class on its own.
    dirty(rb, 0.0f);
    physicscomponent_init(rb);
    printf("pc init vtable %08x\n", rb->_vtable);
    physicscomponent_fini(rb);
    printf("pc fini vtable %08x\n", rb->_vtable);

    rigidbody_init(rb, ri);
    rigidbody_fini(rb);
    printf("rb fini vtable %08x\n", rb->_vtable);
    printf("rb fini rbi %d\n", rb->RBI == ri);

    free(rb);
    free(ri);
}

static void scenario_inertia(void)
{
    static const float M[3] = { 1450.0f, 1.0f, 2.5f };
    static const float OD[3] = { 0.0f, 0.0f, 120.0f };
    int k;

    printf("[inertia]\n");
    for (k = 0; k < 3; k++) {
        RigidBodyInfo *ri = make_info(M[k], 900.0f + 10.0f * (float)k,
                                      3200.0f, 3600.0f, OD[k]);
        RigidBody *rb = calloc(1, sizeof(RigidBody));
        dirty(rb, 0.0f);
        rb->RBI = ri;
        rigidbody_calculate_inertia_tensor(rb);
        printf("case %d\n", k);
        pf("mass", rb->Mass);
        pf("massinv", rb->Mass_inv);
        pm("Ibi", &rb->I_body_inv);
        pf("moiz", rigidbody_get_moment_of_inertia_about_z(rb));

        // Calibrate is the only null-checked pointer in the object, and
        // it copies the w lane too.
        {
            bVector4 c;
            fill_vec(&c, 3.5f + (float)k);
            rigidbody_calibrate(rb, NULL);
            pv("cog-after-null", &rb->CenterOfGravity);
            rigidbody_calibrate(rb, &c);
            pv("cog-after-set", &rb->CenterOfGravity);
        }
        free(rb);
        free(ri);
    }
}

static RigidBody *fresh(float mass, float ix, float iy, float iz,
                        RigidBodyInfo **out)
{
    RigidBodyInfo *ri = make_info(mass, ix, iy, iz, 0.0f);
    RigidBody *rb = calloc(1, sizeof(RigidBody));
    rigidbody_init(rb, ri);
    *out = ri;
    return rb;
}

static void scenario_setstate(void)
{
    static const float ANG[3][4] = {
        { 0.0f, 0.0f, 0.0f, 0.0f },
        { 0.25f, -0.5f, 1.5f, 99.0f },
        { -3.0f, 2.0f, -1.0f, -99.0f },
    };
    int k;

    printf("[setstate]\n");
    for (k = 0; k < 3; k++) {
        RigidBodyInfo *ri;
        RigidBody *rb = fresh(1450.0f, 900.0f, 3200.0f, 3600.0f, &ri);
        bVector4 x, p, w;
        bMatrix4 r;

        fill_vec(&x, 5.0f + (float)k);
        fill_vec(&p, -2.0f + (float)k);
        w.x = ANG[k][0]; w.y = ANG[k][1]; w.z = ANG[k][2]; w.w = ANG[k][3];

        bIdentity(&r);
        r.v0.x = 0.8f; r.v0.y = 0.6f + 0.1f * (float)k;
        r.v1.x = -0.6f; r.v1.y = 0.8f;
        r.v2.z = 1.0f + 0.25f * (float)k;
        r.v3.x = 7.0f; r.v3.y = -3.0f; r.v3.z = 2.0f;

        rigidbody_set_state(rb, &x, &r, &p, &w);
        printf("case %d\n", k);
        pv("X", &rb->State.X);
        pm("R", &rb->State.R);
        pv("P", &rb->State.P);
        pv("L", &rb->State.L);
        free(rb);
        free(ri);
    }
}

// ------------------------------------------------------------ the forces

struct fcase { float f[4]; float at[4]; };

// The last one is a magnitude, not a force: 4096 squared is 2^24, so the
// two remaining squares land either side of the last representable unit
// and ((xx + yy) + zz) and (xx + (yy + zz)) come out two ulps apart. It is
// here so that len3's association is observable and not merely asserted.
static const struct fcase FC[6] = {
    { {  10.0f,  -20.0f,  30.0f,  0.5f }, { 1.0f, 2.0f, -0.5f, 0.25f } },
    { { 900.0f,  800.0f, 700.0f, -1.5f }, { 0.1f, 0.2f,  0.3f, -2.0f } },
    { {   0.0f,    0.0f,   0.0f,  3.0f }, { 4.0f, 5.0f,  6.0f,  7.0f } },
    { {  -5.0f,    0.5f,   0.0f,  0.0f }, { 0.0f, 0.0f,  0.0f,  0.0f } },
    { {2000.0f,-3000.0f, 500.0f,  9.0f }, {-3.0f, 8.0f, -2.5f,  1.0f } },
    { {4096.0f,    1.0f,   1.5f,  0.5f }, { 2.0f,-1.0f,  0.5f,  1.0f } },
};

static void vload(bVector4 *v, const float *s)
{ v->x = s[0]; v->y = s[1]; v->z = s[2]; v->w = s[3]; }

static void scenario_apply(void)
{
    int k;

    printf("[apply]\n");
    for (k = 0; k < 6; k++) {
        RigidBodyInfo *ri;
        RigidBody *rb = fresh(1450.0f, 900.0f, 3200.0f, 3600.0f, &ri);
        bVector4 f, at;

        vload(&f, FC[k].f);
        vload(&at, FC[k].at);
        printf("case %d\n", k);

        // Both accumulators start non-zero, so an Apply that assigns
        // instead of accumulating is visible.
        fill_vec(&rb->ForceAccumulator, 1.0f);
        fill_vec(&rb->MomentAccumulator, -1.0f);
        rigidbody_apply_force(rb, &f, &at);
        pv("force.FA", &rb->ForceAccumulator);
        pv("force.MA", &rb->MomentAccumulator);

        fill_vec(&rb->ForceAccumulator, 1.0f);
        fill_vec(&rb->MomentAccumulator, -1.0f);
        rb->State.R.v0.x = 0.6f; rb->State.R.v0.y = 0.8f;
        rb->State.R.v1.x = -0.8f; rb->State.R.v1.y = 0.6f;
        rb->State.R.v3.x = 11.0f; rb->State.R.v3.y = -4.0f;
        rigidbody_apply_force_in_frame(rb, &f, &at);
        pv("frame.FA", &rb->ForceAccumulator);
        pv("frame.MA", &rb->MomentAccumulator);

        fill_vec(&rb->MomentAccumulator, 2.0f);
        rigidbody_apply_moment(rb, &f);
        pv("moment.MA", &rb->MomentAccumulator);

        fill_vec(&rb->State.P, 3.0f);
        fill_vec(&rb->State.L, -3.0f);
        rigidbody_apply_impulse(rb, &f, &at);
        pv("imp.P", &rb->State.P);
        pv("imp.L", &rb->State.L);

        fill_vec(&rb->State.P, 3.0f);
        fill_vec(&rb->State.L, -3.0f);
        rigidbody_apply_impulse_scaled(rb, &f, &at, 0.375f);
        pv("scaled.P", &rb->State.P);
        pv("scaled.L", &rb->State.L);

        free(rb);
        free(ri);
    }
}

static void scenario_test_impulse(void)
{
    int k;

    printf("[test-impulse]\n");
    for (k = 0; k < 6; k++) {
        RigidBodyInfo *ri;
        RigidBody *rb = fresh(1450.0f + 100.0f * (float)k,
                              900.0f, 3200.0f, 3600.0f, &ri);
        bVector4 j, at, ov, ow;

        vload(&j, FC[k].f);
        vload(&at, FC[k].at);
        fill_vec(&rb->State.P, 12.0f);
        fill_vec(&rb->State.L, -7.0f);
        fill_vec(&rb->Velocity, 0.5f);
        fill_vec(&rb->AngularVelocity, -0.25f);
        rb->State.R.v0.x = 0.6f; rb->State.R.v0.y = 0.8f;
        rb->State.R.v1.x = -0.8f; rb->State.R.v1.y = 0.6f;

        fill_vec(&ov, 77.0f);
        fill_vec(&ow, 88.0f);
        rigidbody_test_impulse(rb, &ov, &ow, &j, &at);
        printf("case %d\n", k);
        pv("outV", &ov);
        pv("outW", &ow);
        pf("energy", rigidbody_get_energy(rb));
        pf("testenergy", rigidbody_get_test_impulse_energy(rb, &j, &at));
        pv("P-unchanged", &rb->State.P);
        pv("L-unchanged", &rb->State.L);

        free(rb);
        free(ri);
    }
}

static void scenario_star(void)
{
    static const float W[4][4] = {
        { 0.0f, 0.0f, 0.0f, 0.0f },
        { 1.0f, 0.0f, 0.0f, 5.0f },
        { 0.25f, -1.5f, 3.0f, -5.0f },
        { -2.0f, 0.5f, -0.125f, 0.0f },
    };
    int k;

    printf("[star]\n");
    for (k = 0; k < 4; k++) {
        bMatrix4 m, o;
        bVector4 w;
        fill_mat(&m, 1.0f + (float)k * 0.5f);
        w.x = W[k][0]; w.y = W[k][1]; w.z = W[k][2]; w.w = W[k][3];
        fill_mat(&o, 900.0f);        // so untouched lanes are visible
        VectorStarMatrix(&o, &w, &m);
        printf("case %d\n", k);
        pm("star", &o);
    }
}

static void scenario_aux(void)
{
    static const float MDF[3] = { 0.25f, -0.5f, 0.0f };
    int k;

    printf("[aux]\n");
    for (k = 0; k < 3; k++) {
        RigidBodyInfo *ri;
        RigidBody *rb = fresh(1450.0f, 900.0f, 3200.0f, 3600.0f, &ri);

        fill_vec(&rb->State.X, 3.0f);
        fill_vec(&rb->State.P, 100.0f * (float)(k + 1));
        fill_vec(&rb->State.L, -50.0f * (float)(k + 1));
        rb->State.MotionDampingFactor = MDF[k];
        rb->State.R.v0.x = 0.6f; rb->State.R.v0.y = 0.8f;
        rb->State.R.v1.x = -0.8f; rb->State.R.v1.y = 0.6f;
        rb->State.R.v3.x = 2.0f; rb->State.R.v3.y = 3.0f;
        fill_vec(&rb->ForceAccumulator, 40.0f);
        fill_vec(&rb->MomentAccumulator, 60.0f);
        fill_mat(&rb->Matrix, 700.0f);

        rigidbody_compute_auxiliaries(rb);
        printf("case %d\n", k);
        pv("V", &rb->Velocity);
        pv("W", &rb->AngularVelocity);
        pm("M", &rb->Matrix);
        pf("mdf", rb->State.MotionDampingFactor);
        pv("FA", &rb->ForceAccumulator);
        pv("MA", &rb->MomentAccumulator);

        rigidbody_resolve_forces(rb);
        rigidbody_print_current_state(rb);
        pv("FA-after-stubs", &rb->ForceAccumulator);

        free(rb);
        free(ri);
    }
}

// --------------------------------------------------------- the derivative

struct dcase {
    float speedlim, catchup, maxmz, mdf, rzz;
    int   ishp, motiondamp;
    float vx, vy, vz;
    float fax, fay, faz;
    float wx, wy, wz;
};

// The last two sit on the speed limiter's own threshold: 14.445 m/s of
// ground speed scales to 32.30, which is above the flat-ground limit of
// 31.90 and below the 32.86 an HP car gets. They are the only cases where
// the HP bonus decides whether the brake fires at all -- everywhere else
// the limit is so far under the speed that the bonus cannot reach it.
// The one after them climbs at 5 m/s: 14 m/s along the ground is 31.30,
// under the limit, and the full 3D speed is 33.24, over it. It is the
// only case where leaving z out of the magnitude changes the answer.
static const struct dcase DC[15] = {
    /* speedlim catchup maxmz  mdf   R.v0.z hp md   V            FA             W        */
    {  0.0f,   1.0f,  0.0f,  0.0f,  0.20f, 0, 0,  1,2,3,   10,20,30,    0.1f,0.2f,0.3f },
    {  0.0f,   1.0f, 50.0f,  0.5f,  0.20f, 0, 1,  1,2,3,   10,20,30,    0.1f,0.2f,0.3f },
    { 30.0f,   1.0f,  0.0f,  0.0f,  0.20f, 0, 0, 40,10,0,  90,10,-5,    1.0f,0.0f,0.0f },
    { 30.0f,   1.0f,  0.0f,  0.0f,  0.20f, 1, 0, 40,10,0,  90,10,-5,    1.0f,0.0f,0.0f },
    { 30.0f,   2.5f,  0.0f,  0.0f, -0.40f, 0, 0, 40,10,0,  90,10,-5,    2.0f,3.0f,1.0f },
    { 30.0f,   1.0f,  0.0f,  0.0f,  0.60f, 0, 0, 40,10,0,  90,10,-5,    0.0f,0.0f,0.0f },
    { 30.0f,   1.0f,  0.0f,  0.0f,  0.00f, 0, 0, 40,10,0,  90,10,-5,    5.0f,5.0f,5.0f },
    { 30.0f,   1.0f,  0.0f,  0.0f,  0.20f, 0, 0, 40,10,0, -90,10,-5,    1.0f,0.0f,0.0f },
    {200.0f,   1.0f,  0.0f,  0.0f,  0.20f, 0, 0,  1, 1,0,  90,10,-5,    0.5f,0.5f,0.5f },
    { 30.0f,   1.0f, 12.0f,  0.9f,  0.20f, 0, 1, 40,10,0,  90,10,-5,    3.0f,1.0f,2.0f },
    {  0.0f,   1.0f,  4.0f,  0.1f,  0.20f, 0, 1,  1, 1,1,  10,20,-99,   0.0f,0.0f,0.0f },
    {  0.0f,   1.0f,  4.0f, -0.2f,  0.20f, 0, 0,  1, 1,1,  10,20, 99,  20.0f,0.0f,0.0f },
    { 30.0f,   1.0f,  0.0f,  0.0f,  0.00f, 0, 0, 14.445f,0,0, 90,10,-5, 1.0f,0.0f,0.0f },
    { 30.0f,   1.0f,  0.0f,  0.0f,  0.00f, 1, 0, 14.445f,0,0, 90,10,-5, 1.0f,0.0f,0.0f },
    { 30.0f,   1.0f,  0.0f,  0.0f,  0.00f, 0, 0, 14.0f,0,5.0f, 90,10,-5, 1.0f,0.0f,0.0f },
};

static void scenario_derivative(void)
{
    int k, i;

    printf("[derivative]\n");
    for (k = 0; k < 15; k++) {
        RigidBodyInfo *ri;
        RigidBody *rb = fresh(1450.0f, 900.0f, 3200.0f, 3600.0f, &ri);
        float out[RIGIDBODY_STATE_FLOATS];
        float *r;

        rb->SpeedLimiter = DC[k].speedlim;
        rb->CatchUpMultiplier = DC[k].catchup;
        rb->MaxMomentZ = DC[k].maxmz;
        rb->State.MotionDampingFactor = DC[k].mdf;
        rb->IsHP = DC[k].ishp;
        rb->MotionDamping = DC[k].motiondamp;

        rb->State.R.v0.x = 0.6f; rb->State.R.v0.y = 0.8f;
        rb->State.R.v0.z = DC[k].rzz;
        rb->State.R.v1.x = -0.8f; rb->State.R.v1.y = 0.6f;
        rb->State.R.v3.x = 4.0f; rb->State.R.v3.y = -2.0f;

        rb->Velocity.x = DC[k].vx; rb->Velocity.y = DC[k].vy;
        rb->Velocity.z = DC[k].vz; rb->Velocity.w = 0.5f;
        rb->AngularVelocity.x = DC[k].wx; rb->AngularVelocity.y = DC[k].wy;
        rb->AngularVelocity.z = DC[k].wz; rb->AngularVelocity.w = -0.5f;
        rb->ForceAccumulator.x = DC[k].fax; rb->ForceAccumulator.y = DC[k].fay;
        rb->ForceAccumulator.z = DC[k].faz; rb->ForceAccumulator.w = 1.5f;
        rb->MomentAccumulator.x = 2.0f; rb->MomentAccumulator.y = -3.0f;
        rb->MomentAccumulator.z = DC[k].faz * 1.5f;
        rb->MomentAccumulator.w = -2.5f;
        fill_vec(&rb->State.P, 500.0f);
        fill_vec(&rb->State.L, -250.0f);

        for (i = 0; i < RIGIDBODY_STATE_FLOATS; i++)
            out[i] = 1000.0f + (float)i;

        r = rigidbody_get_derivative(rb, out);
        printf("case %d returns out %d\n", k, r == out);
        for (i = 0; i < RIGIDBODY_STATE_FLOATS; i++)
            printf("d[%2d] %.9g\n", i, out[i]);
        // The speed limiter is allowed to rewrite the accumulator.
        pv("FA-after", &rb->ForceAccumulator);

        free(rb);
        free(ri);
    }
}

// ------------------------------------------------- state array, accessors

static void scenario_state_array(void)
{
    RigidBodyInfo *ri;
    RigidBody *rb = fresh(1450.0f, 900.0f, 3200.0f, 3600.0f, &ri);
    float buf[RIGIDBODY_STATE_FLOATS];
    int i;

    printf("[state-array]\n");
    printf("getsize %d\n", rigidbody_get_size(rb));
    printf("getstate is state %d\n", rigidbody_get_state(rb) == &rb->State);

    fill_vec(&rb->State.X, 1.0f);
    fill_mat(&rb->State.R, 20.0f);
    fill_vec(&rb->State.P, 40.0f);
    fill_vec(&rb->State.L, 60.0f);
    rb->State.MotionDampingFactor = 80.0f;

    for (i = 0; i < RIGIDBODY_STATE_FLOATS; i++)
        buf[i] = -1.0f - (float)i;
    rigidbody_get_state_array(rb, buf);
    for (i = 0; i < RIGIDBODY_STATE_FLOATS; i++)
        printf("get[%2d] %.9g\n", i, buf[i]);

    for (i = 0; i < RIGIDBODY_STATE_FLOATS; i++)
        buf[i] = 500.0f + (float)i;
    rigidbody_set_state_array(rb, buf);
    pv("X", &rb->State.X);
    pm("R", &rb->State.R);
    pv("P", &rb->State.P);
    pv("L", &rb->State.L);
    pf("mdf", rb->State.MotionDampingFactor);

    // The setters, and then the getters as byte offsets from the object,
    // because every vector and matrix getter answers a pointer in.
    {
        bVector4 v;
        bMatrix4 m;
        fill_vec(&v, 7.0f);
        fill_mat(&m, 300.0f);
        rigidbody_set_l(rb, &v); pv("set_l", &rb->State.L);
        rigidbody_set_p(rb, &v); pv("set_p", &rb->State.P);
        rigidbody_set_x(rb, &v); pv("set_x", &rb->State.X);
        rigidbody_set_r(rb, &m); pm("set_r", &rb->State.R);
        rigidbody_set_motion_damping(rb, -3);
        printf("set_md %d\n", rb->MotionDamping);
        rigidbody_set_is_hp(rb, 300);
        printf("set_ishp %d\n", rb->IsHP);
        rigidbody_set_catch_up_multiplier(rb, 1.75f);
        pf("set_catchup", rb->CatchUpMultiplier);
        rigidbody_set_speed_limiter(rb, 44.5f);
        pf("set_speedlim", rb->SpeedLimiter);
        rigidbody_set_max_moment_z(rb, -9.25f);
        pf("set_maxmz", rb->MaxMomentZ);
    }

#define D(name, e) printf("ptr %-10s %td\n", name, \
    (ptrdiff_t)((char *)(e) - (char *)rb))
    D("Ibi", rigidbody_get_inverse_inertia_tensor(rb));
    D("FA", rigidbody_get_accumulated_forces(rb));
    D("cog", rigidbody_get_center_of_gravity(rb));
    D("Matrix", rigidbody_get_matrix(rb));
    D("L", rigidbody_get_angular_momentum(rb));
    D("W", rigidbody_get_angular_velocity(rb));
    D("R", rigidbody_get_rotation(rb));
    D("P", rigidbody_get_momentum(rb));
    D("V", rigidbody_get_velocity(rb));
    D("X", rigidbody_get_position(rb));
#undef D
    pf("massinv", rigidbody_get_inverse_mass(rb));
    pf("mass", rigidbody_get_mass(rb));

    free(rb);
    free(ri);
}

int main(void)
{
    scenario_layout();
    scenario_ctor();
    scenario_inertia();
    scenario_setstate();
    scenario_apply();
    scenario_test_impulse();
    scenario_star();
    scenario_aux();
    scenario_derivative();
    scenario_state_array();
    return 0;
}
