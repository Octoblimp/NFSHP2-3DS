// Harness for tools/emodelanim_check.py: runs the checker's script on
// emodelanim.c's Render setup (SetupRigidAnimation, SetupVertexAnimation,
// eRigidAnimation::GetMatrixAtTime), and prints what the model prints for
// the retail image. See the checker's docstring.
//
//     emodelanim_test script.txt > out.txt

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bmatrix.h"
#include "eframe.h"
#include "emodel.h"
#include "esolid.h"
#include "realtime.h"

// ------------------------------------- what emodelanim.c reaches for

int32_t   WorldTimeFrames;

uint32_t  FrameMemoryBufferSize;
uint8_t  *CurrentBufferPos;
uint8_t  *CurrentBufferEnd;
int32_t   PrintFrameMalloc;
int32_t   FrameMallocAllocNum;
int32_t   FrameMallocFailed;
uint32_t  FrameMallocFailAmount;
uint32_t  FrameMallocMaxFailAmount;
uint8_t  *FrameMemoryBuffer[2];
int32_t   FrameMemoryBufferAmountUsed[2];

// ------------------------------------------------------------ the objects

#define MAX_ANIMS   8
#define MAX_FRAMES  200
#define MAX_SOLIDS  64
#define MAX_VAS     4
#define MAX_MODELS  16
#define FRAME_BYTES 4096

typedef struct Anim {
    eRigidAnimation a;
    uint8_t         more[64 * MAX_FRAMES];  // the frames past Matricies
} Anim;

static Anim             s_anim[MAX_ANIMS];
static eSolid           s_solid[MAX_SOLIDS];
static eVertexAnimator  s_va[MAX_VAS];
static eModel           s_model[MAX_MODELS];
static bMatrix4         s_in[MAX_MODELS];
static uint8_t          s_frame[FRAME_BYTES] __attribute__((aligned(16)));

static int solid_index(const void *s)
{
    int i;

    if (s == NULL)
        return -1;
    for (i = 0; i < MAX_SOLIDS; i++)
        if ((const void *)&s_solid[i] == s)
            return i;
    return -2;
}

static void put_words(void *dst, char **t, int n)
{
    uint32_t w[16];
    int      i;

    for (i = 0; i < n; i++)
        w[i] = (uint32_t)strtoul(t[i], NULL, 16);
    memcpy(dst, w, (size_t)n * 4);
}

static void print_words(const void *src)
{
    uint32_t w[16];
    int      i;

    memcpy(w, src, sizeof w);
    for (i = 0; i < 16; i++)
        printf(" %08x", (unsigned)w[i]);
}

static void print_state(int m)
{
    printf(" solid=%d start=%04x pos=%d fail=%d amt=%u",
           solid_index(s_model[m].Solid),
           (unsigned)(uint16_t)s_model[m].RigidAnimationStartTime,
           (int)(CurrentBufferPos - s_frame), (int)FrameMallocFailed,
           (unsigned)FrameMallocFailAmount);
}

static void render(int m)
{
    bMatrix4 *out;

    printf("R %d:", m);
    if (s_model[m].Solid == NULL) {
        printf(" none\n");
        return;
    }
    out = emodel_setup_animation(&s_model[m], &s_in[m]);
    if (out == &s_in[m])
        printf(" mtx=in");
    else if ((uint8_t *)out >= s_frame && (uint8_t *)out < s_frame + FRAME_BYTES)
        printf(" mtx=f+%d", (int)((uint8_t *)out - s_frame));
    else
        printf(" mtx=?");
    print_words(out);
    print_state(m);
    printf("\n");
}

int main(int argc, char **argv)
{
    static char line[8192];
    char       *t[80];
    FILE       *f;

    if (argc < 2 || (f = fopen(argv[1], "r")) == NULL) {
        fprintf(stderr, "usage: emodelanim_test script.txt\n");
        return 2;
    }
    CurrentBufferPos = s_frame;
    CurrentBufferEnd = s_frame + FRAME_BYTES;
    while (fgets(line, sizeof line, f)) {
        int   n = 0;
        char *p = strtok(line, " \r\n");

        while (p != NULL && n < 80) {
            t[n++] = p;
            p = strtok(NULL, " \r\n");
        }
        if (n == 0)
            continue;
        switch (t[0][0]) {
        case 'A': {             // A a frames scale trig
            eRigidAnimation *a = &s_anim[atoi(t[1])].a;

            a->NumFrames = (uint16_t)atoi(t[2]);
            a->FrameRateScale = (uint8_t)atoi(t[3]);
            a->TriggerableFlag = (uint8_t)atoi(t[4]);
            break;
        }
        case 'M':               // M a frame w0..w15
            put_words(s_anim[atoi(t[1])].a.Matricies + atoi(t[2]) * 64,
                      &t[3], 16);
            break;
        case 'L': {             // L s a
            int a = atoi(t[2]);

            s_solid[atoi(t[1])].pRigidAnimation =
                a < 0 ? NULL : (uint8_t *)&s_anim[a].a;
            break;
        }
        case 'V': {             // V v rate s0 s1 ...
            eVertexAnimator *va = &s_va[atoi(t[1])];
            int              i;

            va->FrameRate = atoi(t[2]);
            va->NumSolids = n - 3;
            for (i = 3; i < n; i++) {
                va->SolidTable[i - 3] = &s_solid[atoi(t[i])];
                s_solid[atoi(t[i])].pVertexAnimator = va;
            }
            break;
        }
        case 'O': {             // O m s
            int s = atoi(t[2]);

            s_model[atoi(t[1])].Solid = s < 0 ? NULL : &s_solid[s];
            break;
        }
        case 'X':               // X m w0..w15
            put_words(&s_in[atoi(t[1])], &t[2], 16);
            break;
        case 'W':               // W t
            WorldTimeFrames = (int32_t)strtol(t[1], NULL, 0);
            break;
        case 'S':               // S m start
            s_model[atoi(t[1])].RigidAnimationStartTime =
                (int16_t)(uint16_t)strtoul(t[2], NULL, 16);
            break;
        case 'B':               // B pos end
            CurrentBufferPos = s_frame + atoi(t[1]);
            CurrentBufferEnd = s_frame + atoi(t[2]);
            FrameMallocFailed = 0;
            FrameMallocFailAmount = 0;
            break;
        case 'R':
            render(atoi(t[1]));
            break;
        case 'G': {             // G a t
            bMatrix4 out;

            erigidanimation_get_matrix_at_time(&s_anim[atoi(t[1])].a, &out,
                                               atoi(t[2]));
            printf("G %s %s:", t[1], t[2]);
            print_words(&out);
            printf("\n");
            break;
        }
        default:
            printf("BAD %s\n", t[0]);
            break;
        }
    }
    fclose(f);
    return 0;
}
