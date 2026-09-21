// Transcript harness for Steering and TwoWheelAckermanSteering.
// Cross-checked by tools/steering_check.py, which models the same
// behaviour from the disassembly without reading this file.

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "steering.h"
#include "bmath.h"

static unsigned fbits(float f)
{
    unsigned u;
    memcpy(&u, &f, 4);
    return u;
}

// ------------------------------------------------------------- the layout

static void scenario_layout(void)
{
    printf("[layout]\n");
    printf("sizeof_host Steering %zu\n", sizeof(Steering));
    printf("sizeof_host Ackerman %zu\n", sizeof(TwoWheelAckermanSteering));
    printf("slack %zu\n", STEERING_SLACK);

#define OFF(t, f) printf("off %-28s %zu\n", #t "." #f, offsetof(t, f))
    OFF(Steering, CTI);
    OFF(Steering, SteeringMatrix);
    OFF(Steering, _vtable);
    OFF(TwoWheelAckermanSteering, base);
    OFF(TwoWheelAckermanSteering, AckermanMatrix);
#undef OFF

    // The extent, because offsets alone do not pin it: a one-element
    // array with 64 bytes of padding behind it leaves every following
    // offset and the total size exactly where they were.
    printf("arr AckermanMatrix %zu\n",
           sizeof(((TwoWheelAckermanSteering *)0)->AckermanMatrix));
    printf("stride AckermanMatrix %zu\n",
           (size_t)((char *)&((TwoWheelAckermanSteering *)0)->AckermanMatrix[1]
                    - (char *)&((TwoWheelAckermanSteering *)0)->AckermanMatrix[0]));
    printf("sizeof bMatrix4 %zu\n", sizeof(bMatrix4));
    printf("sizeof bVector4 %zu\n", sizeof(bVector4));

    // The four pool entries, as bits. Two of them are the object's own
    // trigonometry constants rather than the library's, and printing the
    // library value beside each one is the whole point: if a future edit
    // "tidies" the header to M_PI these lines stop matching.
    printf("const bam2rad %08x\n", fbits(STEERING_BAM_TO_RADIANS));
    printf("const pi      %08x\n", fbits(STEERING_IMAGE_PI));
    printf("const twopi   %08x\n", fbits(STEERING_IMAGE_TWO_PI));
    printf("const halfpi  %08x\n", fbits(STEERING_IMAGE_HALF_PI));
    printf("true  pi      %08x\n", fbits((float)3.14159265358979323846));
    printf("true  twopi   %08x\n", fbits((float)6.28318530717958647692));
    printf("true  halfpi  %08x\n", fbits((float)1.57079632679489661923));

    printf("vtable Steering %08x\n", (unsigned)STEERING_VTABLE);
    printf("vtable Ackerman %08x\n", (unsigned)ACKERMAN_VTABLE);
}

// ------------------------------------------------- construction, teardown

// A CarTypeInfo big enough to hold the four wheels SetSteering reads.
// Calloc'd rather than declared, so every field the object does not touch
// is a known zero.
static CarTypeInfo *make_cti(const float *x, const float *y)
{
    CarTypeInfo *ct = calloc(1, sizeof(CarTypeInfo));
    int i;
    for (i = 0; i < 4; i++) {
        ct->Wheels[i].PositionX = x[i];
        ct->Wheels[i].PositionY = y[i];
        ct->Wheels[i].PositionZ = -1.0f - (float)i;   // never read
        ct->Wheels[i].Radius = 0.3f + 0.01f * (float)i;
        ct->Wheels[i].WheelNumber = i;
    }
    return ct;
}

// Fill the two matrices with distinct non-zero floats, so that anything
// bIdentity is meant to zero and does not shows up as a leftover.
static void scribble_matrices(TwoWheelAckermanSteering *a)
{
    int i, j;
    for (i = 0; i < ACKERMAN_MATRICES; i++) {
        float *p = (float *)&a->AckermanMatrix[i];
        for (j = 0; j < 16; j++)
            p[j] = 1000.0f * (float)(i + 1) + (float)j + 0.5f;
    }
}

static void print_matrix(const char *tag, const bMatrix4 *m)
{
    const float *p = (const float *)m;
    int j;
    for (j = 0; j < 16; j++)
        printf("%s[%2d] %.9g\n", tag, j, p[j]);
}

static void scenario_init(void)
{
    static const float gx[4] = { 1.40f, 1.35f, -1.30f, -1.25f };
    static const float gy[4] = { 0.75f, -0.75f, 0.80f, -0.70f };
    CarTypeInfo *ct = make_cti(gx, gy);
    bMatrix4 *sentinel = (bMatrix4 *)(void *)ct;   // any address will do
    Steering s;
    int k;

    printf("[init]\n");

    // Two runs with different starting contents, because the claim is
    // that the constructor leaves SteeringMatrix exactly as it found it.
    for (k = 0; k < 2; k++) {
        memset(&s, (k == 0) ? 0x5A : 0xA5, sizeof s);
        s.SteeringMatrix = k ? sentinel : NULL;
        steering_init(&s, ct);
        printf("run %d cti %d\n", k, s.CTI == ct);
        printf("run %d vtable %08x\n", k, s._vtable);
        printf("run %d matrix kept %d\n", k,
               s.SteeringMatrix == (k ? sentinel : NULL));
    }

    // The destructor rewrites the same word and touches nothing else.
    s.CTI = NULL;
    s._vtable = 0xDEADBEEFu;
    s.SteeringMatrix = sentinel;
    steering_fini(&s);
    printf("fini vtable %08x\n", s._vtable);
    printf("fini cti null %d\n", s.CTI == NULL);
    printf("fini matrix kept %d\n", s.SteeringMatrix == sentinel);

    free(ct);
}

static void scenario_ackerman_init(void)
{
    static const float gx[4] = { 0.90f, 0.95f, -2.05f, -2.10f };
    static const float gy[4] = { 1.10f, -1.10f, 1.05f, -1.15f };
    CarTypeInfo *ct = make_cti(gx, gy);
    TwoWheelAckermanSteering *a =
        calloc(1, sizeof(TwoWheelAckermanSteering));
    TwoWheelAckermanSteering *r;
    int i;

    printf("[ackerman-init]\n");

    a->base.CTI = NULL;
    a->base._vtable = 0x11111111u;
    a->base.SteeringMatrix = NULL;
    scribble_matrices(a);

    r = ackerman_init(a, ct);
    printf("returns this %d\n", r == a);
    printf("cti %d\n", a->base.CTI == ct);
    printf("vtable %08x\n", a->base._vtable);

    // The one store that ties the two classes together.
    printf("matrix delta %td\n",
           (ptrdiff_t)((char *)a->base.SteeringMatrix
                       - (char *)&a->AckermanMatrix[0]));

    // And the matrices themselves are untouched -- the loop the compiler
    // emitted has an empty body, so a freshly built object's matrices
    // hold whatever the allocation left there.
    for (i = 0; i < ACKERMAN_MATRICES; i++) {
        char tag[16];
        sprintf(tag, "m%d", i);
        print_matrix(tag, &a->AckermanMatrix[i]);
    }

    // ComputeAuxiliaries is `jr ra ; nop`. Prove it by calling it on a
    // fully populated object and showing every word unchanged.
    {
        unsigned char before[sizeof(TwoWheelAckermanSteering)];
        memcpy(before, a, sizeof before);
        ackerman_compute_auxiliaries(a);
        printf("aux unchanged %d\n", memcmp(before, a, sizeof before) == 0);
    }

    // The destructor writes its own vtable and then lets ~Steering write
    // the base's over the top, so what survives is Steering's.
    ackerman_fini(a);
    printf("fini vtable %08x\n", a->base._vtable);
    printf("fini cti %d\n", a->base.CTI == ct);
    printf("fini matrix delta %td\n",
           (ptrdiff_t)((char *)a->base.SteeringMatrix
                       - (char *)&a->AckermanMatrix[0]));

    free(a);
    free(ct);
}

// -------------------------------------------------------------- GetMatrix

static void scenario_get_matrix(void)
{
    static const float gx[4] = { 1.40f, 1.35f, -1.30f, -1.25f };
    static const float gy[4] = { 0.75f, -0.75f, 0.80f, -0.70f };
    CarTypeInfo *ct = make_cti(gx, gy);
    TwoWheelAckermanSteering *a =
        calloc(1, sizeof(TwoWheelAckermanSteering));
    static const int idx[6] = { -1, 0, 1, 2, 3, 7 };
    int i;

    printf("[get-matrix]\n");
    ackerman_init(a, ct);

    // `sll a1,a1,6` and nothing else: the index is scaled by 64 with no
    // bounds check, so indices past the end are addresses past the end.
    // Printed as a delta from the array base rather than an address.
    for (i = 0; i < 6; i++) {
        bMatrix4 *m = steering_get_matrix(&a->base, idx[i]);
        printf("get %2d delta %td\n", idx[i],
               (ptrdiff_t)((char *)m - (char *)&a->AckermanMatrix[0]));
    }

    free(a);
    free(ct);
}

// ------------------------------------------------------------ SetSteering

struct geom {
    const char *name;
    float x[4];
    float y[4];
};

static const struct geom GEOMS[3] = {
    { "sedan",    { 1.40f, 1.35f, -1.30f, -1.25f },
                  { 0.75f, -0.75f, 0.80f, -0.70f } },
    { "wide",     { 0.90f, 0.95f, -2.05f, -2.10f },
                  { 1.10f, -1.10f, 1.05f, -1.15f } },
    { "negtrack", { 1.25f, 1.20f, -1.30f, -1.35f },
                  { -0.80f, 0.80f, -0.85f, 0.75f } },
};

static const unsigned BAMS[8] = {
    0x0000u, 0x0001u, 0x2000u, 0x7fffu, 0x8000u, 0x8001u, 0xc000u, 0xffffu
};

static void scenario_set_steering(void)
{
    int g, b, i;

    printf("[set-steering]\n");

    for (g = 0; g < 3; g++) {
        CarTypeInfo *ct = make_cti(GEOMS[g].x, GEOMS[g].y);
        TwoWheelAckermanSteering *a =
            calloc(1, sizeof(TwoWheelAckermanSteering));
        ackerman_init(a, ct);

        for (b = 0; b < 8; b++) {
            printf("case %s %04x\n", GEOMS[g].name, BAMS[b]);
            // Scribbled first, so a bIdentity that misses a word shows.
            scribble_matrices(a);
            ackerman_set_steering(a, (uint16_t)BAMS[b]);
            for (i = 0; i < ACKERMAN_MATRICES; i++) {
                char tag[16];
                sprintf(tag, "m%d", i);
                print_matrix(tag, &a->AckermanMatrix[i]);
            }
        }

        free(a);
        free(ct);
    }
}

int main(void)
{
    scenario_layout();
    scenario_init();
    scenario_ackerman_init();
    scenario_get_matrix();
    scenario_set_steering();
    return 0;
}
