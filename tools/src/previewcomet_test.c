// Host harness for 3DS Files/source/previewcomet.c, the Zone Preview's
// comet. Runs the op script tools/previewcomet_check.py writes and prints
// the transcript it diffs against the retail image, run in mipsemu over the
// same script.
//
// The harness owns what the comet reaches outside its own file: the
// splines, the params blocks, the frame memory, and printing stand-ins for
// bMalloc (a patterned arena), bFree, the emitter-data lookup (a scripted
// group of datas), SetEmitterData, AcidEmitter's destructor, the effect
// system's AddAutoEmitter and RemoveAutoEmitter, GetTextureInfo and
// ePoly::Render3D, as the model's stubs do.
//
// Every comet and block starts as 0xa5 bytes, so a field the port leaves
// alone and retail writes (or the other way round) shows. A float prints as
// its bits, every NaN as "nan", and a pointer by what it is. Sizes and
// offsets print in retail's 32-bit terms.
//
//     previewcomet_test script.txt > out.txt

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "acidsys.h"
#include "bchunk.h"
#include "bmem.h"
#include "eframe.h"
#include "epoly.h"
#include "previewcomet.h"
#include "spline.h"
#include "texturepack.h"

// realtime.c's clock, which replay.c reaches for; not linked here.
int32_t WorldTimer;
int32_t WorldLoopCounter;

#define PATTERN    0xa5
#define NCOMET     3
#define NSPL       8
#define NPTS       64
#define NPRM       8
#define NDATA      8
#define FM_SIZE    0x1000
#define ARENA_SIZE 0x40000
#define NBLOCK     256
#define RETAIL_EMITTER 192

static const char *group_names[2] = { "ZONE_PREVIEW", "SMOKE_PUFFS" };

// What previewcomet.c links against, the harness's own.
int32_t          NumAcidEmitters;
AcidEffectSystem FrameEffects;
AcidEffectSystem WorldEffects;
uint8_t         *CurrentBufferPos;
uint8_t         *CurrentBufferEnd;
int32_t          FrameMallocFailed;
uint32_t         FrameMallocFailAmount;

static PreviewComet       comets[NCOMET];
static Spline             spl[NSPL];
static bVector3           pts[NSPL][NPTS + 3];
static PreviewCometParams prm[NPRM];
static AcidEmitterData    datas[NDATA];
static int                ndatas;
static uint8_t            tex[164];
static int                tex_on = 1;
static uint8_t            fm[FM_SIZE] __attribute__((aligned(16)));

static unsigned char arena[ARENA_SIZE] __attribute__((aligned(16)));
static size_t        arena_used;
static void         *blocks[NBLOCK];
static int           nblocks;

// ------------------------------------------------------------ the printing

static uint32_t fbits(float f)
{
    uint32_t u;

    memcpy(&u, &f, 4);
    return u;
}

static float bfloat(uint32_t u)
{
    float f;

    memcpy(&f, &u, 4);
    return f;
}

static const char *fx(float f)
{
    static char buf[32][12];
    static int  slot;
    char       *b = buf[slot++ & 31];
    uint32_t    w = fbits(f);

    if ((w & 0x7f800000u) == 0x7f800000u && (w & 0x7fffffu))
        return "nan";
    sprintf(b, "%08x", w);
    return b;
}

static PreviewCometParams *params_of(int k)
{
    switch (k) {
    case -1: return &ZonePreviewCometParams;
    case -2: return &DrivingLineCometParamsEasy;
    case -3: return &DrivingLineCometParamsMedium;
    case -4: return &DrivingLineCometParamsHard;
    }
    return &prm[k];
}

static const char *params_name(const PreviewCometParams *p)
{
    static char buf[8][16];
    static int  slot;
    char       *b = buf[slot++ & 7];
    int         k;

    for (k = -4; k < NPRM; k++)
        if (p == params_of(k)) {
            if (k < 0)
                sprintf(b, "g%d", -k);
            else
                sprintf(b, "p%d", k);
            return b;
        }
    return "?";
}

static const char *nm(const void *p)
{
    static char buf[16][40];
    static int  slot;
    char       *b = buf[slot++ & 15];
    int         i, k;

    if (p == NULL)
        return "null";
    for (i = nblocks - 1; i >= 0; i--) {
        const uint8_t *s = blocks[i];
        const uint8_t *q = p;

        if (q == s) {
            sprintf(b, "m%d", i);
            return b;
        }
        if (q >= s + 16 && (q - s - 16) % sizeof(AcidEmitter) == 0
            && q < s + 16 + 64 * sizeof(AcidEmitter)) {
            sprintf(b, "m%d[%d]", i, (int)((q - s - 16) / sizeof(AcidEmitter)));
            return b;
        }
    }
    if (p == tex)
        return "tex";
    if (p == &FrameEffects)
        return "frame";
    if (p == &WorldEffects)
        return "world";
    if ((const uint8_t *)p >= fm && (const uint8_t *)p < fm + FM_SIZE) {
        sprintf(b, "fm+%d", (int)((const uint8_t *)p - fm));
        return b;
    }
    for (i = 0; i < NDATA; i++)
        if (p == &datas[i]) {
            sprintf(b, "d%d", i);
            return b;
        }
    for (i = 0; i < NSPL; i++)
        if (p == &spl[i]) {
            sprintf(b, "s%d", i);
            return b;
        }
    for (k = -4; k < NPRM; k++) {
        const PreviewCometParams *q = params_of(k);

        if (p == q)
            return params_name(q);
        if (p == q->vPreviewCometWidth) {
            sprintf(b, "%s+36", params_name(q));
            return b;
        }
        if (p == q->vPreviewCometHead) {
            sprintf(b, "%s+80", params_name(q));
            return b;
        }
        if (p == q->vPreviewCometTail) {
            sprintf(b, "%s+124", params_name(q));
            return b;
        }
    }
    return "?";
}

static void print_comet(int ci)
{
    const PreviewComet *c = &comets[ci];
    int                 j, k;

    printf("  comet %d spl %s prm %s em %s n %d on %d tex %s\n", ci,
           nm(c->pLookSpline), nm(c->pParams), nm(c->pEmitters), c->nEmitters,
           c->Enabled, nm(c->pCometTexture));
    printf("  graphs %s %d %s %d %s %d\n", nm(c->Width.pPoints),
           c->Width.NumPoints, nm(c->Head.pPoints), c->Head.NumPoints,
           nm(c->Tail.pPoints), c->Tail.NumPoints);
    if (c->pEmitters == NULL)
        return;
    for (j = 0; j < c->nEmitters; j++) {
        const AcidEmitter *e = &c->pEmitters[j];
        const uint32_t    *name = (const uint32_t *)(const void *)e->Name;

        printf("  e%d %08x %08x %d %s %s %s %s %08x %08x %08x\n", j,
               e->NameHash, e->EmitterDataNameHash, e->State,
               fx(e->RemainingCycleTime), fx(e->EmissionCountdown),
               nm(e->EmitterData), nm(e->LastActiveGroup), e->RandomSeed,
               e->DontEmit, e->pad2);
        printf("    lw");
        for (k = 0; k < 4; k++) {
            const bVector4 *r = &(&e->LocalWorld.v0)[k];

            printf(" %s %s %s %s", fx(r->x), fx(r->y), fx(r->z), fx(r->w));
        }
        printf("\n    iv %s %s %s %s name", fx(e->InheritVelocity.x),
               fx(e->InheritVelocity.y), fx(e->InheritVelocity.z),
               fx(e->InheritVelocity.w));
        for (k = 0; k < 16; k++)
            printf(" %08x", name[k]);
        printf("\n");
    }
}

static void print_globals(void)
{
    printf("  g count %d fm %d failed %d amount %u\n", NumAcidEmitters,
           (int)(CurrentBufferPos - fm), FrameMallocFailed,
           FrameMallocFailAmount);
}

static void print_params(const PreviewCometParams *p)
{
    uint32_t w[52];
    int      i;

    memset(w, 0, sizeof w);
    w[1] = (uint32_t)p->nPreviewCometSegments;
    w[2] = fbits(p->fPreviewCometTextureDV);
    w[3] = p->nPreviewCometTexture;
    w[4] = fbits(p->fPreviewCometLineWidth);
    w[5] = fbits(p->fPreviewCometLineHeight);
    w[6] = fbits(p->fPreviewCometAltitude);
    w[7] = fbits(p->fPreviewCometLateralCoeff);
    w[8] = (uint32_t)p->nPreviewCometWidths;
    for (i = 0; i < 5; i++) {
        w[9 + 2 * i] = fbits(p->vPreviewCometWidth[i].x);
        w[10 + 2 * i] = fbits(p->vPreviewCometWidth[i].y);
    }
    w[19] = (uint32_t)p->nPreviewCometHeads;
    for (i = 0; i < 5; i++) {
        w[20 + 2 * i] = fbits(p->vPreviewCometHead[i].x);
        w[21 + 2 * i] = fbits(p->vPreviewCometHead[i].y);
    }
    w[30] = (uint32_t)p->nPreviewCometTails;
    for (i = 0; i < 5; i++) {
        w[31 + 2 * i] = fbits(p->vPreviewCometTail[i].x);
        w[32 + 2 * i] = fbits(p->vPreviewCometTail[i].y);
    }
    for (i = 0; i < 3; i++)
        w[41 + i] = (uint32_t)p->pad164[i];
    w[44] = fbits(p->vPreviewCometColour0.x);
    w[45] = fbits(p->vPreviewCometColour0.y);
    w[46] = fbits(p->vPreviewCometColour0.z);
    w[47] = fbits(p->vPreviewCometColour0.w);
    w[48] = fbits(p->vPreviewCometColour1.x);
    w[49] = fbits(p->vPreviewCometColour1.y);
    w[50] = fbits(p->vPreviewCometColour1.z);
    w[51] = fbits(p->vPreviewCometColour1.w);
    printf("  %s \"%s\"", params_name(p), p->EmitterGroupName);
    for (i = 1; i < 52; i++)
        printf(" %08x", w[i]);
    printf("\n");
}

static void set_params(PreviewCometParams *p, const uint32_t *w)
{
    int i;

    p->EmitterGroupName = group_names[w[0] & 1];
    p->nPreviewCometSegments = (int32_t)w[1];
    p->fPreviewCometTextureDV = bfloat(w[2]);
    p->nPreviewCometTexture = w[3];
    p->fPreviewCometLineWidth = bfloat(w[4]);
    p->fPreviewCometLineHeight = bfloat(w[5]);
    p->fPreviewCometAltitude = bfloat(w[6]);
    p->fPreviewCometLateralCoeff = bfloat(w[7]);
    p->nPreviewCometWidths = (int32_t)w[8];
    for (i = 0; i < 5; i++) {
        p->vPreviewCometWidth[i].x = bfloat(w[9 + 2 * i]);
        p->vPreviewCometWidth[i].y = bfloat(w[10 + 2 * i]);
    }
    p->nPreviewCometHeads = (int32_t)w[19];
    for (i = 0; i < 5; i++) {
        p->vPreviewCometHead[i].x = bfloat(w[20 + 2 * i]);
        p->vPreviewCometHead[i].y = bfloat(w[21 + 2 * i]);
    }
    p->nPreviewCometTails = (int32_t)w[30];
    for (i = 0; i < 5; i++) {
        p->vPreviewCometTail[i].x = bfloat(w[31 + 2 * i]);
        p->vPreviewCometTail[i].y = bfloat(w[32 + 2 * i]);
    }
    for (i = 0; i < 3; i++)
        p->pad164[i] = (int32_t)w[41 + i];
    p->vPreviewCometColour0.x = bfloat(w[44]);
    p->vPreviewCometColour0.y = bfloat(w[45]);
    p->vPreviewCometColour0.z = bfloat(w[46]);
    p->vPreviewCometColour0.w = bfloat(w[47]);
    p->vPreviewCometColour1.x = bfloat(w[48]);
    p->vPreviewCometColour1.y = bfloat(w[49]);
    p->vPreviewCometColour1.z = bfloat(w[50]);
    p->vPreviewCometColour1.w = bfloat(w[51]);
}

// ------------------------------------------------------------ the stubs

void *bMalloc(int size, const char *name, int flags, int pool)
{
    size_t off = (arena_used + 15) & ~(size_t)15;
    void  *p = arena + off;
    int    shown = size;

    arena_used = off + (size_t)size;
    if (arena_used > ARENA_SIZE || nblocks == NBLOCK) {
        fprintf(stderr, "arena full\n");
        exit(2);
    }
    // new AcidEmitter[n], in retail's sizes.
    if (size >= 16 && (size - 16) % (int)sizeof(AcidEmitter) == 0)
        shown = 16 + (size - 16) / (int)sizeof(AcidEmitter) * RETAIL_EMITTER;
    blocks[nblocks] = p;
    printf("  malloc %d %s %d %d -> m%d\n", shown, name, flags, pool, nblocks);
    nblocks++;
    return p;
}

void bFree(void *p)
{
    printf("  free %s\n", nm(p));
}

AcidEmitterData *afx_get_emitter_data(uint32_t name_hash, uint32_t group_hash,
                                      AcidEmitterData *after)
{
    AcidEmitterData *d;

    if (after == NULL)
        d = ndatas > 0 ? &datas[0] : NULL;
    else
        d = after + 1 < datas + ndatas ? after + 1 : NULL;
    printf("  getdata %08x %08x %s -> %s\n", name_hash, group_hash, nm(after),
           nm(d));
    return d;
}

int32_t acid_emitter_set_emitter_data(AcidEmitter *e, AcidEmitterData *d)
{
    printf("  setdata %s %s\n", nm(e), nm(d));
    if (d == NULL)
        return 0;
    e->EmitterData = d;
    return 1;
}

void acid_emitter_delete(AcidEmitter *e, int32_t flags)
{
    printf("  emitter dtor %s %d\n", nm(e), flags);
    NumAcidEmitters--;
}

void acid_system_add_auto_emitter(AcidEffectSystem *s, AcidEmitter *e)
{
    printf("  add %s %s\n", nm(s), nm(e));
}

void acid_system_remove_auto_emitter(AcidEffectSystem *s, AcidEmitter *e)
{
    printf("  remove %s %s\n", nm(s), nm(e));
}

TextureInfo *GetTextureInfo(uint32_t hash, int use_default,
                            int include_unloaded)
{
    void *t = tex_on ? tex : NULL;

    printf("  gettex %08x %d %d -> %s\n", hash, use_default,
           include_unloaded, nm(t));
    return t;
}

static void render3d(ePoly *p, TextureInfo *t, bMatrix4 *m, int flags)
{
    int i;

    printf("  draw %s %s %d\n", nm(t), nm(m), flags);
    for (i = 0; i < 4; i++)
        printf("    v %s %s %s %s\n", fx(p->Vertices[i].x),
               fx(p->Vertices[i].y), fx(p->Vertices[i].z),
               fx(p->Vertices[i].w));
    for (i = 0; i < 4; i++)
        printf("    uv %s %s %s\n", fx(p->UVs[i][0]), fx(p->UVs[i][1]),
               fx(p->UVs[i][2]));
    for (i = 0; i < 4; i++)
        printf("    c %02x %02x %02x %02x\n", p->Colours[i][0],
               p->Colours[i][1], p->Colours[i][2], p->Colours[i][3]);
    printf("    a %d %d %d %d %d %d %d %d %d %d\n", p->AlphaA, p->AlphaB,
           p->AlphaC, p->AlphaD, p->AlphaFix, p->AlphaEnabled, p->SunPoly,
           p->ApplyAspectRatio, p->Flailer, p->pDynamicFrameMemory != NULL);
    printf("    m");
    for (i = 0; i < 4; i++) {
        const bVector4 *r = &(&m->v0)[i];

        printf(" %s %s %s %s", fx(r->x), fx(r->y), fx(r->z), fx(r->w));
    }
    printf("\n");
}

// ------------------------------------------------------------ the script

static void after_op(int ci)
{
    if (ci >= 0)
        print_comet(ci);
    print_globals();
}

int main(int argc, char **argv)
{
    FILE *f;
    char  line[4096];
    int   i;

    if (argc < 2 || (f = fopen(argv[1], "r")) == NULL) {
        fprintf(stderr, "usage: previewcomet_test script.txt\n");
        return 2;
    }
    memset(comets, PATTERN, sizeof comets);
    memset(arena, PATTERN, sizeof arena);
    memset(prm, 0, sizeof prm);
    CurrentBufferPos = fm;
    CurrentBufferEnd = fm + FM_SIZE;
    gEPolyRender3DFn = render3d;

    while (fgets(line, sizeof line, f)) {
        char op[8];
        int  a = 0, b = 0, c = 0, n = 0;

        if (sscanf(line, "%7s", op) != 1)
            continue;
        if (strcmp(op, "S") == 0) {
            // S k type n, then the n points and a guard either side, as
            // 4 words each.
            char    *s = line + 1;
            uint32_t w[4];
            int      used, j;

            sscanf(s, "%d %d %d%n", &a, &b, &n, &used);
            s += used;
            for (i = 0; i < n + 3; i++) {
                for (j = 0; j < 4; j++) {
                    sscanf(s, "%x%n", &w[j], &used);
                    s += used;
                }
                pts[a][i].x = bfloat(w[0]);
                pts[a][i].y = bfloat(w[1]);
                pts[a][i].z = bfloat(w[2]);
                pts[a][i].pad = bfloat(w[3]);
            }
            spline_init(&spl[a], (SplineType)b, n, &pts[a][1], 0);
            printf("S %d %d %d\n", a, b, n);
        } else if (strcmp(op, "P") == 0) {
            char    *s = line + 1;
            uint32_t w[52];
            int      used;

            sscanf(s, "%d%n", &a, &used);
            s += used;
            for (i = 0; i < 52; i++) {
                sscanf(s, "%x%n", &w[i], &used);
                s += used;
            }
            set_params(&prm[a], w);
            printf("P %d\n", a);
            print_params(&prm[a]);
        } else if (strcmp(op, "G") == 0) {
            sscanf(line + 1, "%d", &a);
            ndatas = a;
            printf("G %d\n", a);
        } else if (strcmp(op, "T") == 0) {
            sscanf(line + 1, "%d", &a);
            tex_on = a;
            printf("T %d\n", a);
        } else if (strcmp(op, "M") == 0) {
            sscanf(line + 1, "%d", &a);
            CurrentBufferPos = fm;
            CurrentBufferEnd = fm + a;
            printf("M %d\n", a);
            print_globals();
        } else if (strcmp(op, "C") == 0) {
            sscanf(line + 1, "%d %d %d", &a, &b, &c);
            printf("C %d %d %d\n", a, b, c);
            memset(&comets[a], PATTERN, sizeof comets[a]);
            preview_comet_init(&comets[a], &spl[b], params_of(c));
            after_op(a);
        } else if (strcmp(op, "X") == 0) {
            sscanf(line + 1, "%d", &a);
            printf("X %d\n", a);
            preview_comet_destroy(&comets[a]);
            after_op(a);
        } else if (strcmp(op, "E") == 0) {
            sscanf(line + 1, "%d", &a);
            printf("E %d\n", a);
            preview_comet_enable(&comets[a]);
            after_op(a);
        } else if (strcmp(op, "F") == 0) {
            sscanf(line + 1, "%d", &a);
            printf("F %d\n", a);
            preview_comet_disable(&comets[a]);
            after_op(a);
        } else if (strcmp(op, "O") == 0) {
            sscanf(line + 1, "%d %d %d", &a, &b, &c);
            comets[a].pEmitters[b].State = c;
            printf("O %d %d %d\n", a, b, c);
        } else if (strcmp(op, "R") == 0) {
            unsigned u;

            sscanf(line + 1, "%d %x", &a, &u);
            printf("R %d %08x\n", a, u);
            preview_comet_render(&comets[a], NULL, bfloat(u));
            after_op(a);
        } else if (strcmp(op, "I") == 0) {
            printf("I\n");
            for (i = -1; i >= -4; i--)
                print_params(params_of(i));
        }
        // A crash's transcript ends at the op that made it.
        fflush(stdout);
    }
    fclose(f);
    return 0;
}
