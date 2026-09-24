// Harness for tools/average_check.py: runs the checker's op script on the
// port and prints what the model prints for the image. The ops, their
// arguments and every line's format are the checker's; this file only
// carries them out.
//
//     average_test ops.bin > out.txt

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "average.h"
#include "bmem.h"

enum {
    OP_TAG, OP_NEW, OP_DEL, OP_REC, OP_RESET, OP_FLUSH, OP_POKE, OP_DPOKE,
    OP_DUMP, OP_PNEW, OP_PDEL, OP_PREC, OP_PRESET, OP_PDUMP, OP_LINIT,
    OP_LGET, OP_JUNK, OP_PJUNK
};

enum { F_SLOTS, F_CUR, F_N, F_TOTAL, F_AVG };

#define NAVG      8
#define NPID      4
#define SLACK     16        // 0xcd bytes past every block, both sides
#define MAX_HEAP  1024
#define MAX_DUMP  64

static Average  avgs[NAVG];
static PidError pids[NPID];
static Linear   line;

// ------------------------------------------------------------- the heap

static struct {
    const void *p;
    size_t      span;
} heap[MAX_HEAP];
static int nheap;

static void *malloc_hook(int size, const char *name, int flags, int pool)
{
    size_t span = (size > 0 ? (size_t)size : 0) + SLACK;
    void  *p = malloc(span);

    if (nheap >= MAX_HEAP) {
        fprintf(stderr, "heap log full\n");
        exit(3);
    }
    // Fresh blocks are 0xcd on both sides, so the constructor's clear
    // shows, and the slack past the end is the same junk to either.
    memset(p, 0xcd, span);
    heap[nheap].p = p;
    heap[nheap].span = span;
    printf("  alloc h%d size %d name %s flags %d pool %d\n", nheap, size,
           name, flags, pool);
    nheap++;
    return p;
}

static void label(char *buf, size_t n, const void *a)
{
    const char *b = (const char *)a;
    int i;

    if (a == NULL) {
        snprintf(buf, n, "null");
        return;
    }
    for (i = 0; i < NAVG; i++)
        if (a == (const void *)&avgs[i]) {
            snprintf(buf, n, "a%d", i);
            return;
        }
    for (i = 0; i < NPID; i++) {
        if (a == (const void *)&pids[i]) {
            snprintf(buf, n, "p%d", i);
            return;
        }
        if (a == (const void *)&pids[i].aDerivative) {
            snprintf(buf, n, "p%d.d", i);
            return;
        }
    }
    for (i = 0; i < nheap; i++) {
        const char *p = (const char *)heap[i].p;
        if (b >= p && b < p + heap[i].span) {
            if (b == p)
                snprintf(buf, n, "h%d", i);
            else
                snprintf(buf, n, "h%d+%d", i, (int)(b - p));
            return;
        }
    }
    snprintf(buf, n, "?");
}

// Logged, never freed, so no address is handed out twice.
static void free_hook(void *p)
{
    char b[48];

    label(b, sizeof b, p);
    printf("  free %s\n", b);
}

// ------------------------------------------------------------- the script

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

static float nextf(void)
{
    int32_t w = next();
    float   f;

    memcpy(&f, &w, 4);
    return f;
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

    memcpy(&u, &f, 4);
    return u;
}

// ------------------------------------------------------------- the prints

static void dump(const char *name, const Average *a)
{
    char    b[48];
    int32_t i, k;

    label(b, sizeof b, a->pData);
    printf("%s slots %d cur %d n %d total %08x avg %08x data %s\n", name,
           a->nSlots, a->nCurrentSlot, a->nSamples,
           (unsigned)fbits(a->fTotal), (unsigned)fbits(a->fAverage), b);
    // The ring and the slack word after it, eight to a line.
    k = a->nSlots + 1;
    if (k > MAX_DUMP)
        k = MAX_DUMP;
    for (i = 0; i < k; i += 8) {
        int32_t j;
        printf("  d%d", i);
        for (j = i; j < i + 8 && j < k; j++)
            printf(" %08x", (unsigned)fbits(a->pData[j]));
        printf("\n");
    }
}

static void pdump(int slot)
{
    char n[16];
    const PidError *p = &pids[slot];

    printf("p%d err %08x prev %08x\n", slot,
           (unsigned)fbits(p->fCurrentError),
           (unsigned)fbits(p->fPreviousError));
    snprintf(n, sizeof n, "p%d.i", slot);
    dump(n, &p->aIntegral);
    snprintf(n, sizeof n, "p%d.d", slot);
    dump(n, &p->aDerivative);
}

static void junk(Average *a, int32_t seed)
{
    uint32_t u = 0x7f000000u | (uint32_t)seed;
    float    f;

    a->nSlots = 0x1111 + seed;
    a->nCurrentSlot = 0x2222 + seed;
    a->nSamples = 0x3333 + seed;
    memcpy(&f, &u, 4);
    a->fTotal = f;
    u ^= 0x00400000u;
    memcpy(&f, &u, 4);
    a->fAverage = f;
    a->pData = NULL;
}

int main(int argc, char **argv)
{
    FILE    *fh;
    long     size;
    char   **tags;
    int32_t  ntags;
    size_t   end;

    if (argc < 2) {
        fprintf(stderr, "usage: average_test ops.bin\n");
        return 2;
    }
    fh = fopen(argv[1], "rb");
    if (fh == NULL) {
        perror(argv[1]);
        return 2;
    }
    fseek(fh, 0, SEEK_END);
    size = ftell(fh);
    fseek(fh, 0, SEEK_SET);
    words_in = malloc((size_t)size);
    nwords_in = (size_t)size / 4;
    if (fread(words_in, 4, nwords_in, fh) != nwords_in) {
        fprintf(stderr, "short read\n");
        return 2;
    }
    fclose(fh);

    tags = read_strings(&ntags);
    end = (size_t)next();
    end += rd;

    bSetMemoryHooks(malloc_hook, free_hook);

    while (rd < end) {
        int32_t op = next();

        switch (op) {
        case OP_TAG:
            printf("[%s]\n", tags[next()]);
            break;
        case OP_NEW: {
            int32_t slot = next(), n = next();
            Average *r = average_init(&avgs[slot], n);
            char b[48];
            label(b, sizeof b, r);
            printf("new a%d %d -> %s\n", slot, n, b);
            break;
        }
        case OP_DEL: {
            int32_t slot = next(), flags = next();
            printf("del a%d %d\n", slot, flags);
            average_destroy(&avgs[slot], flags);
            break;
        }
        case OP_REC: {
            int32_t slot = next();
            float   v = nextf();
            printf("rec a%d %08x\n", slot, (unsigned)fbits(v));
            average_record(&avgs[slot], v);
            break;
        }
        case OP_RESET: {
            int32_t slot = next();
            float   v = nextf();
            printf("reset a%d %08x\n", slot, (unsigned)fbits(v));
            average_reset(&avgs[slot], v);
            break;
        }
        case OP_FLUSH: {
            int32_t slot = next();
            float   v = nextf();
            printf("flush a%d %08x\n", slot, (unsigned)fbits(v));
            average_flush(&avgs[slot], v);
            break;
        }
        case OP_POKE: {
            int32_t slot = next(), f = next(), v = next();
            Average *a = &avgs[slot];
            switch (f) {
            case F_SLOTS: a->nSlots = v; break;
            case F_CUR:   a->nCurrentSlot = v; break;
            case F_N:     a->nSamples = v; break;
            case F_TOTAL: memcpy(&a->fTotal, &v, 4); break;
            case F_AVG:   memcpy(&a->fAverage, &v, 4); break;
            }
            break;
        }
        case OP_DPOKE: {
            int32_t slot = next(), i = next(), v = next();
            memcpy(&avgs[slot].pData[i], &v, 4);
            break;
        }
        case OP_DUMP: {
            int32_t slot = next();
            char    n[8];
            snprintf(n, sizeof n, "a%d", slot);
            dump(n, &avgs[slot]);
            printf("value %08x total %08x\n",
                   (unsigned)fbits(average_get_value(&avgs[slot])),
                   (unsigned)fbits(average_get_total(&avgs[slot])));
            break;
        }
        case OP_PNEW: {
            int32_t slot = next(), ni = next(), nd = next();
            PidError *r = pid_error_init(&pids[slot], ni, nd);
            char b[48];
            label(b, sizeof b, r);
            printf("pnew p%d %d %d -> %s\n", slot, ni, nd, b);
            break;
        }
        case OP_PDEL: {
            int32_t slot = next(), flags = next();
            printf("pdel p%d %d\n", slot, flags);
            pid_error_destroy(&pids[slot], flags);
            break;
        }
        case OP_PREC: {
            int32_t slot = next();
            float   err = nextf(), dt = nextf();
            printf("prec p%d %08x %08x\n", slot, (unsigned)fbits(err),
                   (unsigned)fbits(dt));
            pid_error_record(&pids[slot], err, dt);
            break;
        }
        case OP_PRESET: {
            int32_t slot = next();
            float   err = nextf();
            printf("preset p%d %08x\n", slot, (unsigned)fbits(err));
            pid_error_reset(&pids[slot], err);
            break;
        }
        case OP_PDUMP:
            pdump(next());
            break;
        case OP_LINIT: {
            float x1 = nextf(), y1 = nextf(), x2 = nextf(), y2 = nextf();
            linear_init(&line, x1, y1, x2, y2);
            printf("linit %08x %08x %08x %08x -> m %08x b %08x\n",
                   (unsigned)fbits(x1), (unsigned)fbits(y1),
                   (unsigned)fbits(x2), (unsigned)fbits(y2),
                   (unsigned)fbits(line.m), (unsigned)fbits(line.b));
            break;
        }
        case OP_LGET: {
            float x = nextf();
            printf("lget %08x -> %08x\n", (unsigned)fbits(x),
                   (unsigned)fbits(linear_get_value(&line, x)));
            break;
        }
        case OP_JUNK: {
            int32_t slot = next();
            junk(&avgs[slot], slot);
            break;
        }
        case OP_PJUNK: {
            int32_t slot = next();
            uint32_t u = 0x7e000000u | (uint32_t)slot;
            junk(&pids[slot].aIntegral, 16 + slot);
            junk(&pids[slot].aDerivative, 32 + slot);
            memcpy(&pids[slot].fCurrentError, &u, 4);
            u ^= 0x00200000u;
            memcpy(&pids[slot].fPreviousError, &u, 4);
            break;
        }
        default:
            fprintf(stderr, "bad op %d\n", op);
            return 2;
        }
    }
    return 0;
}
