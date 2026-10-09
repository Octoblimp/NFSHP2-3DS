// lightflare_test -- tools/lightflare_check.py's harness.
//
// Runs elightflare.c, with epoly.c's constructor and emath.c's identity
// matrix, over the checker's script. GetTextureInfo and ePoly::Render3D
// are stubs that log what they are given, as the model's are; the flare
// packs' list and InGameFlag are this file's. Textures print as T0..T2,
// matrices as I (eMathIdentityMatrix), LW, or "?".

#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "camera.h"
#include "elight.h"
#include "elightflare.h"
#include "emath.h"
#include "epoly.h"
#include "eview.h"
#include "texturepack.h"

#define NFLARES 16
#define NPACKS  3

// ---------------------------------------------------- what the port reads

bNode   eLightFlarePackList = { &eLightFlarePackList, &eLightFlarePackList };
int32_t InGameFlag;

static eView                 view;
static Camera                cam;
static bMatrix4              wv, wc, lw;
static eLightFlare           flares[NFLARES];
static eLightFlarePackHeader packs[NPACKS];
static TextureInfo           texes[NUM_LIGHT_FLARE_TEXTURES];
static int                   tex_on[NUM_LIGHT_FLARE_TEXTURES];

static uint32_t fb(float f)
{
    uint32_t u;

    memcpy(&u, &f, 4);
    return u;
}

static float bf(uint32_t u)
{
    float f;

    memcpy(&f, &u, 4);
    return f;
}

static float hf(const char *s)
{
    return bf((uint32_t)strtoul(s, NULL, 16));
}

static const char *tname(const TextureInfo *t)
{
    static const char *names[] = { "T0", "T1", "T2" };
    int i;

    if (t == NULL)
        return "NULL";
    for (i = 0; i < NUM_LIGHT_FLARE_TEXTURES; i++)
        if (t == &texes[i])
            return names[i];
    return "?";
}

static const char *mname(const bMatrix4 *m)
{
    if (m == &eMathIdentityMatrix)
        return "I";
    if (m == &lw)
        return "LW";
    return "?";
}

// ------------------------------------------------------------- the stubs

TextureInfo *GetTextureInfo(uint32_t hash, int use_default,
                            int include_unloaded)
{
    static const uint32_t hashes[NUM_LIGHT_FLARE_TEXTURES] = {
        0x8868656fu, 0x88d8e8a2u, 0x3394fe62u,
    };
    int i;

    printf("  gettex %08x %d %d\n", hash, use_default, include_unloaded);
    for (i = 0; i < NUM_LIGHT_FLARE_TEXTURES; i++)
        if (hash == hashes[i])
            return tex_on[i] ? &texes[i] : NULL;
    return NULL;
}

// The poly from its vertices on, all but the three pad bytes at 153.
static void render3d(ePoly *p, TextureInfo *tex, bMatrix4 *m, int flags)
{
    const uint8_t *b = (const uint8_t *)p;
    uint32_t w;
    int i;

    printf("  r3d %s %s %d", tname(tex), mname(m), flags);
    for (i = 16; i < 144; i += 4) {
        memcpy(&w, b + i, 4);
        printf(" %08x", w);
    }
    for (i = 144; i < 153; i++)
        printf(" %02x", b[i]);
    printf(" %s\n", p->pDynamicFrameMemory == NULL ? "NULL" : "?");
}

// ------------------------------------------------------------ the script

#define MAXT 40

static int split(char *line, char **t)
{
    int n = 0;
    char *s = line;

    for (;;) {
        char *bar = strchr(s, '|');

        if (n < MAXT)
            t[n++] = s;
        if (bar == NULL)
            break;
        *bar = 0;
        s = bar + 1;
    }
    return n;
}

static int part_index(const eLightFlarePart *p)
{
    if (p == NULL)
        return -1;
    return (int)(p - SingleLightFlareParameters);
}

static void run(char **t, int n)
{
    const char *op = t[0];
    int i;

    printf("%s\n", op);
    if (!strcmp(op, "mat")) {
        bMatrix4 *m = !strcmp(t[1], "lw") ? &lw
                    : !strcmp(t[1], "wv") ? &wv
                    : !strcmp(t[1], "wc") ? &wc : &cam.CurrentKey.Matrix;
        float *f = &m->v0.x;

        for (i = 0; i < 16; i++)
            f[i] = hf(t[2 + i]);
    } else if (!strcmp(op, "campos")) {
        cam.CurrentKey.Position.x = hf(t[1]);
        cam.CurrentKey.Position.y = hf(t[2]);
        cam.CurrentKey.Position.z = hf(t[3]);
    } else if (!strcmp(op, "h")) {
        view.H = hf(t[1]);
    } else if (!strcmp(op, "cam")) {
        view.pCamera = atoi(t[1]) ? &cam : NULL;
    } else if (!strcmp(op, "flare")) {
        eLightFlare *f = &flares[atoi(t[1])];

        f->Enabled = (int8_t)atoi(t[2]);
        f->Type = (int8_t)atoi(t[3]);
        f->Flags = (uint16_t)atoi(t[4]);
        f->PositionX = hf(t[5]);
        f->PositionY = hf(t[6]);
        f->PositionZ = hf(t[7]);
        f->DirectionX = hf(t[8]);
        f->DirectionY = hf(t[9]);
        f->DirectionZ = hf(t[10]);
    } else if (!strcmp(op, "tex")) {
        tex_on[atoi(t[1])] = atoi(t[2]);
    } else if (!strcmp(op, "update")) {
        el_update_textures();
        printf("  tex %s %s %s\n", tname(eLightFlareTextures[0]),
               tname(eLightFlareTextures[1]), tname(eLightFlareTextures[2]));
    } else if (!strcmp(op, "render")) {
        int k = atoi(t[1]);

        printf("  ret %d\n", el_render_light_flare(
            &view, k < 0 ? NULL : &flares[k], atoi(t[2]) ? &lw : NULL,
            hf(t[3])));
    } else if (!strcmp(op, "ingame")) {
        InGameFlag = atoi(t[1]);
    } else if (!strcmp(op, "packs")) {
        int next = 0, k;

        eLightFlarePackList.next = eLightFlarePackList.prev =
            &eLightFlarePackList;
        for (k = 0; k + 1 < n; k++) {
            eLightFlarePackHeader *h = &packs[k];
            bNode *list = &h->LightFlareList;
            int c = atoi(t[1 + k]);

            list->next = list->prev = list;
            for (i = 0; i < c; i++, next++) {
                bNode *f = &flares[next].Node;

                f->prev = list->prev;
                f->next = list;
                list->prev->next = f;
                list->prev = f;
            }
            h->Node.prev = eLightFlarePackList.prev;
            h->Node.next = &eLightFlarePackList;
            eLightFlarePackList.prev->next = &h->Node;
            eLightFlarePackList.prev = &h->Node;
        }
    } else if (!strcmp(op, "world")) {
        el_render_world_light_flares(&view);
    } else if (!strcmp(op, "table")) {
        for (i = 0; i < 9; i++) {
            const eLightFlarePart *p = &SingleLightFlareParameters[i];
            const float *f = &p->MinSize;
            int k;

            printf("  part %d", i);
            for (k = 0; k < 14; k++)
                printf(" %08x", fb(f[k]));
            printf(" %d\n", (int)p->Texture);
        }
        for (i = 0; i < NUM_LIGHT_FLARE_TYPES; i++)
            printf("  type %d %d %d\n", i,
                   part_index(LightFlareParameterIndicies[i][0]),
                   part_index(LightFlareParameterIndicies[i][1]));
    } else {
        fprintf(stderr, "no op %s\n", op);
        exit(3);
    }
}

int main(int argc, char **argv)
{
    static char line[4096];
    char *t[MAXT];
    FILE *f;

    if (argc != 2) {
        fprintf(stderr, "usage: lightflare_test script\n");
        return 2;
    }
    f = fopen(argv[1], "r");
    if (f == NULL) {
        perror(argv[1]);
        return 2;
    }
    eMathInit();
    gEPolyRender3DFn = render3d;
    view.pCamera = &cam;
    view.WorldViewMatrix = &wv;
    view.WorldClipMatrix = &wc;
    while (fgets(line, sizeof line, f) != NULL) {
        char *e = line + strlen(line);
        int n;

        while (e > line && (e[-1] == '\n' || e[-1] == '\r'))
            *--e = 0;
        if (line[0] == 0)
            continue;
        n = split(line, t);
        run(t, n);
    }
    fclose(f);
    return 0;
}
