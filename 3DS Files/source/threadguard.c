// threadguard -- see threadguard.h.

#include "threadguard.h"

#include <malloc.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#include "hangwatch.h"

#define GUARD_MAX    4
#define GUARD_NAN    0x7fc00000u
#define GUARD_STRIDE 16                  // words between samples
#define GUARD_RUN    8                   // the shortest run that counts
#define GUARD_REACH  (64u << 10)         // how far the extent is followed
#define GUARD_TICK   (10 * 1000000LL)    // the workers' old timeout
#define GUARD_IDLE   (1000 * 1000000LL)  // theirs while the guard ticks

// libctru's: the malloc heap, all of it mapped from boot.
extern char* fake_heap_start;
extern char* fake_heap_end;

typedef struct {
    const char*        name;
    Thread             t;
    LightEvent*        wake;
    volatile uint32_t* lo;
    volatile uint32_t* hi;
} Guard;

static Guard                s_guard[GUARD_MAX];
static LightLock            s_lock;    // the list and every check
static bool                 s_lockUp;
static Thread               s_thread;
static volatile bool        s_ticking;
static const char* volatile s_clean = "(none yet)";
static uint32_t             s_hit;     // the first to see a run reports

void (*threadguard_note)(FILE* f);

// Where a worker that wakes onto the run goes: its saved pc, and the
// registers popped with it, are this function's address by then.
__attribute__((noinline, noreturn)) static void park(void)
{
    for (;;)
        svcSleepThread(INT64_MAX);
}

// -------------------------------------------------------------- the report

typedef struct {
    const Guard*       g;
    const char*        clean;
    const char*        where;
    uint32_t           marks;
    volatile uint32_t* lo;
    volatile uint32_t* hi;
    bool               haveBefore, haveAfter;
    uint32_t           before[16], after[16];
    const char*        trail[HANGWATCH_TRAIL];
} Hit;

static Hit s_report;

static void words(FILE* f, const char* what, const volatile uint32_t* at,
                  const uint32_t* w)
{
    fprintf(f, "threadguard: %s %08lx:", what,
            (unsigned long)(uintptr_t)at);
    for (int i = 0; i < 16; i++)
        fprintf(f, " %08lx", (unsigned long)w[i]);
    fprintf(f, "\n");
}

static void report(const Hit* h)
{
    uint32_t n = h->marks;

    fprintf(stderr, "threadguard: NaN floats over the %s worker's thread "
            "block: clean at \"%s\", seen at \"%s\" (written in between), "
            "mark %lu\n", h->g->name, h->clean, h->where, (unsigned long)n);
    fprintf(stderr, "threadguard: run %08lx..%08lx (%lu words), block "
            "%08lx..%08lx\n", (unsigned long)(uintptr_t)h->lo,
            (unsigned long)(uintptr_t)h->hi, (unsigned long)(h->hi - h->lo),
            (unsigned long)(uintptr_t)h->g->lo,
            (unsigned long)(uintptr_t)h->g->hi);
    if (h->haveBefore) words(stderr, "before", h->lo - 16, h->before);
    if (h->haveAfter) words(stderr, "after", h->hi, h->after);
    fprintf(stderr, "threadguard: marks, newest first:");
    for (uint32_t i = 0; i < HANGWATCH_TRAIL && i < n; i++)
        fprintf(stderr, " \"%s\"", h->trail[i]);
    fprintf(stderr, "\n");
    if (threadguard_note) threadguard_note(stderr);
}

// A run at `at` in g's block, seen at `where`, with the list locked. All
// that the report needs is taken before anything else moves, then every
// block's NaN words are made safe, and only then is anything written.
__attribute__((noreturn)) static void hit(const Guard* g,
                                          volatile uint32_t* at,
                                          const char* where)
{
    volatile uint32_t* heapLo = (volatile uint32_t*)(void*)fake_heap_start;
    volatile uint32_t* heapHi = (volatile uint32_t*)(void*)fake_heap_end;
    uint32_t           reach  = GUARD_REACH / 4;
    uint32_t           parkAt = (uint32_t)(uintptr_t)park;
    Hit*               h      = &s_report;

    if (!__atomic_exchange_n(&s_hit, 1u, __ATOMIC_SEQ_CST)) {
        h->g = g;
        h->clean = s_clean;
        h->where = where;
        h->marks = HangwatchMarks;
        h->lo = h->hi = at;
        while (h->lo > heapLo && (uint32_t)(at - h->lo) < reach
               && h->lo[-1] == GUARD_NAN)
            h->lo--;
        while (h->hi < heapHi && (uint32_t)(h->hi - at) < reach
               && *h->hi == GUARD_NAN)
            h->hi++;
        h->haveBefore = h->lo - 16 >= heapLo;
        h->haveAfter = h->hi + 16 <= heapHi;
        for (int i = 0; i < 16; i++) {
            if (h->haveBefore) h->before[i] = h->lo[i - 16];
            if (h->haveAfter) h->after[i] = h->hi[i];
        }
        for (uint32_t i = 0; i < HANGWATCH_TRAIL && i < h->marks; i++)
            h->trail[i] = HangwatchTrail[(h->marks - 1 - i) % HANGWATCH_TRAIL];
        for (int i = 0; i < GUARD_MAX; i++) {
            const Guard* b = &s_guard[i];
            if (!b->t) continue;
            for (volatile uint32_t* p = b->lo; p < b->hi; p++)
                if (*p == GUARD_NAN) *p = parkAt;
        }
        report(h);
        abort();
    }
    // The other thread's report is being written: wait for its abort.
    park();
}

// -------------------------------------------------------------- the checks

static void scan(const char* where)
{
    for (int i = 0; i < GUARD_MAX; i++) {
        const Guard* g = &s_guard[i];
        if (!g->t) continue;
        for (volatile uint32_t* p = g->lo; p < g->hi; p += GUARD_STRIDE) {
            if (*p != GUARD_NAN) continue;
            // A sample on the run: count it out both ways inside the
            // block.
            volatile uint32_t* a = p;
            volatile uint32_t* b = p + 1;
            while (a > g->lo && a[-1] == GUARD_NAN) a--;
            while (b < g->hi && *b == GUARD_NAN) b++;
            if (b - a >= GUARD_RUN) hit(g, p, where);
        }
    }
    s_clean = where;
}

void threadguard_check(const char* where)
{
    if (!s_lockUp) return;
    LightLock_Lock(&s_lock);
    scan(where);
    LightLock_Unlock(&s_lock);
}

void threadguard_signal(LightEvent* wake, const char* where)
{
    threadguard_check(where);
    LightEvent_Signal(wake);
}

int64_t threadguard_wait_ns(void)
{
    return s_ticking ? GUARD_IDLE : GUARD_TICK;
}

// The workers' clock: a check, then their wakes.
static void guard_main(void* arg)
{
    (void)arg;
    for (;;) {
        svcSleepThread(GUARD_TICK);
        LightLock_Lock(&s_lock);
        scan("the guard's tick");
        for (int i = 0; i < GUARD_MAX; i++)
            if (s_guard[i].t) LightEvent_Signal(s_guard[i].wake);
        LightLock_Unlock(&s_lock);
    }
}

// --------------------------------------------------------------- the list

void threadguard_watch(const char* name, Thread t, LightEvent* wake)
{
    if (!t) return;
    if (!s_lockUp) {
        LightLock_Init(&s_lock);
        s_lockUp = true;
    }
    LightLock_Lock(&s_lock);
    for (int i = 0; i < GUARD_MAX; i++) {
        Guard* g = &s_guard[i];
        if (g->t) continue;
        // The block threadCreate took from memalign: the Thread itself,
        // the stack and the TLS above it, to the end of its chunk.
        g->name = name;
        g->wake = wake;
        g->lo   = (volatile uint32_t*)(void*)t;
        g->hi   = g->lo + malloc_usable_size(t) / 4;
        g->t    = t;
        break;
    }
    LightLock_Unlock(&s_lock);

    // Above the workers, which are one above the game's thread, on the
    // same core.
    if (!s_thread) {
        s32 prio = 0x30;
        svcGetThreadPriority(&prio, CUR_THREAD_HANDLE);
        prio = prio > 0x1a ? prio - 2 : 0x18;
        s_thread = threadCreate(guard_main, NULL, 8 << 10, prio, -2, true);
        s_ticking = s_thread != NULL;
    }
}

void threadguard_forget(Thread t)
{
    if (!s_lockUp) return;
    LightLock_Lock(&s_lock);
    for (int i = 0; i < GUARD_MAX; i++)
        if (s_guard[i].t == t) s_guard[i].t = NULL;
    LightLock_Unlock(&s_lock);
}
