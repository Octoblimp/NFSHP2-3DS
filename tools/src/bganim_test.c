// Drives bganim.c for tools/bganim_check.py. A script of ops, one per line,
// fields split on spaces, numbers in hex unless said:
//
//   O s mask          screen s's objects: 1 GRID, 2 MASTER_BP_OBJECT,
//                     4 FADING_BP_OBJECT, all bitmaps
//   S seed            bDefaultSeed
//   I                 the constructor
//   C s timer         ChangeScreenHash(s), RealTimer `timer` (decimal)
//   R timer           Reset
//   T timer elapsed   Tick; RealTimeElapsed is `elapsed`'s bits
//   A h / X h         the kept list's Add and Remove
//   N                 its Count
//   n i               its Nth (decimal, may be negative)
//   K                 its Reset
//   D                 the object, field by field
//
// The Flailer calls print what they were asked, as the model's stubs do.
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bchunk.h"
#include "bganim.h"
#include "bmath.h"
#include "flailer.h"

#define MAX_SCREENS 16

// Three objects a screen; their index is screen * 3 + 0, 1 or 2.
static uint8_t  objects[MAX_SCREENS * 3][64];
static uint32_t screens[MAX_SCREENS];
static int      masks[MAX_SCREENS];
static int      numScreens;
static BgAnim   anim;

static uint32_t fbits(float f)
{
    uint32_t u;
    memcpy(&u, &f, 4);
    return u;
}

static float bitsf(uint32_t u)
{
    float f;
    memcpy(&f, &u, 4);
    return f;
}

static int index_of(const void* p)
{
    if (!p) return -1;
    return (int)(((const uint8_t*)p - &objects[0][0]) / 64);
}

struct FlailerObjectChunk* flailer_find_object(uint32_t screen,
                                               uint32_t object, int32_t type)
{
    static const char* const names[3] = {
        "GRID", "MASTER_BP_OBJECT", "FADING_BP_OBJECT"
    };
    int found = -1;
    for (int s = 0; s < numScreens && found < 0; s++) {
        if (screens[s] != screen) continue;
        for (int k = 0; k < 3; k++)
            if ((masks[s] >> k & 1) && type == FLAILER_TYPE_BITMAP
                && bchunk_hash(names[k]) == object)
                found = s * 3 + k;
    }
    printf("find s=%08x o=%08x t=%d -> %d\n", (unsigned)screen,
           (unsigned)object, (int)type, found);
    return found < 0 ? NULL : (struct FlailerObjectChunk*)objects[found];
}

void flailerbitmap_set_alpha(struct FlailerBitmapChunk* b, int32_t a,
                             int32_t corner)
{
    printf("alpha o=%d a=%d c=%d\n", index_of(b), (int)a, (int)corner);
}

void flailerobject_set_center_x(struct FlailerObjectChunk* o, float x)
{
    printf("cx o=%d %08x\n", index_of(o), (unsigned)fbits(x));
}

void flailerobject_set_center_y(struct FlailerObjectChunk* o, float y)
{
    printf("cy o=%d %08x\n", index_of(o), (unsigned)fbits(y));
}

void flailerbitmap_change_texture(struct FlailerBitmapChunk* b,
                                  uint32_t texture)
{
    printf("tex o=%d %08x\n", index_of(b), (unsigned)texture);
}

static void dump_lane(const BSpline* s)
{
    printf(" [%08x %08x %08x %08x %08x %08x %08x %08x %08x %08x %08x %d %d]",
           (unsigned)fbits(s->val), (unsigned)fbits(s->dval),
           (unsigned)fbits(s->valDesired), (unsigned)fbits(s->dvalDesired),
           (unsigned)fbits(s->coeff[0]), (unsigned)fbits(s->coeff[1]),
           (unsigned)fbits(s->coeff[2]), (unsigned)fbits(s->coeff[3]),
           (unsigned)fbits(s->time), (unsigned)fbits(s->duration),
           (unsigned)fbits(s->arrivalThreshold), (int)s->state,
           (int)s->flags);
}

static void dump(void)
{
    printf("D h=%08x g=%d m=%d f=%d", (unsigned)anim.screenHash,
           index_of(anim.grid), index_of(anim.master),
           index_of(anim.fading));
    dump_lane(&anim.spline.x);
    dump_lane(&anim.spline.y);
    printf(" cf=%d gt=%d p=%08x k=", (int)anim.crossFadeTimer,
           (int)anim.gridTimer, (unsigned)fbits(anim.animParam));
    for (int i = 0; i < 8; i++)
        printf("%s%08x", i ? "," : "", (unsigned)anim.kept[i]);
    printf(" seed=%08x\n", (unsigned)bDefaultSeed);
}

int main(int argc, char** argv)
{
    FILE* f;
    char  line[256];

    if (argc < 2 || !(f = fopen(argv[1], "r"))) {
        fprintf(stderr, "usage: bganim_test script\n");
        return 2;
    }
    while (fgets(line, sizeof line, f)) {
        char     op = line[0];
        uint32_t a = 0, b = 0;
        long     t = 0;
        switch (op) {
        case 'O':
            sscanf(line + 1, "%x %x", &a, &b);
            if (numScreens < MAX_SCREENS) {
                screens[numScreens] = a;
                masks[numScreens++] = (int)b;
            }
            break;
        case 'S':
            sscanf(line + 1, "%x", &a);
            bDefaultSeed = a;
            break;
        case 'I':
            bganim_init(&anim);
            break;
        case 'C':
            sscanf(line + 1, "%x %ld", &a, &t);
            bganim_change_screen_hash(&anim, a, (int32_t)t);
            break;
        case 'R':
            sscanf(line + 1, "%ld", &t);
            bganim_reset(&anim, (int32_t)t);
            break;
        case 'T':
            sscanf(line + 1, "%ld %x", &t, &b);
            bganim_tick(&anim, (int32_t)t, bitsf(b));
            break;
        case 'A':
            sscanf(line + 1, "%x", &a);
            bganim_keep_add(&anim, a);
            break;
        case 'X':
            sscanf(line + 1, "%x", &a);
            bganim_keep_remove(&anim, a);
            break;
        case 'N':
            printf("N %d\n", bganim_keep_count(&anim));
            break;
        case 'n':
            sscanf(line + 1, "%ld", &t);
            printf("n %ld %08x\n", t,
                   (unsigned)bganim_keep_nth(&anim, (int)t));
            break;
        case 'K':
            bganim_keep_reset(&anim);
            break;
        case 'D':
            dump();
            break;
        default:
            break;
        }
    }
    fclose(f);
    return 0;
}
