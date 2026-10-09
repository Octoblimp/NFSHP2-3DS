// positionmarker_test -- tools/positionmarker_check.py's harness.
//
// Runs epositionmarker.c over the checker's script and prints what the
// model prints for the image. The script lays each chunk out as the disc
// does; this host has 8-byte pointers, so its records are rebuilt here at
// the host's size, after the same pad, and the size word says the same
// count of them. A record prints as kK.I (chunk K's I-th), the list's
// head as H, NULL as 0 and anything else as ?.
//
//     positionmarker_test script.txt > out.txt

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "epositionmarker.h"

#define NCHUNK 64
#define MAXT   16

static uint8_t         *cp[NCHUNK];     // the chunk
static ePositionMarker *recs[NCHUNK];   // its first record
static int              nrec[NCHUNK];   // how many the script built

static int total(void)
{
    int k, n = 0;

    for (k = 0; k < NCHUNK; k++)
        n += nrec[k];
    return n;
}

static const char *label(const void *p)
{
    static char buf[8][24];
    static int  b;
    char       *s = buf[b++ & 7];
    int         k;

    if (p == NULL)
        return "0";
    if (p == &PositionMarkerList)
        return "H";
    for (k = 0; k < NCHUNK; k++) {
        uintptr_t a = (uintptr_t)p, r = (uintptr_t)recs[k];

        if (cp[k] != NULL && a >= r
            && a < r + (uintptr_t)nrec[k] * sizeof(ePositionMarker)
            && (a - r) % sizeof(ePositionMarker) == 0) {
            snprintf(s, 24, "k%d.%d", k,
                     (int)((a - r) / sizeof(ePositionMarker)));
            return s;
        }
    }
    return "?";
}

// The list both ways, stopping at anything that is not a record.
static void dump(void)
{
    int    limit = total() + 2, steps;
    bNode *n;

    printf("  list");
    for (n = PositionMarkerList.next, steps = 0;
         n != &PositionMarkerList && steps < limit; n = n->next, steps++) {
        const char *l = label(n);

        printf(" %s", l);
        if (strcmp(l, "?") == 0 || strcmp(l, "0") == 0)
            break;
    }
    printf("\n  back");
    for (n = PositionMarkerList.prev, steps = 0;
         n != &PositionMarkerList && steps < limit; n = n->prev, steps++) {
        const char *l = label(n);

        printf(" %s", l);
        if (strcmp(l, "?") == 0 || strcmp(l, "0") == 0)
            break;
    }
    printf("\n");
}

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

static int split(char *line, char **t)
{
    int   n = 0;
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

static uint32_t hx(const char *s)
{
    return (uint32_t)strtoll(s, NULL, 0);
}

static int ix(const char *s)
{
    return (int)strtol(s, NULL, 0);
}

// chunk|k|mis|type|n|rem|fill: chunk k at mis past a 16-byte boundary,
// its pad, n records and rem bytes more, all of byte fill.
static void make_chunk(int k, int mis, uint32_t type, int n, int rem, int fill)
{
    size_t   bytes = 64 + (size_t)n * sizeof(ePositionMarker) + (size_t)rem;
    uint8_t *raw = malloc(bytes + 64);
    uint8_t *c = (uint8_t *)(((uintptr_t)raw + 15u) & ~(uintptr_t)15u) + mis;
    uint8_t *data = (uint8_t *)(((uintptr_t)c + 23u) & ~(uintptr_t)15u);
    uint32_t size = (uint32_t)(data - (c + 8))
                    + (uint32_t)((size_t)n * sizeof(ePositionMarker))
                    + (uint32_t)rem;

    memset(raw, fill, bytes + 64);
    memcpy(c, &type, 4);
    memcpy(c + 4, &size, 4);
    cp[k] = c;                      // the old one is kept, so no address
    recs[k] = (ePositionMarker *)(void *)data;      // is handed out twice
    nrec[k] = n;
}

static void fields(int k)
{
    int i;

    for (i = 0; i < nrec[k]; i++) {
        const ePositionMarker *m = &recs[k][i];

        printf("  k%d.%d %08x %08x %08x %08x %08x %08x\n", k, i,
               (unsigned)m->NameHash, (unsigned)m->TypeHash,
               (unsigned)fb(m->Position[0]), (unsigned)fb(m->Position[1]),
               (unsigned)fb(m->Position[2]), (unsigned)m->Param);
    }
}

static ePositionMarker *parse_label(const char *s)
{
    int k, i;

    if (strcmp(s, "0") == 0)
        return NULL;
    if (sscanf(s, "k%d.%d", &k, &i) != 2 || k < 0 || k >= NCHUNK
        || i < 0 || i >= nrec[k]) {
        fprintf(stderr, "bad label %s\n", s);
        exit(2);
    }
    return &recs[k][i];
}

static void run(char **t, int n)
{
    const char *o = t[0];

    if (strcmp(o, "reset") == 0) {
        PositionMarkerList.next = &PositionMarkerList;
        PositionMarkerList.prev = &PositionMarkerList;
        memset(cp, 0, sizeof cp);
        memset(nrec, 0, sizeof nrec);
        printf("reset\n");
    } else if (strcmp(o, "chunk") == 0) {
        make_chunk(ix(t[1]), ix(t[2]), hx(t[3]), ix(t[4]), ix(t[5]),
                   ix(t[6]));
    } else if (strcmp(o, "rec") == 0) {
        ePositionMarker *m = &recs[ix(t[1])][ix(t[2])];

        // t[3], t[4]: the disc's node words, which a host record cannot
        // hold; the loader writes both before anything reads them.
        m->NameHash = hx(t[5]);
        m->TypeHash = hx(t[6]);
        m->Position[0] = bf(hx(t[7]));
        m->Position[1] = bf(hx(t[8]));
        m->Position[2] = bf(hx(t[9]));
        m->Param = hx(t[10]);
    } else if (strcmp(o, "load") == 0 || strcmp(o, "unload") == 0) {
        int k = ix(t[1]);
        int r = o[0] == 'l' ? loader_position_markers(cp[k])
                            : unloader_position_markers(cp[k]);

        printf("%s k%d -> %d\n", o, k, r);
        dump();
    } else if (strcmp(o, "dump") == 0) {
        printf("dump\n");
        dump();
    } else if (strcmp(o, "fields") == 0) {
        printf("fields k%d\n", ix(t[1]));
        fields(ix(t[1]));
    } else if (strcmp(o, "find") == 0) {
        ePositionMarker *r =
            eFindPositionMarker(hx(t[1]), hx(t[2]), parse_label(t[3]));

        printf("find %s %s %s -> %s\n", t[1], t[2], t[3], label(r));
    } else {
        fprintf(stderr, "unknown op %s\n", o);
        exit(2);
    }
    (void)n;
}

int main(int argc, char **argv)
{
    static char line[4096];
    char       *t[MAXT];
    FILE       *f;

    if (argc != 2) {
        fprintf(stderr, "usage: positionmarker_test script\n");
        return 2;
    }
    f = fopen(argv[1], "r");
    if (f == NULL) {
        perror(argv[1]);
        return 2;
    }
    while (fgets(line, sizeof line, f) != NULL) {
        char *e = line + strlen(line);

        while (e > line && (e[-1] == '\n' || e[-1] == '\r'))
            *--e = 0;
        if (line[0] == 0)
            continue;
        run(t, split(line, t));
    }
    fclose(f);
    return 0;
}
