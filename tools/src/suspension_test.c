// Transcript harness for Suspension.
// Cross-checked by tools/suspension_check.py, which models the same
// behaviour from the disassembly without reading this file.

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bmath.h"
#include "suspension.h"

static unsigned fbits(float f)
{
    unsigned u;
    memcpy(&u, &f, 4);
    return u;
}

static void pf(const char *tag, float x)
{
    printf("%s %.9g\n", tag, x);
}

static void pv(const char *tag, const bVector4 *v)
{
    printf("%s %.9g %.9g %.9g %.9g\n", tag, v->x, v->y, v->z, v->w);
}

static void pm(const char *tag, const bMatrix4 *m)
{
    const float *p = (const float *)m;
    int j;
    for (j = 0; j < 16; j++)
        printf("%s[%2d] %.9g\n", tag, j, p[j]);
}

// --------------------------------------------------------------- the seams
//
// Stand-ins for the two Wheel methods. FindDrivingSurface records what it
// was handed and returns whatever the scenario asked for, so the height
// arithmetic can be steered into each of its branches while the recorded
// position still pins the transform that produced it. ExchangeZForces
// records its two arguments and returns a closed form of the second.

static float    g_surface_return;
static int      g_surface_calls;
static bVector4 g_surface_pos;
static float    g_surface_r0x;

static float fake_find_driving_surface(Wheel *w, const bVector4 *pos,
                                       const bMatrix4 *r)
{
    (void)w;
    g_surface_calls++;
    g_surface_pos = *pos;
    g_surface_r0x = r->v0.x;
    return g_surface_return;
}

static int   g_exchange_calls;
static int32_t g_exchange_touching;
static float g_exchange_z;

static float fake_exchange_z_forces(Wheel *w, int32_t touching, float z)
{
    (void)w;
    g_exchange_calls++;
    g_exchange_touching = touching;
    g_exchange_z = z;
    return z * 0.75f - 1.5f;
}

// ------------------------------------------------------------- the layout

static void scenario_layout(void)
{
    printf("[layout]\n");
    printf("ptr %zu\n", sizeof(void *));
    printf("slack %zu\n", SUSPENSION_SLACK);
    printf("sizeof Suspension %zu\n", sizeof(Suspension));
    printf("sizeof expected %zu\n", SUSPENSION_SIZEOF);
    printf("sizeof SuspensionState %zu\n", sizeof(SuspensionState));
    printf("sizeof SuspensionInfo %zu\n", sizeof(SuspensionInfo));
    printf("sizeof WheelInfo %zu\n", sizeof(WheelInfo));
    printf("sizeof bVector4 %zu\n", sizeof(bVector4));
    printf("sizeof bMatrix4 %zu\n", sizeof(bMatrix4));

#define OFF(t, f) printf("off %-24s %zu\n", #t "." #f, offsetof(t, f))
    OFF(Suspension, pNext);
    OFF(Suspension, pPrev);
    OFF(Suspension, _vtable);
    OFF(Suspension, SI);
    OFF(Suspension, pSwayBar);
    OFF(Suspension, State);
    OFF(Suspension, Force);
    OFF(Suspension, Position);
    OFF(Suspension, Matrix);
    OFF(Suspension, TouchingGround);
    OFF(Suspension, MagicForce);
    OFF(Suspension, RestLoad);
    OFF(Suspension, RestPosition);
    OFF(Suspension, pWheel);
    OFF(Suspension, pBody);
    OFF(Suspension, pSteering);
    OFF(Suspension, WheelPosition);
    OFF(Suspension, GroundForce);
    OFF(SuspensionState, z);
    OFF(SuspensionState, v);
#undef OFF

    // The extents, because offsets do not pin them: an array can be
    // shortened and padded behind without moving anything after it.
    printf("arr Damping %zu\n", sizeof(((SuspensionInfo *)0)->Damping));
    printf("arr BumpStop %zu\n", sizeof(((SuspensionInfo *)0)->BumpStop));
    printf("arr _pad0 %zu\n", sizeof(((Suspension *)0)->_pad0));
    printf("arr _pad1 %zu\n", sizeof(((Suspension *)0)->_pad1));

    // Wheel is a layout claim only, and every offset Suspension reaches
    // for is one the disassembly pins independently.
    printf("sizeof Wheel %zu\n", sizeof(Wheel));
#define WOFF(f) printf("woff %-20s %zu\n", #f, offsetof(Wheel, f))
    WOFF(WI);
    WOFF(State);
    WOFF(WorldMatrix);
    WOFF(CarMatrix);
    WOFF(Velocity);
    WOFF(WorldGroundForce);
    WOFF(ContactPoint);
    WOFF(ContactNormal);
    WOFF(Damage);
#undef WOFF

    // _pad2 stands in for a quadword alignment this port's bVector4 does
    // not have. Its extent is the whole of the claim: shorten it and every
    // offset behind it slides, on the handheld only.
    printf("arr w_pad2 %zu\n", sizeof(((Wheel *)0)->_pad2));

    printf("vtable Suspension %08x\n", (unsigned)SUSPENSION_VTABLE);
    printf("vtable PhysicsComponent %08x\n", (unsigned)PHYSICSCOMPONENT_VTABLE);
    printf("state floats %d\n", SUSPENSION_STATE_FLOATS);

    // The tuning set, as bits. These are .sdata values the debug menu
    // could move, so the transcript pins the ones the ELF ships.
    printf("g LoadFactor %08x\n", fbits(gLoadFactor));
    printf("g WheelForceFrame %d\n", (int)gWheelForceFrame);
    printf("g TireForceEllipseRatio %08x\n", fbits(gTireForceEllipseRatio));
    printf("g NoSlipCorrectionFactor %08x\n", fbits(gNoSlipCorrectionFactor));
    printf("g UglyTimestepHack %08x\n", fbits(gUglyTimestepHack));
    printf("g GroundPenaltyImpulse %08x\n", fbits(gGroundPenaltyImpulse));
    printf("g GroundPenaltyForce %08x\n", fbits(gGroundPenaltyForce));
    printf("g MaxGroundPenetration %08x\n", fbits(gMaxGroundPenetration));
    printf("g ProgressiveDampingFactor %08x\n",
           fbits(gProgressiveDampingFactor));
    printf("g NoWheels %d\n", (int)gNoWheels);
    printf("const epsilon %08x\n", fbits(SUSPENSION_TIMESTEP_EPSILON));
    printf("const halfpi  %08x\n", fbits(SUSPENSION_IMAGE_HALF_PI));
    printf("true  halfpi  %08x\n", fbits((float)1.57079632679489661923));
}

// --------------------------------------------------------------- fixtures

static SuspensionInfo *make_si(void)
{
    SuspensionInfo *si = calloc(1, sizeof(SuspensionInfo));
    si->Progression = 0.35f;
    si->Stiffness = 42000.0f;
    si->Damping[0] = 2600.0f;   // chosen when v > 0
    si->Damping[1] = 4100.0f;   // chosen when v <= 0
    si->SwayBarStiffness = 900.0f;
    si->BumpStop[0] = 0.18f;    // compression limit
    // Droop limit. -0.25 rather than a rounder-looking -0.22 because the
    // two stop cases below have to land on their stop *exactly*, and
    // -0.22 cannot be reached. ComputeAuxiliaries computes
    // `(stop - Radius) + Radius`; for the compression stop that is a
    // subtraction of two positives within a factor of two, exact by
    // Sterbenz, so it round-trips. For a negative stop the magnitudes
    // add instead, and at 0.57 the ulp is twice the ulp at 0.22, so the
    // sum can only land on every other float near the stop -- and
    // -0.22f, 0xbe6147ae, is not one of them. No float return value
    // reaches it. -0.25f does, because 0.25 + 0.32f happens to be exact.
    si->BumpStop[1] = -0.25f;
    si->MaxRenderingCompression = 0.12f;
    return si;
}

static WheelInfo *make_wi(void)
{
    WheelInfo *wi = calloc(1, sizeof(WheelInfo));
    wi->PositionX = 1.4f;
    wi->PositionY = 0.78f;
    wi->PositionZ = -0.35f;
    wi->Radius = 0.32f;
    wi->Width = 0.21f;
    wi->WheelNumber = 1;
    return wi;
}

static Wheel *make_wheel(const WheelInfo *wi)
{
    Wheel *w = calloc(1, sizeof(Wheel));
    w->WI = wi;
    w->State.a = 0.75f;
    w->State.w = 31.0f;
    w->Damage = 0.0f;
    w->ContactPoint.x = 1.5f;
    w->ContactPoint.y = 0.8f;
    w->ContactPoint.z = -0.4f;
    w->ContactPoint.w = 0.25f;
    w->ContactNormal.x = 0.1f;
    w->ContactNormal.y = -0.2f;
    w->ContactNormal.z = 0.96f;
    w->ContactNormal.w = 0.5f;
    w->WorldGroundForce.x = 120.0f;
    w->WorldGroundForce.y = -45.0f;
    w->WorldGroundForce.z = 310.0f;
    w->WorldGroundForce.w = 7.0f;
    return w;
}

// A body with everything Suspension reads set by hand. RigidBody has a
// checker of its own; this one only needs its fields to be known.
static RigidBody *make_body(int rotated)
{
    RigidBody *b = calloc(1, sizeof(RigidBody));

    b->State.X.x = 10.0f;
    b->State.X.y = -4.0f;
    b->State.X.z = 2.5f;
    b->State.X.w = 0.125f;

    bIdentity(&b->State.R);
    if (rotated) {
        // A yaw of about 0.3 rad, written out rather than composed, so
        // the transcript does not depend on a rotation helper.
        b->State.R.v0.x = 0.955336489f;
        b->State.R.v0.y = 0.295520207f;
        b->State.R.v1.x = -0.295520207f;
        b->State.R.v1.y = 0.955336489f;
    }

    bIdentity(&b->Matrix);
    b->Matrix.v0.x = 0.8f;
    b->Matrix.v1.y = 0.9f;
    b->Matrix.v2.z = 1.1f;
    b->Matrix.v3.x = 10.0f;
    b->Matrix.v3.y = -4.0f;
    b->Matrix.v3.z = 2.5f;

    b->Velocity.x = 12.0f;
    b->Velocity.y = 0.5f;
    b->Velocity.z = -0.25f;
    b->Velocity.w = 0.75f;

    b->AngularVelocity.x = 0.05f;
    b->AngularVelocity.y = -0.12f;
    b->AngularVelocity.z = 0.9f;
    b->AngularVelocity.w = 0.4f;

    b->CenterOfGravity.x = 0.05f;
    b->CenterOfGravity.y = 0.0f;
    b->CenterOfGravity.z = 0.18f;
    b->CenterOfGravity.w = 0.5f;

    b->Mass = 1450.0f;
    b->Mass_inv = 1.0f / 1450.0f;
    return b;
}

// Fill the object with a recognisable pattern first, so a field the
// constructor is supposed to leave alone is visible as itself and a field
// it is supposed to write shows if it does not.
static void scribble(Suspension *s)
{
    unsigned char *p = (unsigned char *)s;
    size_t i;
    for (i = 0; i < sizeof(Suspension); i++)
        p[i] = (unsigned char)(0xA5 ^ (i * 7));
}

static void __attribute__((unused)) dump_state(const char *tag, Suspension *s)
{
    printf("%s vtable %08x\n", tag, (unsigned)s->_vtable);
    printf("%s wheelpos %d\n", tag, (int)s->WheelPosition);
    printf("%s swaybar_null %d\n", tag, s->pSwayBar == NULL);
    printf("%s si_set %d\n", tag, s->SI != NULL);
    printf("%s touching %d\n", tag, (int)s->TouchingGround);
    pf("  z", s->State.z);
    pf("  v", s->State.v);
    pf("  Force", s->Force);
    pf("  RestLoad", s->RestLoad);
    pf("  MagicForce", s->MagicForce);
    pf("  GroundForce", s->GroundForce);
    pv("  Position", &s->Position);
    pv("  RestPosition", &s->RestPosition);
}

// ------------------------------------------------------- construction

static void scenario_init(void)
{
    SuspensionInfo *si = make_si();
    WheelInfo *wi = make_wi();
    Wheel *w = make_wheel(wi);
    RigidBody *b = make_body(0);
    Suspension *s = malloc(sizeof(Suspension));

    printf("[init]\n");

    scribble(s);
    suspension_init(s, 2, b, w, NULL, si);

    // The nine stores, and the fields left as the scribble found them.
    printf("vtable %08x\n", (unsigned)s->_vtable);
    printf("wheelpos %d\n", (int)s->WheelPosition);
    printf("swaybar_null %d\n", s->pSwayBar == NULL);
    printf("body_match %d\n", s->pBody == b);
    printf("wheel_match %d\n", s->pWheel == w);
    printf("steering_null %d\n", s->pSteering == NULL);
    printf("si_match %d\n", s->SI == si);
    // Untouched by the constructor: still the scribble.
    printf("scribble touching %d\n", (int)s->TouchingGround);
    printf("scribble links %08x %08x\n", (unsigned)s->pNext, (unsigned)s->pPrev);
    pf("scribble z", s->State.z);

    suspension_fini(s);
    printf("after fini vtable %08x\n", (unsigned)s->_vtable);

    free(s);
    free(b);
    free(w);
    free(wi);
    free(si);
}

// --------------------------------------------------------------- calibrate

static void scenario_calibrate(void)
{
    static const float LOADS[3] = { 0.0f, 3400.0f, -125.5f };
    SuspensionInfo *si = make_si();
    WheelInfo *wi = make_wi();
    Wheel *w = make_wheel(wi);
    int i;

    printf("[calibrate]\n");

    for (i = 0; i < 3; i++) {
        RigidBody *b = make_body(i == 2);
        Suspension *s = calloc(1, sizeof(Suspension));
        suspension_init(s, 0, b, w, NULL, si);
        suspension_calibrate(s, LOADS[i]);
        printf("case %d\n", i);
        pf("  RestLoad", s->RestLoad);
        pv("  RestPosition", &s->RestPosition);
        // The w lane is Radius minus the body's w, not a zero.
        pf("  wi_radius", wi->Radius);
        pf("  cog_w", b->CenterOfGravity.w);
        free(s);
        free(b);
    }

    free(w);
    free(wi);
    free(si);
}

// ------------------------------------------------------------- the state

static void scenario_state(void)
{
    static const float IN[4][2] = {
        { 0.0f, 0.0f }, { 0.125f, -3.5f }, { -0.5f, 12.25f }, { 1e-7f, 1e7f }
    };
    SuspensionInfo *si = make_si();
    Suspension *s = calloc(1, sizeof(Suspension));
    float out[4];
    int i;

    printf("[state]\n");
    s->SI = si;

    printf("size %d\n", (int)suspension_get_size(s));
    printf("state_ptr_offset %zu\n",
           (size_t)((char *)suspension_get_state(s) - (char *)s));

    for (i = 0; i < 4; i++) {
        suspension_set_state_array(s, IN[i]);
        out[0] = out[1] = out[2] = out[3] = -999.0f;
        suspension_get_state_array(s, out);
        printf("case %d\n", i);
        pf("  z", out[0]);
        pf("  v", out[1]);
        // Only two floats move; the third is the guard.
        pf("  guard", out[2]);

        out[0] = out[1] = out[2] = -999.0f;
        suspension_get_derivative(s, out);
        pf("  dz", out[0]);
        pf("  dv", out[1]);
        pf("  dguard", out[2]);
    }

    suspension_set_state(s);
    pf("cleared z", s->State.z);
    pf("cleared v", s->State.v);

    free(s);
    free(si);
}

// ------------------------------------------------------------- accessors

static void scenario_accessors(void)
{
    // Velocities either side of zero, and heights around both the bump
    // stop and the rendering limit.
    static const float VS[5] = { -3.0f, -0.0f, 0.0f, 1e-20f, 7.5f };
    static const float ZS[6] = { -0.3f, 0.0f, 0.11f, 0.12f, 0.13f, 0.18f };
    SuspensionInfo *si = make_si();
    Suspension *s = calloc(1, sizeof(Suspension));
    int i;

    printf("[accessors]\n");
    s->SI = si;
    s->WheelPosition = 3;
    s->MagicForce = 0.0f;

    pf("progression", suspension_get_progression(s));
    pf("stiffness", suspension_get_stiffness(s));
    pf("swaybar", suspension_get_sway_bar_stiffness(s));
    printf("wheelpos %d\n", (int)suspension_get_wheel_position(s));
    printf("rest_off %zu\n",
           (size_t)((char *)suspension_get_rest_position(s) - (char *)s));
    printf("matrix_off %zu\n",
           (size_t)((char *)suspension_get_matrix(s) - (char *)s));

    for (i = 0; i < 5; i++) {
        s->State.v = VS[i];
        printf("damping %d %.9g %.9g\n", i, VS[i], suspension_get_damping(s));
    }

    for (i = 0; i < 6; i++) {
        s->State.z = ZS[i];
        printf("hack %d %.9g %.9g bottomed %d\n", i, ZS[i],
               suspension_get_compression_hack_offset(s),
               (int)suspension_is_bottomed_out(s));
    }

    s->State.z = 0.055f;
    s->State.v = -1.25f;
    pf("height", suspension_get_height(s));
    pf("velocity", suspension_get_velocity(s));

    suspension_set_magic_force(s, 812.5f);
    pf("magic", s->MagicForce);

    {
        Suspension *other = calloc(1, sizeof(Suspension));
        suspension_set_sway_bar(s, other);
        printf("swaybar_set %d\n", s->pSwayBar == other);
        free(other);
    }

    free(s);
    free(si);
}

// -------------------------------------------------- the point velocity

static void scenario_point_velocity(void)
{
    static const float V[3][4] = {
        { 1.0f, 2.0f, 3.0f, 0.5f },
        { 0.0f, 0.0f, 0.0f, 0.0f },
        { -12.5f, 3.25f, 0.125f, -2.0f },
    };
    static const float W[3][4] = {
        { 0.1f, 0.2f, 0.3f, 9.0f },
        { 1.0f, 0.0f, 0.0f, -1.0f },
        { 0.0f, 0.0f, 2.0f, 0.25f },
    };
    static const float R[3][4] = {
        { 1.5f, -0.5f, 0.25f, 100.0f },
        { 0.0f, 1.0f, 0.0f, 50.0f },
        { 2.0f, 2.0f, 2.0f, 0.0f },
    };
    int i;

    printf("[point-velocity]\n");
    for (i = 0; i < 3; i++) {
        bVector4 v, w, r, out;
        memcpy(&v, V[i], 16);
        memcpy(&w, W[i], 16);
        memcpy(&r, R[i], 16);
        out.x = out.y = out.z = out.w = -999.0f;
        suspension_get_point_velocity(&out, &v, &w, &r);
        printf("case %d\n", i);
        pv("  out", &out);
    }
}

// ----------------------------------------------------- the main pass

struct auxcase {
    const char *name;
    float surface;   // what the driving-surface stand-in returns
    float oldz;      // the height the previous frame left behind
    int   rotated;   // body orientation
    int   steered;   // hang an Ackerman steering off it
    float damage;    // wheel damage, the wobble amplitude
    float restload;
    float swayz;     // the opposite corner's height
};

// `surface` is what the stand-in returns, which is the raw driving
// surface -- ComputeAuxiliaries adds WheelInfo::Radius (0.32 here) to it
// before either bump stop is consulted. Every value below is written as
// the height it is aiming for minus that radius, so the arithmetic is
// visible rather than a number that happens to land right.
#define R_ 0.32f
static const struct auxcase AUX[] = {
    // Straight through the middle: between the stops, wheel down, and
    // rising, so the damper takes SI->Damping[0].
    { "mid",          0.05f - R_,  0.01f, 0, 0, 0.0f, 3400.0f,  0.03f },
    // Past the compression stop: clamps, and the excess is a penetration
    // small enough to survive the sanity check.
    { "bottomed",     0.25f - R_,  0.17f, 0, 0, 0.0f, 3400.0f,  0.03f },
    // Past it by more than gMaxGroundPenetration: the excess is discarded.
    { "deep",         0.40f - R_,  0.17f, 0, 0, 0.0f, 3400.0f,  0.03f },
    // Below the droop stop: the wheel has left the ground.
    { "airborne",    -0.50f - R_,  0.05f, 0, 0, 0.0f, 3400.0f,  0.03f },
    // The same, with a rest load big enough that the spring sum would
    // come out *positive* if the airborne branch fell through instead of
    // returning. With the shipped 3400 it would come out at about -7200
    // and floor back to the zero the branch already wrote, which makes
    // the early return invisible -- the same shape as the two globals
    // that ship at a hiding value.
    { "airborne-loaded", -0.50f - R_, 0.05f, 0, 0, 0.0f, 50000.0f, 0.03f },
    // Exactly on each stop, where neither comparison is strict -- both
    // land in the else, so sitting on the droop stop still counts as
    // touching the ground.
    { "on-bump",      0.18f - R_,  0.10f, 0, 0, 0.0f, 3400.0f, 0.03f },
    { "on-droop",    -0.25f - R_,  0.10f, 0, 0, 0.0f, 3400.0f, 0.03f },
    // A rotated body, so the transform is not the identity.
    { "rotated",      0.05f - R_,  0.01f, 1, 0, 0.0f, 3400.0f,  0.03f },
    // Steered, so the matrix goes through the steering array.
    { "steered",      0.05f - R_,  0.01f, 1, 1, 0.0f, 3400.0f,  0.03f },
    // Damaged, so the wobble runs.
    { "damaged",      0.05f - R_,  0.01f, 0, 0, 0.35f, 3400.0f, 0.03f },
    { "damaged-rot",  0.05f - R_,  0.01f, 1, 1, -0.9f, 3400.0f, 0.03f },
    // Falling rather than rising, which is the other damper.
    { "extending",    0.05f - R_,  0.09f, 0, 0, 0.0f, 3400.0f,  0.03f },
    // A negative height, where the progression term is clamped away but
    // the whole spring is still scaled by a negative z. The rest load is
    // 8000 and not the usual 3400 for the same reason `airborne-loaded`
    // exists: at 3400 the total lands under zero, the floor takes it to
    // zero, and whether the progression was clamped stops mattering.
    { "negative-z",  -0.10f - R_,  0.01f, 0, 0, 0.0f, 8000.0f, -0.05f },
    // A sway bar and a rest load that drive the total below zero, where
    // Force floors at zero rather than going negative.
    { "force-floor",  0.05f - R_,  0.01f, 0, 0, 0.0f, -90000.0f, 4.0f },
};
#undef R_

static void scenario_compute_aux(void)
{
    SuspensionInfo *si = make_si();
    WheelInfo *wi = make_wi();
    size_t n = sizeof(AUX) / sizeof(AUX[0]);
    size_t k;

    printf("[compute-aux]\n");

    gWheelFindDrivingSurfaceFn = fake_find_driving_surface;

    for (k = 0; k < n; k++) {
        const struct auxcase *c = &AUX[k];
        Wheel *w = make_wheel(wi);
        RigidBody *b = make_body(c->rotated);
        Suspension *s = calloc(1, sizeof(Suspension));
        Suspension *sway = calloc(1, sizeof(Suspension));
        TwoWheelAckermanSteering *ack = NULL;
        CarTypeInfo *cti = NULL;

        if (c->steered) {
            static const float gx[4] = { 1.40f, 1.35f, -1.30f, -1.25f };
            static const float gy[4] = { 0.78f, -0.78f, 0.80f, -0.80f };
            int i;
            cti = calloc(1, sizeof(CarTypeInfo));
            for (i = 0; i < 4; i++) {
                cti->Wheels[i].PositionX = gx[i];
                cti->Wheels[i].PositionY = gy[i];
                cti->Wheels[i].Radius = 0.32f;
                cti->Wheels[i].WheelNumber = i;
            }
            ack = calloc(1, sizeof(TwoWheelAckermanSteering));
            ackerman_init(ack, cti);
            ackerman_set_steering(ack, (uint16_t)0x0a00);
        }

        w->Damage = c->damage;
        suspension_init(s, 1, b, w,
                        ack ? &ack->base : NULL, si);
        suspension_calibrate(s, c->restload);
        s->State.z = c->oldz;
        s->State.v = -123.0f;      // overwritten by the difference
        sway->State.z = c->swayz;
        suspension_set_sway_bar(s, sway);

        g_surface_return = c->surface;
        g_surface_calls = 0;
        g_surface_pos.x = g_surface_pos.y = g_surface_pos.z
            = g_surface_pos.w = -999.0f;

        suspension_compute_auxiliaries(s);

        printf("case %s\n", c->name);
        printf("  surface_calls %d\n", g_surface_calls);
        pv("  surface_pos", &g_surface_pos);
        pf("  surface_r0x", g_surface_r0x);
        printf("  touching %d\n", (int)s->TouchingGround);
        pf("  z", s->State.z);
        pf("  v", s->State.v);
        pf("  Force", s->Force);
        pv("  Position", &s->Position);
        pm("  Matrix", &s->Matrix);
        pm("  CarMatrix", &w->CarMatrix);
        pm("  WorldMatrix", &w->WorldMatrix);
        pv("  WheelVelocity", &w->Velocity);
        printf("  bottomed %d\n", (int)suspension_is_bottomed_out(s));
        pf("  hack", suspension_get_compression_hack_offset(s));

        free(s);
        free(sway);
        free(b);
        free(w);
        if (ack) free(ack);
        if (cti) free(cti);
    }

    // gGroundPenaltyForce ships as zero, so every case above computes a
    // penetration that then multiplies by nothing -- `bottomed` and
    // `deep` come out with the same Force to the bit despite differing in
    // whether the excess survived the sanity check. The term is only
    // observable with the global moved off its shipped value, which is a
    // state the debug menu could put the program in, so the same three
    // heights run again with it set.
    {
        static const float SURF[3] = { 0.05f - 0.32f, 0.25f - 0.32f,
                                       0.40f - 0.32f };
        static const char *NAMES[3] = { "pen-none", "pen-small", "pen-huge" };
        int i;
        gGroundPenaltyForce = 800.0f;
        for (i = 0; i < 3; i++) {
            Wheel *w = make_wheel(wi);
            RigidBody *b = make_body(0);
            Suspension *s = calloc(1, sizeof(Suspension));
            Suspension *sway = calloc(1, sizeof(Suspension));
            suspension_init(s, 1, b, w, NULL, si);
            suspension_calibrate(s, 3400.0f);
            s->State.z = 0.17f;
            sway->State.z = 0.03f;
            suspension_set_sway_bar(s, sway);
            g_surface_return = SURF[i];
            suspension_compute_auxiliaries(s);
            printf("case %s\n", NAMES[i]);
            pf("  z", s->State.z);
            pf("  v", s->State.v);
            pf("  Force", s->Force);
            free(s);
            free(sway);
            free(b);
            free(w);
        }
        gGroundPenaltyForce = 0.0f;
    }

    // gUglyTimestepHack ships as 1.0, so the divide that makes a velocity
    // out of the height difference divides by one and the epsilon test
    // never takes its false arm -- neither the division nor the guard is
    // observable in the shipped build. Same remedy as the penalty force:
    // move the global, which is a state the debug menu could produce, and
    // run the same height three times. The third value is below the
    // epsilon, so v is left exactly as the scenario set it.
    {
        static const float HACKS[3] = { 0.5f, 2.0f, 0.00005f };
        static const char *NAMES[3] = { "hack-half", "hack-two", "hack-tiny" };
        int i;
        for (i = 0; i < 3; i++) {
            Wheel *w = make_wheel(wi);
            RigidBody *b = make_body(0);
            Suspension *s = calloc(1, sizeof(Suspension));
            Suspension *sway = calloc(1, sizeof(Suspension));
            suspension_init(s, 1, b, w, NULL, si);
            suspension_calibrate(s, 3400.0f);
            s->State.z = 0.01f;
            s->State.v = -123.0f;
            sway->State.z = 0.03f;
            suspension_set_sway_bar(s, sway);
            g_surface_return = 0.05f - 0.32f;
            gUglyTimestepHack = HACKS[i];
            suspension_compute_auxiliaries(s);
            printf("case %s\n", NAMES[i]);
            pf("  z", s->State.z);
            pf("  v", s->State.v);
            pf("  Force", s->Force);
            free(s);
            free(sway);
            free(b);
            free(w);
        }
        gUglyTimestepHack = 1.0f;
    }

    gWheelFindDrivingSurfaceFn = NULL;

    // And once with the seam left NULL, which is the state the handheld
    // is in until the Wheel slice lands: the surface reads as zero and
    // the rest of the pass still runs.
    {
        Wheel *w = make_wheel(wi);
        RigidBody *b = make_body(0);
        Suspension *s = calloc(1, sizeof(Suspension));
        Suspension *sway = calloc(1, sizeof(Suspension));
        suspension_init(s, 1, b, w, NULL, si);
        suspension_calibrate(s, 3400.0f);
        suspension_set_sway_bar(s, sway);
        suspension_compute_auxiliaries(s);
        printf("case null-seam\n");
        printf("  touching %d\n", (int)s->TouchingGround);
        pf("  z", s->State.z);
        pf("  v", s->State.v);
        pf("  Force", s->Force);
        free(s);
        free(sway);
        free(b);
        free(w);
    }

    free(wi);
    free(si);
}

// ------------------------------------------------------- the force paths

static void scenario_resolve(void)
{
    static const float EXTRA[3] = { 0.0f, 250.0f, -80.0f };
    SuspensionInfo *si = make_si();
    WheelInfo *wi = make_wi();
    int touching, i;

    printf("[resolve-forces]\n");
    gWheelExchangeZForcesFn = fake_exchange_z_forces;

    for (touching = 0; touching < 2; touching++) {
        for (i = 0; i < 3; i++) {
            Wheel *w = make_wheel(wi);
            RigidBody *b = make_body(0);
            Suspension *s = calloc(1, sizeof(Suspension));
            suspension_init(s, 1, b, w, NULL, si);
            s->Force = 5200.0f;
            s->TouchingGround = touching;
            g_exchange_calls = 0;
            g_exchange_touching = -1;
            g_exchange_z = -999.0f;

            suspension_resolve_forces(s, EXTRA[i]);

            printf("case %d %d\n", touching, i);
            printf("  calls %d\n", g_exchange_calls);
            printf("  passed_touching %d\n", (int)g_exchange_touching);
            pf("  passed_z", g_exchange_z);
            pf("  GroundForce", s->GroundForce);

            free(s);
            free(b);
            free(w);
        }
    }

    gWheelExchangeZForcesFn = NULL;
    {
        Wheel *w = make_wheel(wi);
        RigidBody *b = make_body(0);
        Suspension *s = calloc(1, sizeof(Suspension));
        suspension_init(s, 1, b, w, NULL, si);
        s->Force = 5200.0f;
        s->TouchingGround = 1;
        suspension_resolve_forces(s, 10.0f);
        printf("case null-seam\n");
        pf("  GroundForce", s->GroundForce);
        free(s);
        free(b);
        free(w);
    }

    free(wi);
    free(si);
}

static void scenario_resolve_more(void)
{
    SuspensionInfo *si = make_si();
    WheelInfo *wi = make_wi();
    int touching, nowheels;

    printf("[resolve-more-forces]\n");

    for (touching = 0; touching < 2; touching++) {
        for (nowheels = 0; nowheels < 2; nowheels++) {
            Wheel *w = make_wheel(wi);
            RigidBody *b = make_body(0);
            Suspension *s = calloc(1, sizeof(Suspension));
            suspension_init(s, 1, b, w, NULL, si);
            s->TouchingGround = touching;
            gNoWheels = nowheels;

            suspension_resolve_more_forces(s);

            printf("case %d %d\n", touching, nowheels);
            pv("  ForceAccumulator", &b->ForceAccumulator);
            pv("  MomentAccumulator", &b->MomentAccumulator);

            free(s);
            free(b);
            free(w);
        }
    }

    gNoWheels = 0;
    free(wi);
    free(si);
}

// The contact normal decides the sign of the approach, and the first
// draft of this scenario got that wrong: it varied only the z lane, and
// with the body's velocity what it is every one of those normals came out
// approaching *away* from the surface. All four cases took the early
// return, and the entire body of the function -- the impulse, the mass,
// the gNoWheels path -- went unexercised without the transcript showing a
// gap. Five mutations survived on that alone. The whole normal varies
// now, and `grazing` sits on the boundary the comparison tests.
struct pencase {
    const char *name;
    float nx, ny, nz;
    int   rotated;
};

static const struct pencase PEN[] = {
    // Moving away from the surface: the early return.
    { "away",     0.1f, -0.2f,  0.96f, 0 },
    // Moving into it, so the impulse runs.
    { "into",    -0.1f,  0.2f, -0.96f, 0 },
    { "flat",    -0.1f,  0.2f,  0.0f,  0 },
    // A zero normal, so the three-lane dot is +0 and the approach is the
    // negation of that: -0. `-0 < 0` is false, so this falls *through*
    // the guard and applies a zero impulse -- and the returned -0 is
    // what tells a `<=` apart from a `<`.
    { "grazing",  0.0f,  0.0f,  0.0f,  0 },
    // And once with the body rotated, so the offset is not the position.
    { "rotated", -0.1f,  0.2f,  0.5f,  1 },
};

static void scenario_penalty(void)
{
    SuspensionInfo *si = make_si();
    WheelInfo *wi = make_wi();
    size_t n = sizeof(PEN) / sizeof(PEN[0]);
    size_t k;
    int nowheels;

    printf("[penalty]\n");

    for (k = 0; k < n; k++) {
        const struct pencase *c = &PEN[k];
        for (nowheels = 0; nowheels < 2; nowheels++) {
            Wheel *w = make_wheel(wi);
            RigidBody *b = make_body(c->rotated);
            Suspension *s = calloc(1, sizeof(Suspension));
            float j;

            suspension_init(s, 1, b, w, NULL, si);
            suspension_calibrate(s, 3400.0f);
            s->Position = s->RestPosition;
            s->Position.z += 0.04f;
            w->ContactNormal.x = c->nx;
            w->ContactNormal.y = c->ny;
            w->ContactNormal.z = c->nz;
            gNoWheels = nowheels;

            j = suspension_apply_ground_penalty_impulse(s);

            printf("case %s %d\n", c->name, nowheels);
            pf("  j", j);
            pv("  P", &b->State.P);
            pv("  L", &b->State.L);

            free(s);
            free(b);
            free(w);
        }
    }

    gNoWheels = 0;
    free(wi);
    free(si);
}

int main(void)
{
    scenario_layout();
    scenario_init();
    scenario_calibrate();
    scenario_state();
    scenario_accessors();
    scenario_point_velocity();
    scenario_compute_aux();
    scenario_resolve();
    scenario_resolve_more();
    scenario_penalty();
    return 0;
}
