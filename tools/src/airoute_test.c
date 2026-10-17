// Harness for tools/airoute_check.py: runs the checker's op script on the
// port and prints what the model prints for the image. The ops, their
// arguments and every line's format are the checker's; this file only
// carries them out. See the checker's docstring for the arena and the
// labels.
//
//     airoute_test ops.bin > out.txt

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "airoute.h"
#include "race.h"
#include "trackpath.h"
#include "trackroute.h"

// realtime.c's clock, which ReplaySnapshot_Init stamps; not linked here.
int32_t WorldTimer;
int32_t WorldLoopCounter;

enum {
    OP_TAG, OP_CLEAR, OP_WORDS, OP_ROUTE, OP_SIGNS, OP_NSIGNS, OP_RESET,
    OP_ADD, OP_LOADER, OP_LEN, OP_DIR, OP_INFO, OP_NEAREST, OP_NEXT,
    OP_AHEAD, OP_VALID
};

#define ARENA_SIZE  0x80000
#define NSIGNS      256
#define MAX_ROUTES  64
#define HDR         1064
#define PT          112

static _Alignas(16) uint8_t arena[ARENA_SIZE];
static Signpost              signs[NSIGNS];
static int32_t               route_off[MAX_ROUTES];
static NearestRoutePointInfo info;

// ------------------------------------------------------------ the script

static int32_t *words_in;
static size_t   nwords_in, rd;

static int32_t next(void)
{
    if (rd >= nwords_in) {
        fprintf(stderr, "script overrun\n");
        exit(2);
    }
    return words_in[rd++];
}

static char **read_strings(int32_t *count)
{
    int32_t n = next(), i, k;
    char  **out = malloc(sizeof(char *) * (size_t)(n > 0 ? n : 1));

    for (i = 0; i < n; i++) {
        int32_t len = next();
        out[i] = malloc((size_t)len + 1);
        for (k = 0; k < len; k++)
            out[i][k] = (char)next();
        out[i][len] = 0;
    }
    *count = n;
    return out;
}

static uint32_t fbits(float f)
{
    uint32_t u;

    memcpy(&u, &f, sizeof u);
    return u;
}

static float bitsf(int32_t b)
{
    float f;

    memcpy(&f, &b, sizeof f);
    return f;
}

static int32_t arena_i32(int32_t off)
{
    int32_t v;

    memcpy(&v, arena + off, sizeof v);
    return v;
}

// An arena offset, or -1 for NULL.
static void *ref(int32_t off)
{
    if (off < 0)
        return NULL;
    if (off >= ARENA_SIZE) {
        fprintf(stderr, "ref %d outside the arena\n", (int)off);
        exit(2);
    }
    return arena + off;
}

// ------------------------------------------------------------ the labels

// The first registered route whose base, or one of whose points, `a` is;
// otherwise the offset from the arena as a signed word, which is what the
// model prints for the same bytes.
static void label(char *buf, size_t n, const void *a)
{
    int32_t off;
    int     s;

    if (a == NULL) {
        snprintf(buf, n, "null");
        return;
    }
    off = (int32_t)(uint32_t)((uintptr_t)a - (uintptr_t)arena);
    for (s = 0; s < MAX_ROUTES; s++) {
        int32_t base = route_off[s], t, np;

        if (base < 0)
            continue;
        if (off == base) {
            snprintf(buf, n, "r%d", s);
            return;
        }
        t = base + HDR;
        np = arena_i32(base + 16);
        if (off >= t && np > 0 && off < t + PT * np && (off - t) % PT == 0) {
            snprintf(buf, n, "r%d.p%d", s, (int)((off - t) / PT));
            return;
        }
    }
    snprintf(buf, n, "a%+d", (int)off);
}

static void pinfo(char *buf, size_t n)
{
    char r[48], p[48];

    label(r, sizeof r, info.Route);
    label(p, sizeof p, info.Point);
    snprintf(buf, n, "%s %s", r, p);
}

// ------------------------------------------------------------------ main

int main(int argc, char **argv)
{
    FILE   *f;
    long    len;
    int32_t ntags, total, i;
    char  **tags;
    size_t  end;

    if (argc != 2) {
        fprintf(stderr, "usage: airoute_test ops.bin\n");
        return 2;
    }
    f = fopen(argv[1], "rb");
    if (!f) {
        perror(argv[1]);
        return 2;
    }
    fseek(f, 0, SEEK_END);
    len = ftell(f);
    fseek(f, 0, SEEK_SET);
    words_in = malloc((size_t)len);
    nwords_in = fread(words_in, 4, (size_t)len / 4, f);
    fclose(f);

    tags = read_strings(&ntags);
    total = next();
    end = rd + (size_t)total;
    for (i = 0; i < MAX_ROUTES; i++)
        route_off[i] = -1;
    SignpostArray = signs;
    NumSignposts = 0;

    while (rd < end) {
        int32_t code = next(), nargs = next();
        size_t  after = rd + (size_t)nargs;
        char    b0[100], b1[100];

        switch (code) {
        case OP_TAG:
            printf("[%s]\n", tags[next()]);
            break;
        case OP_CLEAR:
            memset(arena, 0, sizeof arena);
            for (i = 0; i < MAX_ROUTES; i++)
                route_off[i] = -1;
            break;
        case OP_WORDS: {
            int32_t off = next(), k;

            for (k = 0; k < nargs - 1; k++) {
                int32_t w = next();
                memcpy(arena + off + 4 * k, &w, 4);
            }
            break;
        }
        case OP_ROUTE: {
            int32_t slot = next();
            route_off[slot] = next();
            break;
        }
        case OP_SIGNS: {
            int32_t first = next(), k;

            for (k = 0; k < (nargs - 1) / 2; k++) {
                int32_t w[2];
                w[0] = next();
                w[1] = next();
                memcpy(&signs[first + k], w, 8);
            }
            break;
        }
        case OP_NSIGNS:
            NumSignposts = (uint32_t)next();
            break;
        case OP_RESET:
            printf("reset\n");
            trmgr_init(&TheTrackRouteManager);
            break;
        case OP_ADD: {
            TrackRoute *r = ref(next());

            label(b0, sizeof b0, r);
            printf("add %s\n", b0);
            trmgr_add_route_to_right_list(&TheTrackRouteManager, r);
            break;
        }
        case OP_LOADER:
            printf("loader\n");
            trmgr_loader(&TheTrackRouteManager, ref(next()));
            break;
        case OP_LEN:
            TheTrackPathManager.TrackLength = bitsf(next());
            break;
        case OP_DIR:
            RaceParametersTrackDirection = next();
            break;
        case OP_INFO:
            info.Route = ref(next());
            info.Point = ref(next());
            break;
        case OP_NEAREST: {
            bVector2 pos;
            int32_t  which, flags, around, r;

            pos.x = bitsf(next());
            pos.y = bitsf(next());
            which = next();
            flags = next();
            around = next();
            r = ai_get_nearest_route_point(&info, &pos, (RoutesToSearch)which,
                                           flags, bitsf(around));
            pinfo(b0, sizeof b0);
            printf("nearest %08x %08x which %d flags %d around %08x -> %d "
                   "%s\n", (unsigned)fbits(pos.x), (unsigned)fbits(pos.y),
                   (int)which, (int)flags, (unsigned)around, (int)r, b0);
            break;
        }
        case OP_NEXT:
        case OP_AHEAD:
            pinfo(b0, sizeof b0);
            if (code == OP_NEXT)
                ai_get_next_route_point(&info);
            else
                ai_get_next_route_point_ahead(&info);
            pinfo(b1, sizeof b1);
            printf("%s %s -> %s\n", code == OP_NEXT ? "next" : "ahead", b0,
                   b1);
            break;
        case OP_VALID:
            pinfo(b0, sizeof b0);
            printf("valid %s -> %d\n", b0, nrpi_is_valid(&info));
            break;
        default:
            fprintf(stderr, "op %d\n", (int)code);
            return 2;
        }
        if (rd != after) {
            fprintf(stderr, "op %d read %d of %d args\n", (int)code,
                    (int)(rd - (after - (size_t)nargs)), (int)nargs);
            return 2;
        }
    }
    return 0;
}
