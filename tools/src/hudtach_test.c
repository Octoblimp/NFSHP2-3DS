// Drives hudtach.c for tools/hudtach_check.py: InitializeFlailerTachometer
// and RenderFlailerTachometer on one FlailerBitmapChunk and two point
// lists. A script of ops, one per line, fields split on '|'; numbers are C
// literals, floats their bits:
//
//   b|OFF|V        the bitmap's word at OFF
//   byte|OFF|V     the bitmap's byte at OFF
//   tex|W|H        the texture's Width and Height, the halfwords at 36
//                  and 38 of its TextureInfo
//   init|L         Init on list L (0 or 1)
//   render|L       Render with list L, or - for none
//   draw           Render with the list the word at 108 names, as
//                  RenderSingleFlailerBitmap calls it
//
// Before each Render the pool's polys are filled with a pattern and
// constructed, and AddPoly hands them out in order, and NULL past the
// 27th, where the model stops retail. After each op: the
// lists and the bitmap when they changed, and each poly handed out. The
// size seam and AddPoly log their calls.
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "epoly.h"
#include "flailer.h"
#include "hudtach.h"

#define NUM_ARGS  8
#define POOL      27
#define LINE_MAX_ 2048

bool (*gFlailerBitmapTextureSizeFn)(struct FlailerBitmapChunk *b,
                                    int32_t *w, int32_t *h);

static struct FlailerBitmapChunk  bitmap;
static FlailerTachometerPointList lists[2];
static ePoly   pool[POOL];
static int     handed;
static int16_t texW, texH;

static char lastList[2][LINE_MAX_];
static char lastBitmap[LINE_MAX_];

// The word a fresh block holds at offset o, as the model's.
static uint32_t pattern(uint32_t o)
{
    return 0x3f800000u + o * 16u;
}

static uint8_t pool_pattern(int k, int o)
{
    return (uint8_t)(k * 37 + o * 13 + 0x5a);
}

// ------------------------------------------------------------- the seams

static bool texture_size(struct FlailerBitmapChunk *b, int32_t *w, int32_t *h)
{
    printf("  texinfo %08x\n", (unsigned)b->TextureHash);
    *w = texW;
    *h = texH;
    return true;
}

static ePoly *add_poly(void *ctx)
{
    (void)ctx;
    if (handed >= POOL) {
        printf("  addpoly full\n");
        return NULL;
    }
    printf("  addpoly %d\n", handed);
    return &pool[handed++];
}

// -------------------------------------------------------------- the dump

static void hex(char *out, const void *p, size_t n)
{
    const uint8_t *b = (const uint8_t *)p;
    size_t i;

    for (i = 0; i < n; i++)
        sprintf(out + 2 * i, "%02x", b[i]);
    out[2 * n] = 0;
}

static const char *list_name(void)
{
    static char buf[32];
    FlailerTachometerPointList *l;

    if (bitmap.pTachPointList == 0) return "none";
    l = hudtach_points(&bitmap);
    if (l == &lists[0]) return "L0";
    if (l == &lists[1]) return "L1";
    sprintf(buf, "tok%08x", (unsigned)bitmap.pTachPointList);
    return buf;
}

static void dump(void)
{
    char line[LINE_MAX_];
    struct FlailerBitmapChunk b;
    int k;

    for (k = 0; k < 2; k++) {
        hex(line, &lists[k], sizeof lists[k]);
        if (strcmp(line, lastList[k]) != 0) {
            strcpy(lastList[k], line);
            printf("  list%d %s\n", k, line);
        }
    }
    b = bitmap;
    b.pTachPointList = 0;
    hex(line, &b, sizeof b);
    strcat(line, " list ");
    strcat(line, list_name());
    if (strcmp(line, lastBitmap) != 0) {
        strcpy(lastBitmap, line);
        printf("  bmp %s\n", line);
    }
    for (k = 0; k < handed; k++) {
        hex(line, &pool[k], 156);
        printf("  poly %d %s %08x\n", k, line,
               (unsigned)(uintptr_t)pool[k].pDynamicFrameMemory);
    }
}

// --------------------------------------------------------------- the ops

static void fresh_pool(void)
{
    int k, o;

    for (k = 0; k < POOL; k++) {
        uint8_t *p = (uint8_t *)&pool[k];
        for (o = 0; o < 156; o++)
            p[o] = pool_pattern(k, o);
        pool[k].pDynamicFrameMemory = (void *)(uintptr_t)0x5a5a5a5au;
        epoly_init(&pool[k]);
    }
    handed = 0;
}

static uint32_t num(const char *s)
{
    return (uint32_t)strtoul(s, NULL, 0);
}

static void run(char *line)
{
    char *a[NUM_ARGS];
    int   n = 0;
    char *p = line;

    while (n < NUM_ARGS) {
        a[n++] = p;
        p = strchr(p, '|');
        if (!p) break;
        *p++ = 0;
    }
    handed = 0;
    if (!strcmp(a[0], "b")) {
        uint32_t v = num(a[2]);
        memcpy((uint8_t *)&bitmap + num(a[1]), &v, 4);
    } else if (!strcmp(a[0], "byte")) {
        ((uint8_t *)&bitmap)[num(a[1])] = (uint8_t)num(a[2]);
    } else if (!strcmp(a[0], "tex")) {
        texW = (int16_t)num(a[1]);
        texH = (int16_t)num(a[2]);
    } else if (!strcmp(a[0], "init")) {
        flailer_initialize_tachometer(NULL, &bitmap.Object,
                                      &lists[num(a[1])]);
    } else if (!strcmp(a[0], "render")) {
        fresh_pool();
        flailer_render_tachometer(&bitmap,
                                  a[1][0] == '-' ? NULL : &lists[num(a[1])],
                                  add_poly, NULL);
    } else if (!strcmp(a[0], "draw")) {
        fresh_pool();
        flailer_render_tachometer(&bitmap, hudtach_points(&bitmap),
                                  add_poly, NULL);
    } else {
        printf("  bad op %s\n", a[0]);
    }
    dump();
}

int main(int argc, char **argv)
{
    static char line[4096];
    FILE       *f;
    uint32_t    o;
    int         k;

    if (argc < 2) return 2;
    f = fopen(argv[1], "r");
    if (!f) return 2;

    gFlailerBitmapTextureSizeFn = texture_size;
    for (o = 0; o < sizeof bitmap; o += 4) {
        uint32_t w = pattern(o);
        memcpy((uint8_t *)&bitmap + o, &w, 4);
    }
    // No list yet, and no TextureInfo: the port keeps none.
    bitmap.pTachPointList = 0;
    bitmap.pTextureInfo = 0;
    for (k = 0; k < 2; k++)
        for (o = 0; o < sizeof lists[k]; o += 4) {
            uint32_t w = pattern(o + 256 * (uint32_t)k);
            memcpy((uint8_t *)&lists[k] + o, &w, 4);
        }

    while (fgets(line, sizeof line, f)) {
        size_t n = strlen(line);
        while (n && (line[n - 1] == '\n' || line[n - 1] == '\r'))
            line[--n] = 0;
        if (!n) continue;
        printf("> %s\n", line);
        run(line);
    }
    fclose(f);
    return 0;
}
