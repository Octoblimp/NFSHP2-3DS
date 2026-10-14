// Harness for tools/envsample_check.py: runs the checker's script on
// eenvmap.c's sample table and ComputeReflectionST, and prints what the
// model prints for the retail image. See the checker's docstring.
//
//     envsample_test script.txt > out.txt

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "cammover.h"
#include "camera.h"
#include "eenvmap.h"
#include "emath.h"
#include "eview.h"
#include "eviewmatrix.h"
#include "player.h"
#include "realtime.h"
#include "trackflow.h"
#include "world.h"

// --------------------------------------------- what eenvmap.c reaches for
//
// The script never calls the cameras' half of eenvmap.c; these only let
// it link, and each says so if it is reached.

static void unreached(const char *name)
{
    printf("UNREACHED %s\n", name);
}

bMatrix4          hack_man_matrix;
uint32_t          eFrameCounter;
float             RealTimeElapsed;
int               CameraStopUpdating;
BGameFlow        *gTrackFlowGameFlow;
World            *pCurrentWorld;
struct Player    *PlayerPlayersByIndex[2];
struct Player    *PlayerPlayersByNumber[2];
int32_t           PlayerNetLocal = -1;

void camera_init(Camera *c)
{
    (void)c;
    unreached("camera_init");
}

void camera_set_matrix(Camera *c, const bMatrix4 *m, float elapsed)
{
    (void)c, (void)m, (void)elapsed;
    unreached("camera_set_matrix");
}

eView *eGetView(int32_t id)
{
    (void)id;
    unreached("eGetView");
    return NULL;
}

eRenderTarget *eGetRenderTarget(int32_t id)
{
    (void)id;
    unreached("eGetRenderTarget");
    return NULL;
}

int32_t eGetCurrentViewMode(void)
{
    unreached("eGetCurrentViewMode");
    return 0;
}

void eMulMatrix(bMatrix4 *o, const bMatrix4 *m1, const bMatrix4 *m2)
{
    (void)o, (void)m1, (void)m2;
    unreached("eMulMatrix");
}

void eMulVector3(bVector3 *o, const bMatrix4 *m, const bVector3 *v)
{
    (void)o, (void)m, (void)v;
    unreached("eMulVector3");
}

void eTransposeMatrix(bMatrix4 *o, const bMatrix4 *m)
{
    (void)o, (void)m;
    unreached("eTransposeMatrix");
}

void eCreateLookAtMatrix(bMatrix4 *m, const bVector3 *eye,
                         const bVector3 *target, const bVector3 *up)
{
    (void)m, (void)eye, (void)target, (void)up;
    unreached("eCreateLookAtMatrix");
}

// ---------------------------------------------------------------- the dump

static uint32_t bits(float f)
{
    uint32_t u;

    memcpy(&u, &f, 4);
    return u;
}

static float from_bits(uint32_t u)
{
    float f;

    memcpy(&f, &u, 4);
    return f;
}

// The table as 4 * 7 words a sample, the model's order.
static void dump_table(void)
{
    const uint32_t *w = (const uint32_t *)EnvMapRefSampleTable;
    size_t          n = sizeof EnvMapRefSampleTable / 4, i;

    for (i = 0; i < n; i += 7) {
        size_t s = i / 7;

        printf("T %zu %zu %zu %08x %08x %08x %08x %08x %08x %08x\n",
               s / 49, s / 7 % 7, s % 7, w[i], w[i + 1], w[i + 2],
               w[i + 3], w[i + 4], w[i + 5], w[i + 6]);
    }
}

int main(int argc, char **argv)
{
    FILE *f;
    char  line[256];

    if (argc != 2 || (f = fopen(argv[1], "r")) == NULL) {
        fprintf(stderr, "usage: envsample_test script.txt\n");
        return 2;
    }
    // The table and the vector start as the model's do: filled.
    memset(EnvMapRefSampleTable, 0xa5, sizeof EnvMapRefSampleTable);
    while (fgets(line, sizeof line, f)) {
        unsigned x, y, z, w, p;

        if (line[0] == 'T') {
            create_ref_sample_table();
            dump_table();
        } else if (line[0] == 'F' && sscanf(line + 1, "%x", &p) == 1) {
            memset(EnvMapRefSampleTable, (int)(p & 0xff),
                   sizeof EnvMapRefSampleTable);
            printf("F %02x\n", p & 0xff);
        } else if (line[0] == 'S'
                   && sscanf(line + 1, "%x %x %x %x", &x, &y, &z, &w) == 4) {
            bVector3 d;
            bVector2 st;

            d.x   = from_bits(x);
            d.y   = from_bits(y);
            d.z   = from_bits(z);
            d.pad = from_bits(w);
            st.x  = from_bits(0xa5a5a5a5u);
            st.y  = from_bits(0xa5a5a5a5u);
            compute_reflection_st(&d, &st);
            printf("S %08x %08x %08x %08x -> %08x %08x %08x %08x %08x %08x\n",
                   x, y, z, w, bits(d.x), bits(d.y), bits(d.z), bits(d.pad),
                   bits(st.x), bits(st.y));
        }
    }
    fclose(f);
    return 0;
}
