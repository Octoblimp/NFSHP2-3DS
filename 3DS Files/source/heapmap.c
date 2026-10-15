// heapmap -- see heapmap.h.

#include "heapmap.h"

#include <reent.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

// The sbrk window's end (heapcfg.c sets it).
extern char* fake_heap_end;

// mallocr.c's, under newlib's names for them.
extern char* __malloc_sbrk_base;
extern void* __malloc_av_[];
extern void  __malloc_lock(struct _reent* r);
extern void  __malloc_unlock(struct _reent* r);

#define PREV_INUSE 1u
#define SIZE_BITS  3u
#define MINSIZE    16u
#define PIECE_MIN  (64u * 1024)

typedef struct {
    uint32_t prev;
    uint32_t size;
} Chunk;

// The first chunk is the first sbrk's, moved up to 8 (malloc_extend_top's
// front_misalign). The top is av_[2]; before the first sbrk it is the bins'
// own header and sbrk_base is still -1.
static Chunk* first_chunk(void)
{
    uintptr_t b = (uintptr_t)__malloc_sbrk_base;

    if (__malloc_sbrk_base == (char*)-1 || b == 0) return NULL;
    return (Chunk*)((b + 7u) & ~(uintptr_t)7);
}

static uint32_t chunk_size(const Chunk* c) { return c->size & ~SIZE_BITS; }

// ------------------------------------------------------------ the names

#define NAMES     256
#define NAME_LEN  28

typedef struct {
    void*    p;
    uint32_t size;
    char     name[NAME_LEN];
} Name;

static Name g_names[NAMES];

void heapmap_note(void* p, int size, const char* name)
{
    int i;

    if (p == NULL || (uint32_t)size < HEAPMAP_NAMED) return;
    __malloc_lock(_REENT);
    for (i = 0; i < NAMES; i++) {
        if (g_names[i].p != NULL) continue;
        g_names[i].p    = p;
        g_names[i].size = (uint32_t)size;
        snprintf(g_names[i].name, NAME_LEN, "%s", name ? name : "?");
        break;
    }
    __malloc_unlock(_REENT);
}

void heapmap_forget(void* p)
{
    int i;

    if (p == NULL) return;
    __malloc_lock(_REENT);
    for (i = 0; i < NAMES; i++) {
        if (g_names[i].p == p) {
            g_names[i].p = NULL;
            break;
        }
    }
    __malloc_unlock(_REENT);
}

void heapmap_named(void (*line)(const char* text), uint32_t lo, uint32_t hi)
{
    Name     copy[NAMES];
    char     text[64];
    int      i, n = 0;

    __malloc_lock(_REENT);
    for (i = 0; i < NAMES; i++) {
        uint32_t a = (uint32_t)(uintptr_t)g_names[i].p;

        if (g_names[i].p != NULL && a >= lo && a < hi) copy[n++] = g_names[i];
    }
    __malloc_unlock(_REENT);
    for (i = 0; i < n; i++) {
        snprintf(text, sizeof text, "%lu KB %s",
                 (unsigned long)copy[i].size / 1024, copy[i].name);
        line(text);
    }
}

// A chunk's block's name, or NULL: memalign's blocks are chunks' too, so
// the block is the chunk's memory, 8 on.
static const char* name_of(const Chunk* c)
{
    const void* p = (const char*)c + 8;
    int         i;

    for (i = 0; i < NAMES; i++)
        if (g_names[i].p == p) return g_names[i].name;
    return NULL;
}

// ------------------------------------------------------------- the walk

typedef void (*Visit)(void* ctx, const Chunk* c, uint32_t size, int used,
                      int top);

// Under the malloc lock. 0 when there is no heap yet or a size word does
// not lead on to the top.
static int walk(Visit v, void* ctx)
{
    Chunk* c   = first_chunk();
    Chunk* top = (Chunk*)__malloc_av_[2];

    char*  brk;

    if (c == NULL || top == NULL || top < c) return 0;
    while (c < top) {
        uint32_t sz = chunk_size(c);
        Chunk*   n  = (Chunk*)((char*)c + sz);

        if (sz < MINSIZE || n > top) return 0;
        v(ctx, c, sz, (n->size & PREV_INUSE) != 0, 0);
        c = n;
    }
    // The top grows into what sbrk has not handed out, up to the heap's
    // end, and free trims it back (M_TRIM_THRESHOLD): that is free too.
    brk = (char*)sbrk(0);
    v(ctx, top,
      chunk_size(top)
          + (brk != (char*)-1 && fake_heap_end > brk
                 ? (uint32_t)(fake_heap_end - brk) : 0u),
      0, 1);
    return 1;
}

static void take_one(void* ctx, const Chunk* c, uint32_t size, int used,
                     int top)
{
    HeapMap* m = (HeapMap*)ctx;

    (void)c;
    if (used) {
        m->used += size;
        return;
    }
    m->free += size;
    if (size > m->largest) m->largest = size;
    if (size >= PIECE_MIN) m->pieces++;
    if (top) m->top = size;
}

void heapmap_take(HeapMap* m)
{
    memset(m, 0, sizeof *m);
    __malloc_lock(_REENT);
    m->ok = walk(take_one, m);
    __malloc_unlock(_REENT);
}

// ------------------------------------------------------------ the lines

#define PIECES 48

typedef struct {
    uint32_t at, size;            // the free piece; size 0 for the tail
    uint32_t blocks, bytes;       // the run in use before it
    uint32_t holes, holeBytes;    // its free chunks under the minimum
    uint32_t largest;             // its largest block
    char     name[NAME_LEN];      // that block's, or ""
} Piece;

typedef struct {
    const Chunk* base;
    uint32_t     min;
    Piece        run;             // the run being walked
    Piece        pieces[PIECES];
    int          n, dropped;
} Lines;

static void lines_one(void* ctx, const Chunk* c, uint32_t size, int used,
                      int top)
{
    Lines* l = (Lines*)ctx;
    Piece* r = &l->run;

    if (used) {
        r->blocks++;
        r->bytes += size;
        if (size > r->largest) {
            const char* nm = name_of(c);

            r->largest = size;
            snprintf(r->name, NAME_LEN, "%s", nm ? nm : "");
        }
        return;
    }
    if (size < l->min && !top) {
        r->holes++;
        r->holeBytes += size;
        return;
    }
    if (size < l->min) size = 0;  // a small top: only the run before it
    r->at   = (uint32_t)((const char*)c - (const char*)l->base);
    r->size = size;
    if (l->n < PIECES) l->pieces[l->n++] = *r;
    else l->dropped++;
    memset(r, 0, sizeof *r);
}

void heapmap_lines(void (*line)(const char* text), uint32_t min)
{
    static Lines l;
    char         s[160];
    int          i, ok;

    memset(&l, 0, sizeof l);
    l.min = min < MINSIZE ? MINSIZE : min;
    __malloc_lock(_REENT);
    l.base = first_chunk();
    ok     = walk(lines_one, &l);
    __malloc_unlock(_REENT);
    if (!ok) {
        line("heap: no map (no heap yet, or a chunk did not read)");
        return;
    }
    // The lines after the lock: a line may itself allocate.
    for (i = 0; i < l.n; i++) {
        const Piece* p = &l.pieces[i];

        snprintf(s, sizeof s,
                 "heap: %6lu KB used in %4lu (%lu KB in %lu holes; largest "
                 "%lu KB%s%s), then at %6lu KB %lu KB free%s",
                 (unsigned long)p->bytes / 1024, (unsigned long)p->blocks,
                 (unsigned long)p->holeBytes / 1024, (unsigned long)p->holes,
                 (unsigned long)p->largest / 1024, p->name[0] ? " " : "",
                 p->name, (unsigned long)p->at / 1024,
                 (unsigned long)p->size / 1024,
                 i == l.n - 1 && !l.dropped ? ", the top" : "");
        line(s);
    }
    if (l.dropped) {
        snprintf(s, sizeof s, "heap: and %d more pieces", l.dropped);
        line(s);
    }
}
