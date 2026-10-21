// Harness for tools/dof_check.py: runs the checker's scenarios on efocus.c
// and prints what the model prints for the image. eGetView and ZRanges are
// the harness's, and so are eFrameCounter and WorldTimeFrames, for the
// weatherman.c that efog.c brings in; the seams eAttachDepthOfField hands
// each palette and the blur to log them, with the band. See the checker's
// docstring.
//
//     dof_test scenarios.txt > out.txt

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "efocus.h"
#include "eview.h"

#define NUM_VIEWS 5

eZRange  ZRanges[2];
uint32_t eFrameCounter;
int32_t  WorldTimeFrames;

static eView  views[EVIEW_NUM_VIEWS];
static Camera cams[EVIEW_NUM_VIEWS];

eView *eGetView(int32_t id)
{
    return &views[id];
}

static uint32_t   scratch_pal[256];
static EFocusBand attached[NUM_VIEWS];
static int        has_band[NUM_VIEWS];

static float fbits(uint32_t u)
{
    float f;

    memcpy(&f, &u, 4);
    return f;
}

static uint32_t bitsf(float f)
{
    uint32_t u;

    memcpy(&u, &f, 4);
    return u;
}

static const char *label(const void *p)
{
    static char buf[4][16];
    static int  k;
    char       *b = buf[k++ & 3];
    int         i;

    if (p == NULL)
        return "null";
    for (i = 0; i < 4; i++) {
        if (p == FocusPalettes[i]) {
            snprintf(b, 16, "focus%d", i);
            return b;
        }
    }
    if (p == scratch_pal)
        return "pal";
    return "x";
}

static void dump_palette(const char *name, const uint32_t *p)
{
    int k;

    printf("  %s", name);
    for (k = 0; k < 256; k++)
        printf(" %x", p[k]);
    printf("\n");
}

// ------------------------------------------------------------ the seams

static void dof_attach(eView *view, const uint32_t *palette,
                       const EFocusBand *band)
{
    int id = view->ID;

    if (band != NULL) {
        printf("  attach view %d %s band %d %d\n", id, label(palette),
               band->Near, band->Far);
    } else {
        printf("  attach view %d %s noband\n", id, label(palette));
    }
    if (id >= 0 && id < NUM_VIEWS) {
        has_band[id] = band != NULL;
        if (band != NULL)
            attached[id] = *band;
    }
}

static void dof_blur(void)
{
    printf("  blur\n");
}

// ------------------------------------------------------------ the ops

static const int32_t get_ids[] = {
    -1, 0, 1, 2, 3, 4, 5, 9, 0x7fffffff, (int32_t)0x80000000u,
};

// The helpers' operands, as the checker lists them.
static const uint32_t s2p_zs[] = {
    0x00000000u, 0x40000000u, 0x40000010u, 0x400ff010u, 0x40000fffu,
    0x40001000u, 0x4007f000u, 0x40080000u, 0x400ff000u, 0x40100000u,
    0x3f800000u, 0xbf800000u, 0x7f800000u, 0xffffffffu, 0x12345678u,
};
static const uint32_t p2s_is[] = {
    0, 1, 2, 15, 16, 127, 128, 200, 254, 255, 256, 0x1ff, 0xffffffffu,
    0x80000000u,
};

typedef struct { uint32_t near, far, sz; } VzArgs;

static const VzArgs s2v_args[] = {
    { 0x3f000000u, 0x44fa0000u, 0x40000010u },  // 0.5, 2000, ZMin
    { 0x3f000000u, 0x44fa0000u, 0x40400000u },  // 3.0
    { 0x3f000000u, 0x44fa0000u, 0x407ff000u },
    { 0x3f000000u, 0x44fa0000u, 0x40800000u },  // ZMax
    { 0x3f800000u, 0x44bb8000u, 0x40200000u },  // 1, 1500, 2.5
    { 0x3e800000u, 0x457a0000u, 0x40100000u },  // 0.25, 4000
    { 0x41200000u, 0x41200000u, 0x40400000u },  // near == far
    { 0x447a0000u, 0x3f800000u, 0x40400000u },  // near past far
    { 0x3f000000u, 0x44fa0000u, 0x00000000u },
    { 0x3f000000u, 0x44fa0000u, 0xc0000000u },
};

static const uint32_t pica_gs[] = {
    0, 1, 2, 63, 64, 65, 100, 127, 128, 129, 200, 255, 256, 1000,
    0xffffffffu,
};

// The depths the plan's alphas are printed at.
static uint32_t d24s[1024];
static int      nd24;

static void add_d24(uint32_t d)
{
    int i;

    for (i = 0; i < nd24; i++) {
        if (d24s[i] == d)
            return;
    }
    d24s[nd24++] = d;
}

static void make_d24s(void)
{
    static const uint32_t edges[] = {
        1, 0x7f, 0x80, 0x1ff, 0x200, 0x3ff, 0x400, 0x1e0, 0x1df, 0xffff,
        0x10000, 0x10001, 0x101ff, 0x1fdff, 0x1fe00, 0x1feff, 0x1ff00,
        0x1ffff, 0x20000, 0x20001, 0x2ffff, 0x30000, 0x7fffff, 0x800000,
        0xfffffe, 0xffffff,
    };
    uint32_t d;
    size_t   i;

    for (d = 0; d <= 0x20400; d += 0x100)
        add_d24(d);
    for (i = 0; i < sizeof edges / sizeof *edges; i++)
        add_d24(edges[i]);
}

// P is checked against the palette by the model, Q is not: the harness
// prints the model's verdict for P.
static void plan_op(int id, int checked)
{
    EFocusPlan plan;
    int        n;

    efocus_plan(FocusPalettes[id - 1],
                has_band[id] ? &attached[id] : NULL, &plan);
    printf("  plan %d", plan.Count);
    for (n = 0; n < plan.Count; n++) {
        const EFocusStep *s = &plan.Step[n];

        printf(" [at %08x ramp %d alpha %d far %d near %d q %d t %d k %d "
               "min %d max %d]", bitsf(plan.At[n]), s->Ramp, s->Alpha,
               s->FarB, s->NearB, s->Quads, s->Times, s->K, s->Min, s->Max);
    }
    printf("\n  alphas");
    for (n = 0; n < nd24; n++) {
        float a = efocus_pica_alpha(&plan, d24s[n]);

        printf(" %x", (unsigned)(a * 255.0f + 0.5f));
    }
    printf("\n");
    if (checked)
        printf("  bound ok\n");
}

static void op(const char *o)
{
    size_t i;

    printf(" %s\n", o);
    if (strcmp(o, "A") == 0) {
        printf("  -> %d\n", eattach_depth_of_field());
        for (i = 0; i < 4; i++) {
            char name[16];

            snprintf(name, sizeof name, "focus%d", (int)i);
            dump_palette(name, FocusPalettes[i]);
        }
    } else if (o[0] == 'C' && o[1] == 'n') {
        printf("  -> %d\n", CreateFocusPalette(NULL, scratch_pal));
        dump_palette("pal", scratch_pal);
    } else if (o[0] == 'C' && o[1] == 'p') {
        printf("  -> %d\n", CreateFocusPalette(&views[atoi(o + 2)], NULL));
    } else if (o[0] == 'C') {
        printf("  -> %d\n", CreateFocusPalette(&views[atoi(o + 1)],
                                               scratch_pal));
        dump_palette("pal", scratch_pal);
    } else if (o[0] == 'P' || o[0] == 'Q') {
        plan_op(atoi(o + 1), o[0] == 'P');
    } else if (strcmp(o, "G") == 0) {
        eView tmp;

        memset(&tmp, 0, sizeof tmp);
        printf("  get");
        for (i = 0; i < sizeof get_ids / sizeof *get_ids; i++) {
            tmp.ID = get_ids[i];
            printf(" %s", label(GetFocusPalette(&tmp)));
        }
        printf("\n");
    } else if (strcmp(o, "H") == 0) {
        printf("  s2p");
        for (i = 0; i < sizeof s2p_zs / sizeof *s2p_zs; i++)
            printf(" %x", MapScreenZToPaletteIndex(fbits(s2p_zs[i])));
        printf("\n  p2s");
        for (i = 0; i < sizeof p2s_is / sizeof *p2s_is; i++)
            printf(" %08x", bitsf(MapPaletteIndexToScreenZ(p2s_is[i])));
        printf("\n  s2v");
        for (i = 0; i < sizeof s2v_args / sizeof *s2v_args; i++)
            printf(" %08x", bitsf(MapScreenZToViewZ(
                                fbits(s2v_args[i].near),
                                fbits(s2v_args[i].far),
                                fbits(s2v_args[i].sz))));
        printf("\n");
    } else if (strcmp(o, "B") == 0) {
        printf("  byte");
        for (i = 0; i < sizeof pica_gs / sizeof *pica_gs; i++)
            printf(" %d", efocus_pica_byte(pica_gs[i]));
        printf("\n");
    } else if (strcmp(o, "g") == 0) {
        printf("  globals print %d\n", FocusPrintPalette);
    } else {
        printf("  ?\n");
    }
}

// ------------------------------------------------------------ the script

int main(int argc, char **argv)
{
    FILE *f;
    char  line[4096];
    int   k = 0;

    if (argc < 2) {
        fprintf(stderr, "usage: dof_test scenarios.txt\n");
        return 2;
    }
    f = fopen(argv[1], "r");
    if (f == NULL) {
        perror(argv[1]);
        return 2;
    }
    make_d24s();
    gEDofAttachFn = dof_attach;
    gEDofBlurFn   = dof_blur;
    printf("start draw %d print %d min %08x max %08x focal %08x dof %08x "
           "blend %d samples %d len %d first %08x\n",
           DrawDepthOfField, FocusPrintPalette, bitsf(FocusAlphaMin),
           bitsf(FocusAlphaMax), bitsf(FocalDistance), bitsf(DepthOfField),
           JitterBlend, FocusJitterSamples, FocusRampLength,
           bitsf(FocusFirstPrevious));
    printf("jitter");
    for (k = 0; k < 6; k++)
        printf(" %d,%d", FocusJitter[k][0], FocusJitter[k][1]);
    printf("\n");
    k = 0;
    while (fgets(line, sizeof line, f)) {
        char    *p = line;
        unsigned a, b, c, d, e, g, h;
        int      i, n;

        line[strcspn(line, "\r\n")] = 0;
        if (line[0] == 'S') {
            // A scenario: the views and palettes as the model resets them.
            printf("scenario %d %s\n", k++, line + 2);
            memset(views, 0, sizeof views);
            memset(cams, 0, sizeof cams);
            memset(has_band, 0, sizeof has_band);
            for (i = 0; i < EVIEW_NUM_VIEWS; i++) {
                views[i].ID      = i;
                views[i].pCamera = &cams[i];
            }
            for (n = 0; n < 4; n++) {
                for (i = 0; i < 256; i++)
                    FocusPalettes[n][i] = 0xde000000u | (uint32_t)n << 16
                                        | (uint32_t)i;
            }
            for (i = 0; i < 256; i++)
                scratch_pal[i] = 0xdead0000u + (uint32_t)i;
        } else if (sscanf(line, "g %u %u %x %x %x %x %d", &a, &b, &c, &d,
                          &e, &g, &n) == 7) {
            DrawDepthOfField  = (int32_t)a;
            FocusPrintPalette = (int32_t)b;
            FocusAlphaMin     = fbits(c);
            FocusAlphaMax     = fbits(d);
            FocalDistance     = fbits(e);
            DepthOfField      = fbits(g);
            FocusRampLength   = n;
            p = strrchr(line, ' ');
            FocusFirstPrevious = fbits((uint32_t)strtoul(p + 1, NULL, 16));
        } else if (sscanf(line, "z %x %x", &a, &b) == 2) {
            ZRanges[1].ZMin = fbits(a);
            ZRanges[1].ZMax = fbits(b);
        } else if (sscanf(line, "v %d %x %x %x %x %x", &i, &a, &b, &c, &d,
                          &h) == 6) {
            views[i].Active = (uint8_t)a;
            views[i].NearZ  = fbits(b);
            views[i].FarZ   = fbits(c);
            cams[i].CurrentKey.FocalDistance = fbits(d);
            cams[i].CurrentKey.DepthOfField  = fbits(h);
        } else if (line[0] == 'o') {
            char *t = strtok(line + 1, " ");

            while (t != NULL) {
                op(t);
                t = strtok(NULL, " ");
            }
        }
    }
    fclose(f);
    return 0;
}
