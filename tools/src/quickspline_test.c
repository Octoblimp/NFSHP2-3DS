// Harness for tools/quickspline_check.py: runs the checker's op script on
// the port and prints what the model prints for the image. The ops, their
// arguments and every line's format are the checker's; this file only
// carries them out. See the checker's docstring for the heap labels and the
// slack vector.
//
//     quickspline_test ops.bin > out.txt

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bmem.h"
#include "quickspline.h"

// realtime.c's clock, which ReplaySnapshot_Init stamps; not linked here.
int32_t WorldTimer;
int32_t WorldLoopCounter;

enum {
    OP_TAG, OP_NEW, OP_NEWBUF, OP_DESTROY, OP_SETUP, OP_SETN, OP_POKE, OP_CP,
    OP_DUMP, OP_BASIS, OP_BASISFLAG, OP_BASISPOKE, OP_INITBASIS, OP_FIXUP,
    OP_CLAMP, OP_GENEX, OP_EVAL, OP_GETPOINT, OP_FCCP, OP_FCCPALL, OP_FCP,
    OP_CAL, OP_CONST
};

enum {
    K_EPT, K_BT, K_MAX, K_MIN, K_LEN, K_DIRTY, K_ALLOC, K_MINC, K_MAXC, K_N,
    K_BUFNULL
};

#define EXT_N     256
#define SLACK     16        // the port's extra vector, in bytes
#define MAX_DUMP  80
#define MAX_HEAP  4096

static QuickSpline spl[2];
static bVector4    ext[2][EXT_N];

// ------------------------------------------------------------- the heap

static struct {
    const void *p;
    int         size;       // what the image would have asked for
} heap[MAX_HEAP];
static int nheap;

static void *malloc_hook(int size, const char *name, int flags, int pool)
{
    void *p = malloc((size_t)size);

    if (nheap >= MAX_HEAP) {
        fprintf(stderr, "heap log full\n");
        exit(3);
    }
    heap[nheap].p = p;
    heap[nheap].size = size - SLACK;
    printf("  alloc h%d size %d name %s flags %d pool %d\n", nheap,
           size - SLACK, name, flags, pool);
    nheap++;
    return p;
}

static void label(char *buf, size_t n, const void *a);

// Logged, never freed: the splines themselves are statics, and a buffer
// freed here would let malloc hand its address to the next one.
static void free_hook(void *p)
{
    char b[48];

    label(b, sizeof b, p);
    printf("  free %s\n", b);
}

static void label(char *buf, size_t n, const void *a)
{
    const char *base = (const char *)a;
    struct { const void *p; size_t size; char name[16]; } r[8];
    int nr = 0, i;

    if (a == NULL) {
        snprintf(buf, n, "null");
        return;
    }
    r[nr].p = &spl[0]; r[nr].size = sizeof spl[0];
    snprintf(r[nr++].name, 16, "s0");
    r[nr].p = &spl[1]; r[nr].size = sizeof spl[1];
    snprintf(r[nr++].name, 16, "s1");
    r[nr].p = ext[0]; r[nr].size = sizeof ext[0];
    snprintf(r[nr++].name, 16, "e0");
    r[nr].p = ext[1]; r[nr].size = sizeof ext[1];
    snprintf(r[nr++].name, 16, "e1");
    r[nr].p = QuickSplineBasisMatricies;
    r[nr].size = sizeof QuickSplineBasisMatricies;
    snprintf(r[nr++].name, 16, "basis");

    for (i = 0; i < nr; i++) {
        const char *p = (const char *)r[i].p;
        if (base >= p && base < p + r[i].size) {
            if (base == p)
                snprintf(buf, n, "%s", r[i].name);
            else
                snprintf(buf, n, "%s+%d", r[i].name, (int)(base - p));
            return;
        }
    }
    for (i = 0; i < nheap; i++) {
        const char *p = (const char *)heap[i].p;
        if (base >= p && base < p + heap[i].size + SLACK) {
            if (base == p)
                snprintf(buf, n, "h%d", i);
            else
                snprintf(buf, n, "h%d+%d", i, (int)(base - p));
            return;
        }
    }
    snprintf(buf, n, "?");
}

static int is_heap(const void *a)
{
    int i;

    for (i = 0; i < nheap; i++)
        if (heap[i].p == a)
            return 1;
    return 0;
}

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

// ------------------------------------------------------------ the prints

static void pvec(const char *pre, const bVector4 *v)
{
    printf("%s%08x %08x %08x %08x", pre, (unsigned)fbits(v->x),
           (unsigned)fbits(v->y), (unsigned)fbits(v->z),
           (unsigned)fbits(v->w));
}

static void dump(int slot, int withbuf)
{
    QuickSpline *s = &spl[slot];
    char b0[48], b1[48], b2[48];
    int  i, cnt;

    label(b0, sizeof b0, s->pControlPointBuffer);
    label(b1, sizeof b1, s->pControlPoints);
    label(b2, sizeof b2, s->pBasisMatricies);
    printf("s%d ept %d bt %d max %08x min %08x len %08x dirty %d alloc %d "
           "minc %d maxc %d n %d buf %s cp %s basis %s\n",
           slot, (int)s->EndPointType, (int)s->BasisType,
           (unsigned)fbits(s->MaxParam), (unsigned)fbits(s->MinParam),
           (unsigned)fbits(s->Length), s->ControlPointsDirty,
           s->BufferWasAllocated, s->MinControlPoints, s->MaxControlPoints,
           s->NumControlPoints, b0, b1, b2);
    if (!withbuf)
        return;
    cnt = s->MaxControlPoints + 3;
    if (cnt > MAX_DUMP)
        cnt = MAX_DUMP;
    for (i = 0; i < cnt; i++) {
        char pre[16];
        snprintf(pre, sizeof pre, "  b%d ", i);
        pvec(pre, &s->pControlPointBuffer[i]);
        printf("\n");
    }
    if (is_heap(s->pControlPointBuffer)) {
        pvec("  slack ", &s->pControlPointBuffer[s->MaxControlPoints + 3]);
        printf("\n");
    }
}

static void basis(void)
{
    int k, r;

    printf("basis done %d\n", (int)QuickSplineBasisMatrixInitDone);
    for (k = 0; k < 3; k++) {
        const bVector4 *row = &QuickSplineBasisMatricies[k].v0;
        for (r = 0; r < 4; r++) {
            char pre[16];
            snprintf(pre, sizeof pre, "  m%d r%d ", k, r);
            pvec(pre, &row[r]);
            printf("\n");
        }
    }
}

static void poke(QuickSpline *s, int k, int32_t v)
{
    switch (k) {
    case K_EPT:     s->EndPointType = v; break;
    case K_BT:      s->BasisType = v; break;
    case K_MAX:     s->MaxParam = bitsf(v); break;
    case K_MIN:     s->MinParam = bitsf(v); break;
    case K_LEN:     s->Length = bitsf(v); break;
    case K_DIRTY:   s->ControlPointsDirty = (int8_t)v; break;
    case K_ALLOC:   s->BufferWasAllocated = (int8_t)v; break;
    case K_MINC:    s->MinControlPoints = (int8_t)v; break;
    case K_MAXC:    s->MaxControlPoints = (uint16_t)v; break;
    case K_N:       s->NumControlPoints = (uint16_t)v; break;
    case K_BUFNULL: s->pControlPointBuffer = NULL; break;
    default:
        fprintf(stderr, "poke %d\n", k);
        exit(2);
    }
}

static void put_pt(bVector3 *p, int32_t x, int32_t y, int32_t z)
{
    p->x = bitsf(x);
    p->y = bitsf(y);
    p->z = bitsf(z);
    p->pad = 0.0f;
}

int main(int argc, char **argv)
{
    FILE    *fh;
    long     size;
    char   **tags;
    int32_t  ntags;
    size_t   end;
    bVector4 out[4];

    if (argc < 2) {
        fprintf(stderr, "usage: quickspline_test ops.bin\n");
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
    memset(spl, 0x55, sizeof spl);

    while (rd < end) {
        int32_t op = next();

        switch (op) {
        case OP_TAG:
            printf("[%s]\n", tags[next()]);
            break;
        case OP_NEW: {
            int32_t slot = next(), ept = next(), bt = next(), n = next();
            printf("new s%d ept %d bt %d n %d\n", slot, ept, bt, n);
            quickspline_init(&spl[slot], ept, bt, n);
            break;
        }
        case OP_NEWBUF: {
            int32_t slot = next(), ept = next(), bt = next(), n = next();
            printf("newbuf s%d ept %d bt %d n %d\n", slot, ept, bt, n);
            quickspline_init_with_buffer(&spl[slot], ept, bt, ext[slot], n);
            break;
        }
        case OP_DESTROY: {
            int32_t slot = next(), flags = next();
            printf("destroy s%d flags %d\n", slot, flags);
            quickspline_destroy(&spl[slot], flags);
            break;
        }
        case OP_SETUP: {
            int32_t slot = next(), ept = next(), bt = next();
            printf("setup s%d ept %d bt %d\n", slot, ept, bt);
            quickspline_setup(&spl[slot], ept, bt);
            break;
        }
        case OP_SETN: {
            int32_t slot = next(), n = next();
            quickspline_set_num_control_points(&spl[slot], n);
            break;
        }
        case OP_POKE: {
            int32_t slot = next(), k = next(), v = next();
            poke(&spl[slot], k, v);
            break;
        }
        case OP_CP: {
            int32_t slot = next(), idx = next();
            bVector4 *p = &spl[slot].pControlPoints[idx];
            p->x = bitsf(next());
            p->y = bitsf(next());
            p->z = bitsf(next());
            p->w = bitsf(next());
            break;
        }
        case OP_DUMP: {
            int32_t slot = next(), withbuf = next();
            dump(slot, withbuf);
            break;
        }
        case OP_BASIS:
            basis();
            break;
        case OP_BASISFLAG:
            QuickSplineBasisMatrixInitDone = next();
            break;
        case OP_BASISPOKE: {
            int32_t k = next(), r = next(), lane = next(), v = next();
            float *row = &(&QuickSplineBasisMatricies[k].v0)[r].x;
            row[lane] = bitsf(v);
            break;
        }
        case OP_INITBASIS:
            quickspline_init_basis_matricies();
            break;
        case OP_FIXUP:
            quickspline_fixup_endpoints(&spl[next()]);
            break;
        case OP_CLAMP: {
            int32_t slot = next(), t = next();
            float r = quickspline_clamp_param(&spl[slot], bitsf(t));
            printf("clamp %08x -> %08x\n", (unsigned)t, (unsigned)fbits(r));
            break;
        }
        case OP_GENEX: {
            int32_t slot = next(), start = next(), i;
            quickspline_generate_extrapolated_control_points(&spl[slot], out,
                                                             start);
            printf("genex %d\n", start);
            for (i = 0; i < 4; i++) {
                pvec("  ", &out[i]);
                printf("\n");
            }
            break;
        }
        case OP_EVAL: {
            int32_t slot = next(), t = next(), bt = next(), idx = next();
            quickspline_evaluate_spline(&spl[slot], &out[0], bitsf(t), bt,
                                        &spl[slot].pControlPoints[idx]);
            printf("eval %08x b%d cp%d -> ", (unsigned)t, bt, idx);
            pvec("", &out[0]);
            printf("\n");
            break;
        }
        case OP_GETPOINT: {
            int32_t slot = next(), t = next(), bt = next();
            char b[48];
            bVector4 *r = quickspline_get_point(&spl[slot], &out[0],
                                                bitsf(t), bt);
            // The model's OUT has no label of its own; neither does this.
            snprintf(b, sizeof b, "%s", r == &out[0] ? "?" : "wrong");
            printf("point %08x b%d -> ", (unsigned)t, bt);
            pvec("", &out[0]);
            printf(" ret %s\n", b);
            break;
        }
        case OP_FCCP: {
            int32_t slot = next(), x = next(), y = next(), z = next();
            int32_t start = next();
            bVector3 p;
            put_pt(&p, x, y, z);
            printf("fccp %08x %08x %08x from %d -> %d\n", (unsigned)x,
                   (unsigned)y, (unsigned)z, start,
                   quickspline_find_closest_control_point_from(&spl[slot],
                                                               &p, start));
            break;
        }
        case OP_FCCPALL: {
            int32_t slot = next(), x = next(), y = next(), z = next();
            bVector3 p;
            put_pt(&p, x, y, z);
            printf("fccp %08x %08x %08x -> %d\n", (unsigned)x, (unsigned)y,
                   (unsigned)z,
                   quickspline_find_closest_control_point(&spl[slot], &p));
            break;
        }
        case OP_FCP: {
            int32_t slot = next(), x = next(), y = next(), z = next();
            int32_t guess = next(), tol = next();
            bVector3 p;
            float r;
            put_pt(&p, x, y, z);
            r = quickspline_find_closest_param(&spl[slot], &p, bitsf(guess),
                                               bitsf(tol));
            printf("fcp %08x %08x %08x g %08x tol %08x -> %08x\n",
                   (unsigned)x, (unsigned)y, (unsigned)z, (unsigned)guess,
                   (unsigned)tol, (unsigned)fbits(r));
            break;
        }
        case OP_CAL: {
            int32_t slot = next(), samples = next();
            printf("calibrate s%d samples %d\n", slot, samples);
            quickspline_calibrate_length(&spl[slot], samples);
            break;
        }
        case OP_CONST:
            printf("const gp%d %08x\n", -27168,
                   (unsigned)fbits(QUICKSPLINE_EXTRAPOLATED_MIN));
            printf("const gp%d %08x\n", -27164,
                   (unsigned)fbits(QUICKSPLINE_EXTRAPOLATED_MAX));
            printf("const gp%d %08x\n", -27160,
                   (unsigned)fbits(QUICKSPLINE_LINE_EPSILON));
            break;
        default:
            fprintf(stderr, "op %d at word %u\n", (int)op, (unsigned)rd);
            return 2;
        }
    }
    (void)ntags;
    return 0;
}
