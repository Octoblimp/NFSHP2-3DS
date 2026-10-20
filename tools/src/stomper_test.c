// Harness for tools/stomper_check.py: runs the checker's script on
// stomper.c and on weatherman.c's query, and prints what the model prints
// for the image. The globals the eggs stomp that live in files the harness
// does not link (carrender.c's, eview.c's) are the harness's, with the
// same first values; the checker's facts hold those files to the image.
// bMalloc and bFree log, and bFree frees nothing, so a label still names
// what it was given. RadialBlurOnOff(bool, int) logs and returns what the
// model's stub does: radialblur_check.py runs the real one.
//
// The host's Stomper is 24 bytes, its pointer 8: the malloc log prints
// that size as the 3DS's 12.
//
//     stomper_test script.txt > out.txt

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bmem.h"
#include "carrenderinfo.h"
#include "eastereggs.h"
#include "eview.h"
#include "radialblur.h"
#include "stomper.h"
#include "weatherman.h"

bMatrix4 CarRenderMatrix = {
    { 1.0f, 0.0f, 0.0f, 0.0f }, { 0.0f, 1.0f, 0.0f, 0.0f },
    { 0.0f, 0.0f, 1.0f, 0.0f }, { 0.0f, 0.0f, 0.0f, 1.0f },
};
int32_t ForceRenderDriver;
int32_t ForceBlackAndWhite;
int32_t EnvPassAlphaA;
int32_t EnvPassAlphaB = 2;
int32_t EnvPassAlphaC = 1;
int32_t EnvPassAlphaD = 1;
int32_t EnvPassAlphaFix = 16;
EasterEggs TheEasterEggs;
int32_t  WorldTimeFrames;
uint32_t eFrameCounter;

static eView views[EVIEW_NUM_VIEWS];

eView *eGetView(int32_t id)
{
    return &views[id];
}

#define NCODES 10
#define NLIST  24
#define NTGT   64
#define NSAVE  128

static EasterEggCode codes[NCODES];
static Stomper      *saved;
static Stomper       obj2;
static StompEntry    list[NLIST];
static uint8_t       tgt[NTGT];
static uint8_t       save[NSAVE];

// The targets, in the dump's order.
#define NTARGETS 30
static void *targets[NTARGETS];

static void init_targets(void)
{
    int i, n = 0;

    for (i = 0; i < 4; i++) {
        bVector4 *v = &(&CarRenderMatrix.v0)[i];

        targets[n++] = &v->x;
        targets[n++] = &v->y;
        targets[n++] = &v->z;
        targets[n++] = &v->w;
    }
    targets[n++] = &OverrideAnimatedDriverLOD;
    targets[n++] = &ForceRenderDriver;
    targets[n++] = &nBoneScale;
    for (i = 0; i < 4; i++)
        targets[n++] = &vBoneScale[i];
    targets[n++] = &ForceBlackAndWhite;
    targets[n++] = &WeatherHeavyFog;
    targets[n++] = &EnvPassAlphaA;
    targets[n++] = &EnvPassAlphaB;
    targets[n++] = &EnvPassAlphaC;
    targets[n++] = &EnvPassAlphaD;
    targets[n++] = &EnvPassAlphaFix;
}

static uint32_t word(const void *p)
{
    uint32_t v;

    memcpy(&v, p, 4);
    return v;
}

static const char *label(const void *p)
{
    if (p == NULL)
        return "null";
    if (p == pStomper || (saved != NULL && p == saved))
        return "stomper";
    if ((pStomper != NULL && p == pStomper->pStack)
        || (saved != NULL && p == saved->pStack))
        return "stack";
    if (p == &obj2)
        return "obj2";
    if (p == obj2.pStack)
        return "obj2stack";
    return "?";
}

void *bMalloc(int size, const char *name, int flags, int pool)
{
    printf("  malloc %d %s %d %d\n",
           size == (int)sizeof(Stomper) ? 12 : size, name, flags, pool);
    return calloc(1, (size_t)size);
}

void bFree(void *p)
{
    printf("  free %s\n", label(p));
}

int32_t radialblur_on_off(int32_t on, int32_t player)
{
    printf("  radial %d %08x\n", on, (uint32_t)player);
    return (int32_t)((uint32_t)player ^ 0x5a5a0000u ^ (uint32_t)on);
}

static int32_t fi(int32_t set, int32_t v)
{
    printf("  fi %d %08x\n", set, (uint32_t)v);
    return (int32_t)((uint32_t)v ^ 0x0f0f0f0fu ^ (uint32_t)set);
}

static float ff(int32_t set, float f)
{
    uint32_t b;

    memcpy(&b, &f, 4);
    printf("  ff %d %08x\n", set, b);
    b ^= 0x00400000u ^ ((uint32_t)set << 1);
    memcpy(&f, &b, 4);
    return f;
}

static void hex(const char *tag, const uint8_t *p, int n)
{
    int i;

    printf("  %s", tag);
    for (i = 0; i < n; i++)
        printf("%s%02x", (i & 3) ? "" : " ", p[i]);
    printf("\n");
}

static void dump(void)
{
    int i;

    if (pStomper == NULL) {
        printf("stomper null\n");
    } else {
        printf("stomper en %d cur %d stack %s\n", pStomper->bEnabled,
               pStomper->nCurrent, label(pStomper->pStack));
        if (pStomper->pStack != NULL)
            hex("stack", pStomper->pStack, 64);
    }
    printf("  targets");
    for (i = 0; i < NTARGETS; i++)
        printf(" %08x", word(targets[i]));
    printf("\n");
}

static void dump_list(void)
{
    hex("tgt", tgt, NTGT);
    hex("save", save, 96);
}

static void dump_obj2(void)
{
    printf("obj2 en %d cur %d stack %s\n", obj2.bEnabled, obj2.nCurrent,
           label(obj2.pStack));
}

int main(int argc, char **argv)
{
    FILE *f;
    char  line[256];
    int   i;

    if (argc < 2 || (f = fopen(argv[1], "r")) == NULL) {
        fprintf(stderr, "usage: stomper_test script.txt\n");
        return 2;
    }
    init_targets();
    TheEasterEggs.Codes = codes;

    while (fgets(line, sizeof line, f)) {
        char     op[8];
        int      a = 0, b = 0;
        unsigned u = 0, v = 0, w = 0, x = 0, y = 0, z = 0;
        uint8_t *r;

        line[strcspn(line, "\r\n")] = 0;
        if (sscanf(line, "%7s", op) != 1)
            continue;
        if (strcmp(op, "T") == 0) {
            printf("[%s]\n", line + 2);
        } else if (strcmp(op, "D") == 0) {
            dump();
        } else if (strcmp(op, "I") == 0) {
            printf("init\n");
            InitStomper();
        } else if (strcmp(op, "X") == 0) {
            printf("close\n");
            CloseStomper();
        } else if (strcmp(op, "S") == 0) {
            sscanf(line + 1, "%d", &a);
            printf("set %d\n", a);
            stomper_set(pStomper, a);
        } else if (strcmp(op, "C") == 0) {
            printf("clear\n");
            stomper_clear(pStomper);
        } else if (strcmp(op, "CS") == 0) {
            sscanf(line + 2, "%d", &a);
            printf("clear set %d\n", a);
            stomper_clear_set(pStomper, a);
        } else if (strcmp(op, "SU") == 0) {
            printf("suspend\n");
            stomper_suspend(pStomper);
        } else if (strcmp(op, "RE") == 0) {
            printf("resume\n");
            stomper_resume(pStomper);
        } else if (strcmp(op, "RR") == 0) {
            printf("reset eggs\n");
            ResetRenderEggs();
        } else if (strcmp(op, "SR") == 0) {
            printf("suspend eggs\n");
            SuspendRenderEggs();
        } else if (strcmp(op, "RS") == 0) {
            printf("resume eggs\n");
            ResumeRenderEggs();
        } else if (strcmp(op, "DR") == 0) {
            printf("disable eggs\n");
            DisableRenderEggs();
        } else if (strcmp(op, "ER") == 0) {
            printf("enable eggs\n");
            EnableRenderEggs();
        } else if (strcmp(op, "EG") == 0) {
            printf("eggs from codes\n");
            SetRenderEggFromEasterEggs();
        } else if (strcmp(op, "O") == 0) {
            sscanf(line + 1, "%d %d", &a, &b);
            codes[a].On = b;
        } else if (strcmp(op, "P") == 0) {
            sscanf(line + 1, "%d %x", &a, &u);
            memcpy(targets[a], &u, 4);
        } else if (strcmp(op, "SF") == 0) {
            sscanf(line + 2, "%x", &u);
            for (i = 0; i < STOMPER_STACK_SIZE; i++)
                pStomper->pStack[i] = (uint8_t)(u + 5 * i);
        } else if (strcmp(op, "N") == 0) {
            saved    = pStomper;
            pStomper = NULL;
        } else if (strcmp(op, "NR") == 0) {
            pStomper = saved;
            saved    = NULL;
        } else if (strcmp(op, "TW") == 0) {
            sscanf(line + 2, "%d %x %x %d %d %d", &a, &u, &v, &b,
                   (int *)&w, (int *)&x);
            WeatherUseTweakerValues = a;
            memcpy(&WeatherFog, &u, 4);
            memcpy(&WeatherFogStart, &v, 4);
            WeatherFogColourR = b;
            WeatherFogColourG = (int32_t)w;
            WeatherFogColourB = (int32_t)x;
        } else if (strcmp(op, "W") == 0) {
            WeatherQuery q;
            bVector3     pos;
            uint32_t     qw[6];

            sscanf(line + 1, "%d %x %x %x", &a, &x, &y, &z);
            WorldTimeFrames = a;
            for (i = 0; i < 6; i++)
                qw[i] = 0xdead0000u + (uint32_t)i;
            memcpy(&q, qw, sizeof qw);
            memcpy(&pos.x, &x, 4);
            memcpy(&pos.y, &y, 4);
            memcpy(&pos.z, &z, 4);
            pos.pad = 0.0f;
            WeatherManQuery(&q, &pos);
            memcpy(qw, &q, sizeof qw);
            printf("query %d", a);
            for (i = 0; i < 6; i++)
                printf(" %08x", qw[i]);
            printf("\n");
        } else if (strcmp(op, "LE") == 0) {
            StompEntry *s;

            sscanf(line + 2, "%d %d %d %x", &a, &b, (int *)&w, &u);
            s = &list[a];
            s->nType = b;
            switch (b) {
            case STOMP_INT8: case STOMP_INT16: case STOMP_INT32:
            case STOMP_FLOAT:
                s->u.pData = tgt + w;
                break;
            case STOMP_FUNCTION_INT:
                s->u.pFuncInt = fi;
                break;
            case STOMP_FUNCTION_FLOAT:
                s->u.pFuncFloat = ff;
                break;
            case STOMP_NESTED:
                s->u.pNested = &list[w];
                break;
            default:
                s->u.pData = NULL;
                break;
            }
            memcpy(&s->v, &u, 4);
        } else if (strcmp(op, "LF") == 0) {
            sscanf(line + 2, "%x", &u);
            for (i = 0; i < NTGT; i++)
                tgt[i] = (uint8_t)(u + 7 * i);
            for (i = 0; i < NSAVE; i++)
                save[i] = (uint8_t)(u * 3 + 13 * i + 1);
        } else if (strcmp(op, "L1") == 0 || strcmp(op, "L0") == 0
                   || strcmp(op, "LS") == 0 || strcmp(op, "LC") == 0) {
            sscanf(line + 2, "%d %d", &a, &b);
            if (op[1] == '1')
                r = stompentry_set(&list[a], save + b);
            else if (op[1] == '0')
                r = stompentry_clear(&list[a], save + b);
            else if (op[1] == 'S')
                r = stompentry_set_all(&list[a], save + b);
            else
                r = stompentry_clear_all(&list[a], save + b);
            printf("%s %d %d -> %d\n", op, a, b, (int)(r - save));
            dump_list();
        } else if (strcmp(op, "K") == 0) {
            sscanf(line + 1, "%x", &u);
            obj2.bEnabled = (int32_t)(0x5a5a0000u | u);
            obj2.pStack   = (uint8_t *)(uintptr_t)1;
            obj2.nCurrent = (int32_t)(0x5a5a0200u | u);
            dump_obj2();
        } else if (strcmp(op, "KC") == 0) {
            Stomper *s = stomper_construct(&obj2);

            printf("construct -> %s\n", label(s));
            dump_obj2();
        } else if (strcmp(op, "KX") == 0) {
            sscanf(line + 2, "%d", &a);
            printf("destroy %d\n", a);
            stomper_destroy(&obj2, a);
        } else {
            fprintf(stderr, "bad op %s\n", line);
            return 3;
        }
        fflush(stdout);
    }
    return 0;
}
