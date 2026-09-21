// Host harness for 3DS Files/source/emath.c. Prints a transcript that
// tools/emath_check.py diffs line by line against an independent model.
//
// Everything printed is a float32 rendered with %.9g, which round-trips, so
// a single-ulp disagreement shows up as a changed line rather than being
// absorbed by a tolerance. The one function that cannot be bit-exact against
// the hardware -- anything through VRSQRT -- is still bit-exact between this
// and the model, because both do the same IEEE divide and square root.
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "emath.h"
#include "bmath.h"

// ------------------------------------------------------------------- output

static void pv3(const char *tag, const bVector3 *v)
{
    printf("  %s %.9g %.9g %.9g\n", tag, v->x, v->y, v->z);
}

static void pv4(const char *tag, const bVector4 *v)
{
    printf("  %s %.9g %.9g %.9g %.9g\n", tag, v->x, v->y, v->z, v->w);
}

static void pmat(const bMatrix4 *m)
{
    printf("    %.9g %.9g %.9g %.9g\n", m->v0.x, m->v0.y, m->v0.z, m->v0.w);
    printf("    %.9g %.9g %.9g %.9g\n", m->v1.x, m->v1.y, m->v1.z, m->v1.w);
    printf("    %.9g %.9g %.9g %.9g\n", m->v2.x, m->v2.y, m->v2.z, m->v2.w);
    printf("    %.9g %.9g %.9g %.9g\n", m->v3.x, m->v3.y, m->v3.z, m->v3.w);
}

// ------------------------------------------------------------------ the rng
//
// A plain LCG so the two implementations can walk the same matrices. The
// float is built out of 24 integer bits and a power-of-two scale, so every
// step is exact in float32 and the model can reproduce it without caring how
// its host rounds.

static uint32_t rngState;

static void rseed(uint32_t s)
{
    rngState = s;
}

static float frand(float scale)
{
    float u;

    rngState = rngState * 1103515245u + 12345u;
    u = (float)(int32_t)(rngState >> 8) * (1.0f / 8388608.0f) - 1.0f;
    return u * scale;
}

static void rmat(bMatrix4 *m, float scale)
{
    float *p = &m->v0.x;
    int i;

    for (i = 0; i < 16; i++) p[i] = frand(scale);
}

static void rvec3(bVector3 *v, float scale)
{
    v->x = frand(scale);
    v->y = frand(scale);
    v->z = frand(scale);
    v->pad = 0.0f;
}

// ---------------------------------------------------------------- scenarios

// The BAMs worth testing: both ends, the quadrant boundaries, one either
// side of each, and a coarse sweep. eSin's folds happen at pi and pi/2, and
// a BAM of 16384 lands exactly on one of them.
static const uint16_t BAMS[] = {
    0, 1, 2, 100, 8191, 8192, 8193, 16383, 16384, 16385,
    24575, 24576, 24577, 32767, 32768, 32769, 40960, 49151, 49152, 49153,
    57344, 60000, 65534, 65535,
    4096, 12288, 20480, 28672, 36864, 45056, 53248, 61440,
};
#define NBAMS ((int)(sizeof BAMS / sizeof BAMS[0]))

static void scenario_sin(void)
{
    // The interesting radians: the reduction boundaries themselves, values
    // just outside them, negatives (which spin the add loop), and a value
    // large enough to prove the loop is a loop and not a modulo.
    static const float xs[] = {
        0.0f, 1e-8f, 0.5f, 1.0f, 1.5707963f, 1.5707964f, 2.0f, 3.1415926f,
        3.1415927f, 3.1415928f, 4.0f, 6.2831852f, 6.2831855f, 6.2831858f,
        7.0f, 12.566371f, 100.0f, -0.5f, -3.0f, -6.2831855f, -20.0f,
    };
    int i;

    printf("scenario sin\n");
    for (i = 0; i < (int)(sizeof xs / sizeof xs[0]); i++)
        printf("  sin %.9g -> %.9g\n", xs[i], eSin(xs[i]));
    for (i = 0; i < NBAMS; i++) {
        float r = (float)(int)BAMS[i] * 0x1.921fb6p-14f;
        printf("  bam %5u rad %.9g -> %.9g\n", BAMS[i], r, eSin(r));
    }
}

static void scenario_basics(void)
{
    bMatrix4 a, b, o;
    bVector3 v3;
    bVector4 v4;

    printf("scenario basics\n");
    eMathInit();
    printf("  identity\n");
    pmat(&eMathIdentityMatrix);
    printf("  zero\n");
    pmat(&eMathZeroMatrix);

    eIdentity(&o);
    printf("  eIdentity\n");
    pmat(&o);
    eZeroMatrix(&o);
    printf("  eZeroMatrix\n");
    pmat(&o);

    rseed(0x1234567u);
    rmat(&a, 4.0f);
    rmat(&b, 4.0f);
    printf("  a\n");
    pmat(&a);
    printf("  b\n");
    pmat(&b);
    eMulMatrix(&o, &a, &b);
    printf("  a*b\n");
    pmat(&o);
    eMulMatrix(&o, &b, &a);
    printf("  b*a\n");
    pmat(&o);

    // Aliasing: the original loads all eight quadwords before storing, so
    // these must come out the same as the two above.
    o = a;
    eMulMatrix(&o, &o, &b);
    printf("  a*b aliased dst=src1\n");
    pmat(&o);
    o = b;
    eMulMatrix(&o, &a, &o);
    printf("  a*b aliased dst=src2\n");
    pmat(&o);

    eTransposeMatrix(&o, &a);
    printf("  transpose a\n");
    pmat(&o);

    rvec3(&v3, 3.0f);
    pv3("v3", &v3);
    eMulVector3(&v3, &a, &v3);
    pv3("v3*a", &v3);
    v4.x = frand(3.0f); v4.y = frand(3.0f);
    v4.z = frand(3.0f); v4.w = frand(3.0f);
    pv4("v4", &v4);
    eMulVector4(&v4, &a, &v4);
    pv4("v4*a", &v4);
}

static void scenario_rotate(void)
{
    bMatrix4 base, o;
    int i;

    printf("scenario rotate\n");
    rseed(0x2468aceu);
    rmat(&base, 2.0f);
    printf("  base\n");
    pmat(&base);
    for (i = 0; i < NBAMS; i++) {
        bMatrix4 id;

        eIdentity(&id);
        eRotateX(&o, &id, BAMS[i]);
        printf("  rotX %5u of identity\n", BAMS[i]);
        pmat(&o);
        eRotateY(&o, &id, BAMS[i]);
        printf("  rotY %5u of identity\n", BAMS[i]);
        pmat(&o);
        eRotateZ(&o, &id, BAMS[i]);
        printf("  rotZ %5u of identity\n", BAMS[i]);
        pmat(&o);
        eRotateX(&o, &base, BAMS[i]);
        printf("  rotX %5u of base\n", BAMS[i]);
        pmat(&o);
        eRotateZ(&o, &base, BAMS[i]);
        printf("  rotZ %5u of base\n", BAMS[i]);
        pmat(&o);
    }
}

static void scenario_translate(void)
{
    bMatrix4 base, o;
    bVector3 v;
    int i;

    printf("scenario translate\n");
    rseed(0x13572468u);
    rmat(&base, 2.0f);
    for (i = 0; i < 6; i++) {
        rvec3(&v, 50.0f);
        pv3("v", &v);
        eCreateTranslationMatrix(&o, &v);
        printf("  createTranslation\n");
        pmat(&o);
        eTranslate(&o, &base, &v);
        printf("  translate base\n");
        pmat(&o);
    }
}

static void scenario_axis(void)
{
    // Unit axes and a few normalised oblique ones: the function does not
    // normalise, so feeding it something else would test nothing useful.
    static const bVector3 axes[] = {
        { 1.0f, 0.0f, 0.0f, 0.0f },
        { 0.0f, 1.0f, 0.0f, 0.0f },
        { 0.0f, 0.0f, 1.0f, 0.0f },
        { 0.57735026f, 0.57735026f, 0.57735026f, 0.0f },
        { -0.70710678f, 0.70710678f, 0.0f, 0.0f },
        { 0.26726124f, 0.53452247f, 0.80178374f, 0.0f },
    };
    bMatrix4 o;
    int i, j;

    printf("scenario axis\n");
    for (i = 0; i < (int)(sizeof axes / sizeof axes[0]); i++)
        for (j = 0; j < NBAMS; j += 3) {
            eCreateAxisRotationMatrix(&o, &axes[i], BAMS[j]);
            printf("  axis %d bam %5u\n", i, BAMS[j]);
            pmat(&o);
        }
}

static void scenario_lookat(void)
{
    bMatrix4 o;
    bVector3 eye, target, up;
    int i;

    printf("scenario lookat\n");
    rseed(0xfeedfaceu);
    for (i = 0; i < 12; i++) {
        rvec3(&eye, 100.0f);
        rvec3(&target, 100.0f);
        rvec3(&up, 1.0f);
        pv3("eye", &eye);
        pv3("target", &target);
        pv3("up", &up);
        eCreateLookAtMatrix(&o, &eye, &target, &up);
        pmat(&o);
    }
    // The canonical one: looking down -Z from the origin with Z up, which is
    // what the engine's own defaults amount to.
    eye.x = 0.0f; eye.y = 0.0f; eye.z = 10.0f; eye.pad = 0.0f;
    target.x = 0.0f; target.y = 0.0f; target.z = 0.0f; target.pad = 0.0f;
    up.x = 0.0f; up.y = 1.0f; up.z = 0.0f; up.pad = 0.0f;
    eCreateLookAtMatrix(&o, &eye, &target, &up);
    printf("  canonical\n");
    pmat(&o);
}

static void scenario_invert(void)
{
    bMatrix4 base, rot, o;
    bVector3 axis;
    int i;

    printf("scenario invert\n");
    rseed(0x0badf00du);
    for (i = 0; i < 8; i++) {
        rvec3(&axis, 1.0f);
        rmat(&base, 3.0f);
        eInvertTransformationMatrix(&o, &base);
        printf("  invertTransform\n");
        pmat(&o);
        eInvertRotationMatrix(&o, &base);
        printf("  invertRotation\n");
        pmat(&o);
        eOrthonormalizeMatrix(&o, &base);
        printf("  orthonormalize\n");
        pmat(&o);
        // And once on something that is already a rotation, where the answer
        // is checkable by eye.
        eIdentity(&rot);
        eRotateZ(&rot, &rot, (uint16_t)(i * 8192));
        eRotateX(&rot, &rot, (uint16_t)(i * 4096));
        eInvertTransformationMatrix(&o, &rot);
        printf("  invertTransform of rotation\n");
        pmat(&o);
        eOrthonormalizeMatrix(&o, &rot);
        printf("  orthonormalize of rotation\n");
        pmat(&o);
    }
}

static void scenario_vectors(void)
{
    bMatrix4 m, o;
    bVector4 a, b, r;
    bVector3 v;
    int i;

    printf("scenario vectors\n");
    rseed(0xc0ffeeu);
    for (i = 0; i < 10; i++) {
        a.x = frand(50.0f); a.y = frand(50.0f);
        a.z = frand(50.0f); a.w = frand(1.0f);
        b.x = frand(50.0f); b.y = frand(50.0f);
        b.z = frand(50.0f); b.w = frand(1.0f);
        pv4("from", &a);
        pv4("to", &b);
        eNormalizedDirection(&r, &a, &b);
        pv4("dir", &r);
        eReflectVector(&r, &a, &b);
        pv4("reflect", &r);
    }
    for (i = 0; i < 10; i++) {
        rmat(&m, 2.0f);
        a.x = frand(20.0f); a.y = frand(20.0f);
        a.z = frand(20.0f); a.w = frand(2.0f);
        pv4("v", &a);
        eRotTransPers(&r, &m, &a);
        pv4("pers", &r);
        printf("  clip %02x\n", (unsigned)eGetClipFlags(&a, &m));
    }
    // Clip flags deserve their own sweep: a point walked out past each face
    // in turn, so every one of the six bits is exercised on its own.
    eIdentity(&m);
    for (i = -3; i <= 3; i++) {
        a.x = (float)i; a.y = 0.0f; a.z = 0.0f; a.w = 1.0f;
        printf("  clipx %2d -> %02x\n", i, (unsigned)eGetClipFlags(&a, &m));
        a.x = 0.0f; a.y = (float)i;
        printf("  clipy %2d -> %02x\n", i, (unsigned)eGetClipFlags(&a, &m));
        a.y = 0.0f; a.z = (float)i;
        printf("  clipz %2d -> %02x\n", i, (unsigned)eGetClipFlags(&a, &m));
    }
    for (i = 0; i < 6; i++) {
        rmat(&o, 1.0f);
        rmat(&m, 2.0f);
        rvec3(&v, 3.0f);
        pv3("star v", &v);
        eVectorStarMatrix(&o, &v, &m);
        printf("  star\n");
        pmat(&o);
    }
}

static void scenario_poly(void)
{
    // A convex square, a concave L, and a self-intersecting bowtie, walked
    // over a grid that lands on vertices and edges as well as the interior.
    static const bVector2 square[] = {
        { 0.0f, 0.0f }, { 4.0f, 0.0f }, { 4.0f, 4.0f }, { 0.0f, 4.0f },
    };
    static const bVector2 ell[] = {
        { 0.0f, 0.0f }, { 4.0f, 0.0f }, { 4.0f, 2.0f }, { 2.0f, 2.0f },
        { 2.0f, 4.0f }, { 0.0f, 4.0f },
    };
    static const bVector2 bowtie[] = {
        { 0.0f, 0.0f }, { 4.0f, 4.0f }, { 4.0f, 0.0f }, { 0.0f, 4.0f },
    };
    struct { const char *name; const bVector2 *p; int n; } polys[] = {
        { "square", square, 4 }, { "ell", ell, 6 }, { "bowtie", bowtie, 4 },
    };
    int k, i, j;

    printf("scenario poly\n");
    for (k = 0; k < 3; k++)
        for (j = -2; j <= 12; j++)
            for (i = -2; i <= 12; i++) {
                bVector2 pt;

                pt.x = (float)i * 0.5f;
                pt.y = (float)j * 0.5f;
                printf("  %s %.9g %.9g -> %d\n", polys[k].name, pt.x, pt.y,
                       eIsPointInPoly(&pt, polys[k].p, polys[k].n));
            }
    // Degenerate counts: the loop is `for i < n` with j starting at n-1, so
    // n of 0 and 1 have to be shown rather than assumed.
    {
        bVector2 pt = { 1.0f, 1.0f };

        printf("  square n=0 -> %d\n", eIsPointInPoly(&pt, square, 0));
        printf("  square n=1 -> %d\n", eIsPointInPoly(&pt, square, 1));
        printf("  square n=2 -> %d\n", eIsPointInPoly(&pt, square, 2));
    }
}

int main(void)
{
    scenario_sin();
    scenario_basics();
    scenario_rotate();
    scenario_translate();
    scenario_axis();
    scenario_lookat();
    scenario_invert();
    scenario_vectors();
    scenario_poly();
    return 0;
}
