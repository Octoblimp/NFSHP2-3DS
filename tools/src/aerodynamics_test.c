// Transcript harness for Aerodynamics. Cross-checked by
// tools/aerodynamics_check.py, which models the object from the
// disassembly and reuses rigidbody_check's model of ApplyForce and
// ApplyForceInFrame for what the three calls do to the body.
//
// ResolveForces writes nothing but the body's two accumulators and its
// out-parameter, so each case starts both accumulators at a value no
// force would produce and prints all four lanes of each afterwards: an
// Apply that assigned rather than added, or a force whose w lane was
// dropped, is visible that way.

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "aerodynamics.h"
#include "rigidbody.h"
#include "wheel.h"

// wheel.c owns this seam; the harness links Aerodynamics without Wheel.
ReplayShouldResetFn gReplayShouldResetFn;

static unsigned fbits(float f)
{
    unsigned u;
    memcpy(&u, &f, 4);
    return u;
}

static void pv(const char *tag, const bVector4 *v)
{
    printf("%s %.9g %.9g %.9g %.9g\n", tag, v->x, v->y, v->z, v->w);
}

static void set4(bVector4 *v, float x, float y, float z, float w)
{
    v->x = x;
    v->y = y;
    v->z = z;
    v->w = w;
}

static void dump_aero(const char *tag, const Aerodynamics *a,
                      const AeroInfo *ai, const RigidBody *rb)
{
    printf("%s ai %d body %d boost %.9g draft %.9g throttle %.9g ge %.9g\n",
           tag, a->AI == ai, a->pBody == rb, a->Boost, a->Draft,
           a->Throttle, a->GroundEffect);
}

// ------------------------------------------------------------ layout

static void s_layout(void)
{
    printf("[layout]\n");
    printf("sizeof %d slack %d\n", (int)sizeof(Aerodynamics),
           (int)AERODYNAMICS_SLACK);
    printf("off %d %d %d %d %d %d\n", (int)offsetof(Aerodynamics, AI),
           (int)offsetof(Aerodynamics, pBody),
           (int)offsetof(Aerodynamics, Boost),
           (int)offsetof(Aerodynamics, Draft),
           (int)offsetof(Aerodynamics, Throttle),
           (int)offsetof(Aerodynamics, GroundEffect));
    printf("aeroinfo %d %d %d %d %d\n", (int)sizeof(AeroInfo),
           (int)offsetof(AeroInfo, Drag),
           (int)offsetof(AeroInfo, FrontDownforce),
           (int)offsetof(AeroInfo, RearDownforce),
           (int)offsetof(AeroInfo, AutoBalanceDownforce));
    printf("body %d %d %d\n", (int)offsetof(RigidBody, Velocity),
           (int)offsetof(RigidBody, State.R.v0),
           (int)offsetof(RigidBody, State.R.v2.z));
    printf("consts %08x %08x %08x %08x\n", fbits(AERODYNAMICS_MIN_SPEED),
           fbits(AERODYNAMICS_FRONT_SHARE), fbits(AERODYNAMICS_REAR_SHARE),
           fbits(AERODYNAMICS_GROUND_EFFECT));
    printf("sdata %08x %08x\n", fbits(OffThrottleDragFactor),
           fbits(OffThrottleDragCenterHeight));
}

// The static initialiser writes x, y and z of each and never w. Every lane
// starts at a sentinel so a lane written twice or not at all shows.
static void s_static(void)
{
    printf("[static]\n");
    set4(&FrontDownforceLocation, 7.0f, 7.5f, 8.0f, 8.5f);
    set4(&RearDownforceLocation, -7.0f, -7.5f, -8.0f, -8.5f);
    aerodynamics_static_init();
    pv("front", &FrontDownforceLocation);
    pv("rear", &RearDownforceLocation);
    // What the rest of the transcript runs with: the image's .bss is zero
    // before the initialiser runs, so the w lanes are zero.
    FrontDownforceLocation.w = 0.0f;
    RearDownforceLocation.w = 0.0f;
}

// ------------------------------------------------------------- init

static void s_init(void)
{
    Aerodynamics a;
    AeroInfo ai = { 0.25f, 1.5f, 2.5f, 7.0f };
    RigidBody rb;

    printf("[init]\n");
    memset(&a, 0x5a, sizeof a);
    aerodynamics_init(&a, &rb, &ai);
    dump_aero("init", &a, &ai, &rb);
    aerodynamics_set_boost(&a, 1.5f);
    aerodynamics_set_draft(&a, 0.625f);
    aerodynamics_set_throttle(&a, 0.75f);
    aerodynamics_set_ground_effect(&a, 0.875f);
    dump_aero("set", &a, &ai, &rb);
    printf("at-speed %.9g\n", aerodynamics_get_downforce_at_speed(&a, 2.0f));
}

// ---------------------------------------------------------- resolve

typedef struct Case {
    const char *name;
    float vel[4];
    float r0[4], r1[4], r2[4], r3[4];
    float boost, draft, throttle, ge;
    float drag, front, rear;
    int   with_out;
} Case;

// R rows are the body axes in world space, as RigidBodyState keeps them:
// v0 forward, v1 left, v2 up, v3 the translation row bMulMatrixVec3 adds.
static const Case kCases[] = {
    // Level, straight ahead, full throttle, GroundEffect 0: the shipped
    // arm, with every factor 1.
    { "level", { 30.0f, 0.0f, 0.0f, 0.0f },
      { 1, 0, 0, 0 }, { 0, 1, 0, 0 }, { 0, 0, 1, 0 }, { 0, 0, 0, 1 },
      1.0f, 1.0f, 1.0f, 0.0f, 0.375f, 2.5f, 3.25f, 1 },
    // Off the throttle: the drag gains OffThrottleDragFactor - 1 over
    // 1 - Throttle, and Draft and Boost are not 1.
    { "coast", { 20.0f, 5.0f, -1.0f, 0.0f },
      { 0.96f, 0.28f, 0, 0 }, { -0.28f, 0.96f, 0, 0 }, { 0, 0, 1, 0 },
      { 0, 0, 0, 1 },
      1.25f, 0.8f, 0.3f, 0.0f, 0.4f, 1.5f, 2.0f, 1 },
    // GroundEffect exactly 0.5: c.le.s is inclusive, so the drag's point
    // drops and the up factor is forced to 1 although R.v2.z is 0.97.
    { "ge-half", { 12.0f, -3.0f, 0.5f, 0.0f },
      { 1, 0, 0, 0 }, { 0, 0.968245804f, -0.25f, 0 },
      { 0, 0.25f, 0.968245804f, 0 }, { 0, 0, 0, 1 },
      1.0f, 1.0f, 0.2f, 0.5f, 0.3f, 2.0f, 1.0f, 1 },
    // GroundEffect between 0 and 0.5: the second downforce arm, but not
    // the ground-effect point or the forced up factor.
    { "ge-low", { 25.0f, 2.0f, 0.0f, 0.0f },
      { 0.8f, 0.6f, 0, 0 }, { -0.6f, 0.8f, 0, 0 }, { 0, 0, 0.5f, 0 },
      { 3.0f, -2.0f, 1.0f, 1 },
      1.0f, 1.0f, 0.6f, 0.25f, 0.5f, 3.0f, 4.0f, 1 },
    // GroundEffect above 0.5, upside down: R.v2.z is negative, which the
    // first arm would floor to 0 and this arm replaces with 1.
    { "ge-inverted", { 18.0f, 0.0f, 4.0f, 0.0f },
      { 1, 0, 0, 0 }, { 0, -1, 0, 0 }, { 0, 0, -1, 0 }, { 0, 0, 0, 1 },
      1.0f, 1.5f, 0.0f, 0.75f, 0.25f, 1.25f, 0.75f, 1 },
    // Upside down with GroundEffect 0: the up factor floors at 0 and the
    // downforce is zero, but the drag is not.
    { "inverted", { 18.0f, 0.0f, 4.0f, 0.0f },
      { 1, 0, 0, 0 }, { 0, -1, 0, 0 }, { 0, 0, -1, 0 }, { 0, 0, 0, 1 },
      1.0f, 1.0f, 0.5f, 0.0f, 0.25f, 1.25f, 0.75f, 1 },
    // Backwards: the forward axis against the velocity is negative and
    // floors at 0.
    { "reverse", { -15.0f, 1.0f, 0.0f, 0.0f },
      { 1, 0, 0, 0 }, { 0, 1, 0, 0 }, { 0, 0, 1, 0 }, { 0, 0, 0, 1 },
      1.0f, 1.0f, 0.0f, 0.0f, 0.35f, 2.0f, 2.0f, 1 },
    // Standing still: speed 0, so the direction is the (1, 0, 0) default
    // and every force is zero -- -0 in places, which the w lanes show.
    { "still", { 0.0f, 0.0f, 0.0f, 0.0f },
      { 1, 0, 0, 0 }, { 0, 1, 0, 0 }, { 0, 0, 1, 0 }, { 0, 0, 0, 1 },
      1.0f, 1.0f, 1.0f, 0.0f, 0.3f, 2.0f, 2.0f, 1 },
    // Speed exactly the 1e-4 floor, sideways: the test is strict, so the
    // direction is the (1, 0, 0) default and c is R.v0.x, 0.6, although
    // the car is moving along y. sqrt(y * y) is y for this y.
    { "at-floor", { 0.0f, 9.99999975e-05f, 0.0f, 0.0f },
      { 0.6f, 0.8f, 0, 0 }, { -0.8f, 0.6f, 0, 0 }, { 0, 0, 1, 0 },
      { 0, 0, 0, 1 },
      1.0f, 1.0f, 1.0f, 0.0f, 0.3f, 2.0f, 2.0f, 1 },
    // One ulp above it: now the velocity is the direction, and c is
    // R.v0.y, 0.8.
    { "over-floor", { 0.0f, 0.000100000005f, 0.0f, 0.0f },
      { 0.6f, 0.8f, 0, 0 }, { -0.8f, 0.6f, 0, 0 }, { 0, 0, 1, 0 },
      { 0, 0, 0, 1 },
      1.0f, 1.0f, 1.0f, 0.0f, 0.3f, 2.0f, 2.0f, 1 },
    // Boost 2: s is half the speed, and the "direction" has length 2.
    { "boost", { 40.0f, 0.0f, 0.0f, 0.0f },
      { 1, 0, 0, 0 }, { 0, 1, 0, 0 }, { 0, 0, 1, 0 }, { 0, 0, 0, 1 },
      2.0f, 1.0f, 1.0f, 0.0f, 0.375f, 2.5f, 3.25f, 1 },
    // A velocity whose squares sum differently grouped the other way:
    // ((xx + yy) + zz), the VU's vaddy then vaddz, is the only order that
    // matches here.
    { "bracket", { 15.0f, 4.3f, 0.7f, 0.0f },
      { 0.96f, 0.28f, 0, 0 }, { -0.28f, 0.96f, 0, 0 }, { 0, 0, 1, 0 },
      { 0, 0, 0, 1 },
      1.0f, 1.0f, 0.4f, 0.0f, 0.35f, 1.5f, 2.0f, 1 },
    // Fast enough that the drag clamps at MaxForce: the moment is taken
    // from the unclamped force. The velocity's w lane is not zero, and
    // the vmulx scales it with the other three.
    { "clamp", { 150.0f, -40.0f, 10.0f, 2.0f },
      { 0.96f, -0.28f, 0, 0 }, { 0.28f, 0.96f, 0, 0 }, { 0, 0, 1, 0 },
      { 0, 0, 0, 1 },
      1.0f, 1.0f, 0.1f, 0.9f, 0.5f, 1.0f, 1.0f, 1 },
    // No out-parameter: the forces land and nothing else is written.
    { "no-out", { 22.0f, 1.0f, 0.0f, 0.0f },
      { 1, 0, 0, 0 }, { 0, 1, 0, 0 }, { 0, 0, 1, 0 }, { 0, 0, 0, 1 },
      1.0f, 1.0f, 1.0f, 0.0f, 0.375f, 2.5f, 3.25f, 0 },
    // A non-unit forward axis: R.v0 of length 2 scales c by 16 through
    // the fourth power -- the clamp is only on the low side.
    { "long-axis", { 10.0f, 0.0f, 0.0f, 0.0f },
      { 2, 0, 0, 0 }, { 0, 1, 0, 0 }, { 0, 0, 1, 0 }, { 0, 0, 0, 1 },
      1.0f, 1.0f, 1.0f, 0.0f, 0.2f, 0.5f, 0.75f, 1 },
};

static void s_resolve(void)
{
    int k;

    printf("[resolve]\n");
    for (k = 0; k < (int)(sizeof kCases / sizeof kCases[0]); k++) {
        const Case *c = &kCases[k];
        RigidBody rb;
        AeroInfo ai;
        Aerodynamics a;
        float out = 1234.5f;

        memset(&rb, 0, sizeof rb);
        set4(&rb.Velocity, c->vel[0], c->vel[1], c->vel[2], c->vel[3]);
        set4(&rb.State.R.v0, c->r0[0], c->r0[1], c->r0[2], c->r0[3]);
        set4(&rb.State.R.v1, c->r1[0], c->r1[1], c->r1[2], c->r1[3]);
        set4(&rb.State.R.v2, c->r2[0], c->r2[1], c->r2[2], c->r2[3]);
        set4(&rb.State.R.v3, c->r3[0], c->r3[1], c->r3[2], c->r3[3]);
        set4(&rb.ForceAccumulator, 1.0f, 2.0f, 3.0f, 4.0f);
        set4(&rb.MomentAccumulator, -1.0f, -2.0f, -3.0f, -4.0f);

        ai.Drag = c->drag;
        ai.FrontDownforce = c->front;
        ai.RearDownforce = c->rear;
        ai.AutoBalanceDownforce = 99.0f;

        aerodynamics_init(&a, &rb, &ai);
        a.Boost = c->boost;
        a.Draft = c->draft;
        a.Throttle = c->throttle;
        a.GroundEffect = c->ge;

        printf("case %s\n", c->name);
        aerodynamics_resolve_forces(&a, c->with_out ? &out : NULL);
        pv("  FA", &rb.ForceAccumulator);
        pv("  MA", &rb.MomentAccumulator);
        printf("  out %.9g\n", out);
        dump_aero("  after", &a, &ai, &rb);
    }
}

// --------------------------------------------------- off-throttle tuning

// The two .sdata floats are writable, and ResolveForces reads them every
// call rather than folding them in.
static void s_tuning(void)
{
    RigidBody rb;
    AeroInfo ai = { 0.5f, 1.0f, 1.0f, 0.0f };
    Aerodynamics a;
    float out;
    float f0 = OffThrottleDragFactor, h0 = OffThrottleDragCenterHeight;

    printf("[tuning]\n");
    memset(&rb, 0, sizeof rb);
    set4(&rb.Velocity, 10.0f, 0.0f, 0.0f, 0.0f);
    set4(&rb.State.R.v0, 1, 0, 0, 0);
    set4(&rb.State.R.v1, 0, 1, 0, 0);
    set4(&rb.State.R.v2, 0, 0, 1, 0);
    set4(&rb.State.R.v3, 0, 0, 0, 1);
    aerodynamics_init(&a, &rb, &ai);
    a.Throttle = 0.25f;
    a.GroundEffect = 1.0f;

    OffThrottleDragFactor = 3.5f;
    OffThrottleDragCenterHeight = -0.75f;
    aerodynamics_resolve_forces(&a, &out);
    pv("  FA", &rb.ForceAccumulator);
    pv("  MA", &rb.MomentAccumulator);
    printf("  out %.9g\n", out);

    OffThrottleDragFactor = f0;
    OffThrottleDragCenterHeight = h0;
}

// ----------------------------------------------------- at speed / snapshot

static void s_at_speed(void)
{
    static const float speeds[] = { -5.0f, -0.0f, 0.0f, 3.5f, 100.0f,
                                    0.1f };
    AeroInfo ai = { 0.3f, 1.75f, 2.125f, 0.0f };
    Aerodynamics a;
    RigidBody rb;
    int k;

    printf("[at-speed]\n");
    aerodynamics_init(&a, &rb, &ai);
    for (k = 0; k < (int)(sizeof speeds / sizeof speeds[0]); k++)
        printf("  %.9g -> %.9g\n", speeds[k],
               aerodynamics_get_downforce_at_speed(&a, speeds[k]));
}

static int32_t snap_reset(const void *snap)
{
    const uint8_t *b = (const uint8_t *)snap;
    return (b[56] | b[57]) != 0;
}

static void s_snapshot(void)
{
    static const uint8_t pairs[4][2] = { { 0, 0 }, { 1, 0 }, { 0, 2 },
                                         { 128, 64 } };
    uint8_t snap[64];
    Aerodynamics a;
    AeroInfo ai = { 0.0f, 0.0f, 0.0f, 0.0f };
    RigidBody rb;
    int k;

    printf("[snapshot]\n");
    for (k = -1; k < 4; k++) {
        memset(snap, 0, sizeof snap);
        if (k >= 0) {
            snap[56] = pairs[k][0];
            snap[57] = pairs[k][1];
        }
        gReplayShouldResetFn = k >= 0 ? snap_reset : NULL;
        aerodynamics_init(&a, &rb, &ai);
        a.Boost = 1.25f;
        a.Draft = 0.5f;
        a.Throttle = 0.75f;
        a.GroundEffect = 0.625f;
        aerodynamics_do_snapshot(&a, snap);
        dump_aero(k >= 0 ? "  seam" : "  null", &a, &ai, &rb);
    }
    gReplayShouldResetFn = NULL;
}

int main(void)
{
    s_layout();
    s_static();
    s_init();
    s_resolve();
    s_tuning();
    s_at_speed();
    s_snapshot();
    return 0;
}
