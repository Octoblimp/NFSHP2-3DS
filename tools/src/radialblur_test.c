// Harness for tools/radialblur_check.py: runs the checker's script on
// radialblur.c, and prints what the model prints for the retail image.
// See the checker's docstring.
//
//     radialblur_test script.txt > out.txt

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "esolid.h"
#include "race.h"
#include "racecoord.h"
#include "radialblur.h"
#include "replayscreen.h"

#define NVIEWS 5

// ------------------------------------------- what radialblur.c reaches for

static eView           views[NVIEWS];
static eRenderTarget   targets[NVIEWS];
static RaceCoordinator coord;
static ReplayScreen    replay;
static uint8_t         blur_ti[164];
static uint8_t         other_ti[164];

RaceCoordinator *pRaceCoordinator;
void            *pTextureInfoRadialBlur = blur_ti;

eView *eGetView(int32_t id)
{
    return &views[id];
}

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

static const char *tex_name(const void *t)
{
    if (t == NULL)
        return "null";
    if (t == blur_ti)
        return "blur";
    if (t == other_ti)
        return "other";
    return "?";
}

static void print_poly(const ePoly *p, const char *tex)
{
    int i;

    printf("  poly %s 0\n", tex);
    for (i = 0; i < 4; i++)
        printf("    v %08x %08x %08x %08x\n", fbits(p->Vertices[i].x),
               fbits(p->Vertices[i].y), fbits(p->Vertices[i].z),
               fbits(p->Vertices[i].w));
    for (i = 0; i < 4; i++)
        printf("    uv %08x %08x %08x\n", fbits(p->UVs[i][0]),
               fbits(p->UVs[i][1]), fbits(p->UVs[i][2]));
    for (i = 0; i < 4; i++)
        printf("    c %02x %02x %02x %02x\n", p->Colours[i][0],
               p->Colours[i][1], p->Colours[i][2], p->Colours[i][3]);
    printf("    a %d %d %d %d %d %d %d %d %d %d\n", p->AlphaA, p->AlphaB,
           p->AlphaC, p->AlphaD, p->AlphaFix, p->AlphaEnabled, p->SunPoly,
           p->ApplyAspectRatio, p->Flailer, p->pDynamicFrameMemory != NULL);
}

static void print_state(void)
{
    int i;

    printf("S %02x %02x %02x %02x |", RadialBlurFromAlpha[0],
           RadialBlurFromAlpha[1], RadialBlurToAlpha[0],
           RadialBlurToAlpha[1]);
    for (i = 0; i < NVIEWS; i++)
        printf(" %s", tex_name(views[i].pBlendMask));
    printf("\n");
}

static void *blend_of(int b)
{
    return b == 0 ? NULL : b == 1 ? (void *)blur_ti : (void *)other_ti;
}

// ------------------------------------------------------------ the script

int main(int argc, char **argv)
{
    FILE *f;
    char  line[256];
    int   i;

    if (argc < 2 || (f = fopen(argv[1], "r")) == NULL) {
        fprintf(stderr, "usage: radialblur_test script.txt\n");
        return 2;
    }
    for (i = 0; i < NVIEWS; i++)
        views[i].pRenderTarget0 = &targets[i];

    while (fgets(line, sizeof line, f)) {
        char     op[8];
        int      a = 0, b = 0, c = 0, d = 0, e = 0, g = 0, h = 0, k = 0, m = 0;
        unsigned u = 0, v = 0;

        if (sscanf(line, "%7s", op) != 1)
            continue;
        if (strcmp(op, "F") == 0) {
            sscanf(line + 1, "%x", &u);
            memset(RadialBlurFromAlpha, (int)u, 2);
            memset(RadialBlurToAlpha, (int)u, 2);
            printf("F %02x\n", u);
            print_state();
        } else if (strcmp(op, "C") == 0) {
            sscanf(line + 1, "%d %d %d", &a, &b, &c);
            if (a < 0) {
                pRaceCoordinator = NULL;
            } else {
                pRaceCoordinator = &coord;
                coord.CurrentRCState = a;
                coord.pReplayScreen = b ? &replay : NULL;
                replay.PlayerNumber = c;
            }
            printf("C %d %d %d\n", a, b, c);
        } else if (strcmp(op, "V") == 0) {
            sscanf(line + 1, "%d %d %d %d %d %d %d %d %d %x", &a, &b, &c, &d,
                   &e, &g, &h, &k, &m, &u);
            views[a].ID = b;
            views[a].Active = (uint8_t)c;
            views[a].pBlendMask = blend_of(d);
            targets[a].Active = (uint32_t)e;
            targets[a].ScissorX = g;
            targets[a].ScissorY = h;
            targets[a].ScissorW = k;
            targets[a].ScissorH = m;
            targets[a].MaxZ = bfloat(u);
            printf("V %d %d %d %d %d %d %d %d %d %08x\n", a, b, c, d, e, g,
                   h, k, m, u);
            print_state();
        } else if (strcmp(op, "G") == 0) {
            eView *r;

            sscanf(line + 1, "%d", &a);
            r = radialblur_player_view(a);
            if (r == NULL)
                printf("G %d -> null\n", a);
            else
                printf("G %d -> %d\n", a, (int)(r - views));
        } else if (strcmp(op, "ON") == 0) {
            sscanf(line + 2, "%d", &a);
            radialblur_on(a);
            printf("ON %d\n", a);
            print_state();
        } else if (strcmp(op, "OFF") == 0) {
            sscanf(line + 3, "%d", &a);
            radialblur_off(a);
            printf("OFF %d\n", a);
            print_state();
        } else if (strcmp(op, "VON") == 0) {
            sscanf(line + 3, "%d", &a);
            radialblur_view_on(&views[a]);
            printf("VON %d\n", a);
            print_state();
        } else if (strcmp(op, "VOFF") == 0) {
            sscanf(line + 4, "%d", &a);
            radialblur_view_off(&views[a]);
            printf("VOFF %d\n", a);
            print_state();
        } else if (strcmp(op, "OO") == 0) {
            sscanf(line + 2, "%d %d", &a, &b);
            radialblur_on_off_view(a, &views[b]);
            printf("OO %d %d\n", a, b);
            print_state();
        } else if (strcmp(op, "OP") == 0) {
            sscanf(line + 2, "%d %d", &a, &b);
            c = radialblur_on_off(a, b);
            printf("OP %d %d -> %d\n", a, b, c);
            print_state();
        } else if (strcmp(op, "R") == 0) {
            sscanf(line + 1, "%d", &a);
            radialblur_replay(a);
            printf("R %d\n", a);
            print_state();
        } else if (strcmp(op, "A") == 0) {
            sscanf(line + 1, "%d %x %x", &a, &u, &v);
            radialblur_alpha(a, bfloat(u), bfloat(v));
            printf("A %d %08x %08x\n", a, u, v);
            print_state();
        } else if (strcmp(op, "D") == 0) {
            ePoly polys[4];
            int   n;

            sscanf(line + 1, "%d", &a);
            printf("D %d\n", a);
            n = radialblur_mask_polys(&views[a], polys);
            for (i = 0; i < n; i++)
                print_poly(&polys[i], tex_name(views[a].pBlendMask));
            if (n)
                printf("  attach\n");
        } else if (strcmp(op, "P") == 0) {
            ePoly poly;

            sscanf(line + 1, "%d", &a);
            printf("P %d\n", a);
            if (radialblur_previous_poly(&views[a], &poly)) {
                print_poly(&poly, "prev");
                printf("  attach\n");
            }
        }
    }
    fclose(f);
    return 0;
}
