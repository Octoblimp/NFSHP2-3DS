// Host harness for bware's slot-pool allocator.
//
// Builds "3DS Files/source/bslotpool.c" for the host, with bplist.c, the
// bPNode pool on top of it, and drives them through scripted sequences of
// pool operations, printing one line per step:
//
//     scenario <name>
//     <op> <args> -> <result>
//     pool '<name>' P0 size=.. num=.. total=.. alloc=.. most=.. ...
//       free: P0#3 P0#2 P1#0 (3)
//     log| <a line bPrintf would have produced>
//
// tools/bslotpool_check.py prints the same from a Python model written off
// the disassembly at 0x0023f508 rather than off this code, and diffs the two.
//
// An allocator's behaviour is in the *sequence*, not in any single call, so
// almost everything here is a script: allocate, release, expand, clean up,
// then dump the whole pool chain and the whole free list and compare.
//
// Two things have to be arranged before the two sides can be compared at all,
// and both come from the same fact: this host is LP64 and the 3DS is not.
//
//   * A raw address will not do. The port's header is 48 bytes on ARM32 and
//     72 here, so every arena offset would move. The allocator hook is
//     pointed at a bump arena that registers each block, and a pointer prints
//     as the block that contains it and the slot index within it: `P2#5` is
//     slot 5 of the third block allocated in this scenario, `P2#5+3` three
//     bytes into it, `P2` a header, `P2!+0` a block that has been released,
//     `??` an address in no block at all. Names are not quite the whole
//     story -- an address inside no slot still prints a raw byte offset, so
//     `bGetSlot(-2)` comes back as `P0+48` here and would be `P0+24` on
//     target -- so the model derives the header size from the host's pointer
//     width rather than keeping the PS2's 48.
//
//   * A slot's first word is a *pointer*, so it is eight bytes here and four
//     on target. Slot contents are therefore printed as the link -- through
//     the same symbolic namer -- plus the payload words that follow it, never
//     as a flat word dump, and a pool whose slotSize is under a pointer wide
//     is never walked. The model uses the host's pointer width for the same
//     reason the port does.
//
// Fresh blocks are filled with 0xCD, so an uninitialised word reads
// differently from a zeroed one; released blocks are left exactly as they
// were and never reused, so a dangling pointer keeps finding the bytes it
// used to find. The arena's capacity is a *block* count rather than a byte
// count, again so that what fits does not depend on how wide a pointer is.
//
// Usage: bslotpool_test [scenario]...      (no argument runs them all)

#include <stdio.h>
#include <string.h>

#include "bplist.h"
#include "bslotpool.h"

#define ARENA_SIZE    (1u << 18)
#define MAX_BLOCKS    64
#define FREE_WALK_MAX 64        /* a corrupt free list can be a cycle */
#define LINK_SIZE     ((int)sizeof(void*))
#define LINK_WORDS    (LINK_SIZE / 4)

static unsigned char g_arena[ARENA_SIZE];
static unsigned      g_cursor;
static unsigned      g_blockBudget;

static struct {
    unsigned char* base;
    size_t         bytes;
    int            live;
} g_block[MAX_BLOCKS];
static int g_blocks;

// Sixteen bytes of slack past every block, so that a pool whose slotSize is
// smaller than a host pointer -- legal on target, impossible to thread here --
// writes its last link into slack instead of into its neighbour. Nothing
// reads that slack.
static void* arena_alloc(size_t bytes, const char* name, int memoryPool)
{
    unsigned       need = ((unsigned)bytes + 16u + 15u) & ~15u;
    unsigned char* p;

    (void)name;
    (void)memoryPool;
    if ((unsigned)g_blocks >= g_blockBudget || g_blocks >= MAX_BLOCKS
        || g_cursor + need > ARENA_SIZE) {
        return NULL;
    }
    p = g_arena + g_cursor;
    g_cursor += need;
    memset(p, 0xcd, need);
    g_block[g_blocks].base  = p;
    g_block[g_blocks].bytes = bytes;
    g_block[g_blocks].live  = 1;
    g_blocks++;
    return p;
}

static void arena_release(void* block)
{
    int i;

    for (i = 0; i < g_blocks; i++) {
        if (g_block[i].base == (unsigned char*)block) {
            g_block[i].live = 0;
            return;
        }
    }
    printf("!! released a block the arena never handed out\n");
}

static void arena_reset(unsigned blockBudget)
{
    g_cursor      = 0;
    g_blocks      = 0;
    g_blockBudget = blockBudget;
    memset(g_arena, 0xaa, ARENA_SIZE);
    memset(g_block, 0, sizeof g_block);
}

// ----------------------------------------------------------------- printing

// A rotating buffer so several addresses can appear in one printf. Which
// buffer each call gets depends on the argument evaluation order, but the
// contents do not, so this is safe even where gcc evaluates right to left.
static const char* A(const void* p)
{
    static char bufs[6][32];
    static int  turn;
    char*       b = bufs[turn++ % 6];
    int         i;

    if (!p) {
        strcpy(b, "nil");
        return b;
    }
    for (i = 0; i < g_blocks; i++) {
        const unsigned char* base = g_block[i].base;
        long                 off;

        if ((const unsigned char*)p < base
            || (const unsigned char*)p >= base + g_block[i].bytes) {
            continue;
        }
        off = (long)((const unsigned char*)p - base);
        if (!g_block[i].live) {
            sprintf(b, "P%d!+%ld", i, off);
        } else if (off < (long)BSLOTPOOL_HEADER_SIZE) {
            if (off == 0) {
                sprintf(b, "P%d", i);
            } else {
                sprintf(b, "P%d+%ld", i, off);
            }
        } else {
            const BSlotPool* pool = (const BSlotPool*)base;
            long             rel  = off - (long)BSLOTPOOL_HEADER_SIZE;
            long             idx  = rel / pool->slotSize;
            long             rem  = rel % pool->slotSize;

            if (rem) {
                sprintf(b, "P%d#%ld+%ld", i, idx, rem);
            } else {
                sprintf(b, "P%d#%ld", i, idx);
            }
        }
        return b;
    }
    strcpy(b, "??");
    return b;
}

// Which arena blocks are still checked out. Nothing else in the transcript
// says this: a pointer only reports its block's liveness when something still
// prints that pointer, and after a teardown nothing does. Without this line a
// bDeleteSlotPool that releases the head of an expansion chain and drops the
// rest looks exactly like one that releases all of it.
static void dump_arena(void)
{
    int i;

    printf("arena:");
    for (i = 0; i < g_blocks; i++) {
        printf(" P%d=%s", i, g_block[i].live ? "live" : "free");
    }
    printf(" (%d)\n", g_blocks);
}

// ------------------------------------------------------------- the log hook

static char     g_log[4096];
static unsigned g_logLen;

static void log_hook(const char* text)
{
    unsigned n = (unsigned)strlen(text);

    if (g_logLen + n >= sizeof g_log) {
        n = (unsigned)(sizeof g_log - 1 - g_logLen);
    }
    memcpy(g_log + g_logLen, text, n);
    g_logLen += n;
    g_log[g_logLen] = 0;
}

// Print every complete line the hook has collected, keeping any partial one
// for the next flush -- PrintAllSlotPools builds a row out of up to six
// separate bPrintf calls and only the last of them ends the line.
static void flush_log(void)
{
    unsigned start = 0;
    unsigned i;

    for (i = 0; i < g_logLen; i++) {
        if (g_log[i] == '\n') {
            printf("log| %.*s\n", (int)(i - start), g_log + start);
            start = i + 1;
        }
    }
    if (start) {
        memmove(g_log, g_log + start, g_logLen - start);
        g_logLen -= start;
        g_log[g_logLen] = 0;
    }
}

static void end_log(void)
{
    flush_log();
    if (g_logLen) {
        printf("log| %s <partial>\n", g_log);
        g_logLen = 0;
        g_log[0] = 0;
    }
}

// ------------------------------------------------------------- state dumps

static void dump_free(const BSlotPool* pool)
{
    const void* p = pool->freeSlots;
    int         n = 0;

    printf("  free:");
    if (pool->slotSize < LINK_SIZE) {
        printf(" <slot narrower than a host pointer, not walked>\n");
        return;
    }
    while (p && n < FREE_WALK_MAX) {
        printf(" %s", A(p));
        p = *(void* const*)p;
        n++;
    }
    if (p) {
        printf(" ...(%d+, cycle or overlong)", n);
    } else {
        printf(" (%d)", n);
    }
    printf("\n");
}

static void dump_pool(const BSlotPool* pool)
{
    if (!pool) {
        printf("pool nil\n");
        return;
    }
    printf("pool '%s' %s size=%d num=%d total=%d alloc=%d most=%d "
           "flags=0x%02x mem=%d next=%s\n",
           pool->debugName ? pool->debugName : "(null)", A(pool),
           pool->slotSize, pool->numSlots, pool->totalNumSlots,
           pool->numAllocatedSlots, pool->mostNumAllocatedSlots,
           (unsigned)pool->flags, pool->memoryPool, A(pool->nextSlotPool));
    dump_free(pool);
}

// The head pool plus everything it has expanded into.
static void dump_chain(const BSlotPool* pool)
{
    const BSlotPool* p;
    int              n = 0;

    printf("chain:");
    for (p = pool; p; p = p->nextSlotPool) {
        printf(" %s[%d]", A(p), p->numSlots);
        n++;
    }
    printf(" (%d)\n", n);
    for (p = pool; p; p = p->nextSlotPool) {
        dump_pool(p);
    }
}

// A slot's link word, named the same way any other pointer is, and then the
// payload words that follow it -- never a flat dump, because the link is a
// different width here than on target.
static void dump_slot(const void* slot, int slotSize)
{
    int words = slotSize / 4;
    int i;

    printf("  slot %s link=%s payload:", A(slot), A(*(void* const*)slot));
    for (i = LINK_WORDS; i < words; i++) {
        printf(" %08x", ((const unsigned*)slot)[i]);
    }
    printf("\n");
}

// Dirty a slot. `fromWord` is 0 to scribble over the link as well, which is
// fair game once the slot has been handed out, and LINK_WORDS to leave a live
// chain walkable.
static void fill_slot(void* slot, int slotSize, unsigned seed, int fromWord)
{
    int words = slotSize / 4;
    int i;

    for (i = fromWord; i < words; i++) {
        ((unsigned*)slot)[i] = seed + (unsigned)i * 0x01010101u;
    }
}

// ------------------------------------------------------------------ helpers

static BSlotPool* mk(int slotSize, int numSlots, const char* name, int mempool)
{
    BSlotPool* p = bNewSlotPool(slotSize, numSlots, name, mempool);

    printf("bNewSlotPool(%d, %d, '%s', %d) -> %s\n",
           slotSize, numSlots, name, mempool, A(p));
    flush_log();
    return p;
}

static void* omalloc(BSlotPool* pool, const char* tag)
{
    void* s = bSlotOMalloc(pool);

    printf("bSlotOMalloc(%s) -> %s   [%s]\n", A(pool), A(s), tag);
    flush_log();
    return s;
}

static void* fmalloc(BSlotPool* pool, const char* tag)
{
    void* s = bSlotMalloc(pool);

    printf("bSlotMalloc(%s) -> %s   [%s]\n", A(pool), A(s), tag);
    flush_log();
    return s;
}

static void sfree(BSlotPool* pool, void* slot, const char* tag)
{
    printf("bSlotFree(%s, %s)   [%s]\n", A(pool), A(slot), tag);
    bSlotFree(pool, slot);
    flush_log();
}

static void counts(const BSlotPool* pool)
{
    printf("counts full=%d free=%d total=%d alloc=%d most=%d over=%d "
           "flags=0x%02x name='%s'\n",
           bIsSlotPoolFull(pool), bCountFreeSlots(pool),
           bCountTotalSlots(pool), bCountAllocatedSlots(pool),
           bCountMostAllocatedSlots(pool), bHasSlotPoolOverflowed(pool),
           (unsigned)bGetSlotPoolFlags(pool), bGetSlotPoolName(pool));
}

// ----------------------------------------------------------------- scenarios

// One pool, taken empty and given back, in two different orders, with growth
// switched off so this stays about the plain path. The free list is a LIFO,
// so slots come back in the reverse of the order they went out.
static void s_basic(void)
{
    BSlotPool* p = mk(8, 4, "BASIC", 0);
    void*      s[4];
    int        i;

    bClearSlotPoolFlag(p, BSP_ZERO_ALLOCATED_MEMORY);
    bClearSlotPoolFlag(p, BSP_OVERFLOW_IF_FULL);
    dump_pool(p);
    counts(p);

    for (i = 0; i < 4; i++) {
        s[i] = omalloc(p, "take");
    }
    dump_pool(p);
    counts(p);
    printf("one too many:\n");
    (void)omalloc(p, "empty");

    for (i = 0; i < 4; i++) {
        sfree(p, s[i], "give back in order");
    }
    dump_pool(p);
    counts(p);

    for (i = 0; i < 4; i++) {
        s[i] = omalloc(p, "take again");
    }
    for (i = 3; i >= 0; i--) {
        sfree(p, s[i], "give back reversed");
    }
    dump_pool(p);
    counts(p);

    bDeleteSlotPool(p);
    printf("deleted\n");
    end_log();
}

// Every slot index, including the ones off both ends. bGetSlotNumber divides
// unsigned, so a pointer below the slot array comes back enormous.
static void s_queries(void)
{
    BSlotPool* p = mk(12, 5, "QUERIES", 3);
    int        i;

    for (i = -2; i <= 6; i++) {
        void* s = bGetSlot(p, i);
        printf("bGetSlot(%2d) -> %-8s bGetSlotNumber -> %11d (0x%08x)\n",
               i, A(s), bGetSlotNumber(p, s),
               (unsigned)bGetSlotNumber(p, s));
    }
    printf("one byte before the array: bGetSlotNumber -> %11d (0x%08x)\n",
           bGetSlotNumber(p, (char*)bGetSlot(p, 0) - 1),
           (unsigned)bGetSlotNumber(p, (char*)bGetSlot(p, 0) - 1));
    printf("one byte into slot 0:      bGetSlotNumber -> %11d\n",
           bGetSlotNumber(p, (char*)bGetSlot(p, 0) + 1));
    counts(p);
    (void)bSlotOMalloc(p);
    counts(p);
    bDeleteSlotPool(p);
    end_log();
}

// slotSize is rounded up to a multiple of 4 by the manager layer and nowhere
// else, which is what keeps the free-list threading word-exact.
static void s_rounding(void)
{
    int      sizes[] = {1, 2, 3, 4, 5, 7, 8, 9, 12, 13, 16, 31, 32, 33};
    unsigned i;

    for (i = 0; i < sizeof sizes / sizeof sizes[0]; i++) {
        BSlotPool* p = mk(sizes[i], 3, "ROUND", 0);

        printf("asked %2d -> slotSize %2d, slot1 %s, slot2 %s\n",
               sizes[i], p->slotSize, A(bGetSlot(p, 1)), A(bGetSlot(p, 2)));
        dump_free(p);
        bDeleteSlotPool(p);
    }
    end_log();
}

// ZERO_ALLOCATED_MEMORY clears the whole slot on the way out, link word
// included -- the link has already been read by then.
static void s_zero(void)
{
    BSlotPool* p = mk(16, 3, "ZERO", 0);
    void*      a;
    void*      b;

    printf("flags default 0x%02x\n", (unsigned)bGetSlotPoolFlags(p));
    a = omalloc(p, "fresh, zeroed");
    dump_slot(a, 16);
    fill_slot(a, 16, 0x11111111u, 0);
    dump_slot(a, 16);
    sfree(p, a, "back");
    dump_slot(a, 16);
    b = omalloc(p, "same slot, zeroed again");
    dump_slot(b, 16);

    printf("now with the flag off:\n");
    bClearSlotPoolFlag(p, BSP_ZERO_ALLOCATED_MEMORY);
    fill_slot(b, 16, 0x22222222u, 0);
    sfree(p, b, "back");
    b = omalloc(p, "dirty");
    dump_slot(b, 16);

    printf("FastMalloc never clears, whatever the flag says:\n");
    bSetSlotPoolFlag(p, BSP_ZERO_ALLOCATED_MEMORY);
    fill_slot(b, 16, 0x33333333u, 0);
    sfree(p, b, "back");
    b = fmalloc(p, "fast");
    dump_slot(b, 16);

    bDeleteSlotPool(p);
    end_log();
}

// The two allocate paths differ in exactly two things: FastMalloc will not
// grow the pool and will not clear the slot. Both move the high-water mark.
static void s_fast(void)
{
    BSlotPool* p = mk(8, 2, "FAST", 0);
    void*      s[4];
    int        i;

    bClearSlotPoolFlag(p, BSP_ZERO_ALLOCATED_MEMORY);
    for (i = 0; i < 4; i++) {
        s[i] = fmalloc(p, "fast");
    }
    dump_chain(p);
    counts(p);
    for (i = 0; i < 2; i++) {
        sfree(p, s[i], "back");
    }
    printf("and now the slow path, which grows:\n");
    for (i = 0; i < 4; i++) {
        s[i] = omalloc(p, "slow");
    }
    dump_chain(p);
    counts(p);
    bDeleteSlotPool(p);
    end_log();
}

// Growing. The quarter-plus-one rule, the flag that gates it, the inherited
// flags, and the spliced free list.
static void s_expand(void)
{
    BSlotPool* p = mk(8, 8, "EXPAND", 2);
    int        i;

    bClearSlotPoolFlag(p, BSP_ZERO_ALLOCATED_MEMORY);
    for (i = 0; i < 8; i++) {
        (void)omalloc(p, "fill it");
    }
    dump_chain(p);
    printf("the ninth grows it by numSlots/4 + 1 = %d:\n", 8 / 4 + 1);
    (void)omalloc(p, "grow");
    dump_chain(p);
    counts(p);
    for (i = 9; i < 12; i++) {
        (void)omalloc(p, "eat the expansion");
    }
    dump_chain(p);
    printf("and again -- note numSlots is still the original 8:\n");
    (void)omalloc(p, "grow again");
    dump_chain(p);
    counts(p);

    printf("with the flag off it just fails:\n");
    bClearSlotPoolFlag(p, BSP_OVERFLOW_IF_FULL);
    for (i = 13; i < 16; i++) {
        (void)omalloc(p, "drain");
    }
    (void)omalloc(p, "no grow");
    dump_chain(p);

    printf("an explicit expand, flag or no flag:\n");
    (void)bExpandSlotPool(p, 3);
    dump_chain(p);
    counts(p);
    bDeleteSlotPool(p);
    end_log();
}

// WARN_IF_OVERFLOW turns the expand and the cleanup into log lines, and
// WARN_IF_NONEMPTY_DELETE turns a leak into one.
static void s_warn(void)
{
    BSlotPool* p = mk(8, 4, "WARN", 0);
    void*      s[6];
    int        i;

    for (i = 0; i < 6; i++) {
        s[i] = omalloc(p, "fill and grow");
    }
    dump_chain(p);
    printf("hold one expanded slot, release the rest, then clean up:\n");
    for (i = 0; i < 5; i++) {
        sfree(p, s[i], "back");
    }
    bCleanupExpandedSlotPools(p);
    flush_log();
    dump_chain(p);
    sfree(p, s[5], "the last one");
    bCleanupExpandedSlotPools(p);
    flush_log();
    dump_chain(p);
    printf("deleting it while it still holds slots:\n");
    (void)omalloc(p, "hold");
    bDeleteSlotPool(p);
    end_log();
}

// Several expansions, released in an order that leaves one of them busy, so
// cleanup has to relink around a pool it is not deleting.
static void s_cleanup(void)
{
    BSlotPool* p = mk(8, 4, "CLEANUP", 0);
    void*      s[16];
    int        i;
    int        n = 0;

    bClearSlotPoolFlag(p, BSP_ZERO_ALLOCATED_MEMORY);
    for (i = 0; i < 10; i++) {
        s[n++] = omalloc(p, "fill");
    }
    dump_chain(p);
    printf("free everything except the sixth slot handed out:\n");
    for (i = 0; i < n; i++) {
        if (i != 5) {
            sfree(p, s[i], "back");
        }
    }
    dump_chain(p);
    bCleanupExpandedSlotPools(p);
    flush_log();
    printf("after cleanup:\n");
    dump_chain(p);
    counts(p);
    printf("release the survivor and clean up again:\n");
    sfree(p, s[5], "back");
    bCleanupExpandedSlotPools(p);
    flush_log();
    dump_chain(p);
    counts(p);
    printf("cleanup on a pool that never grew does nothing:\n");
    bCleanupExpandedSlotPools(p);
    dump_chain(p);
    bDeleteSlotPool(p);
    end_log();
}

// The range test cleanup uses to decide which pool a free slot belongs to
// (0x0023f894, 0x0023f8e0) is half-open: an address exactly one slot array
// past the end of an expanded pool belongs to nobody, and has to keep
// belonging to nobody, or cleanup miscounts the pool it sits behind.
//
// Nothing in ordinary use puts such an address on a free list. bSlotFree
// checks nothing at all, though -- `abuse` leans on that -- so one can be put
// there deliberately. The arena hands blocks out in order, never reuses a
// released one, and leaves sixteen bytes of slack past each, so the end of
// the last pool is scratch and the link word written there disturbs nothing.
static void s_boundary(void)
{
    BSlotPool* p = mk(8, 8, "BOUNDARY", 0);
    BSlotPool* g;
    void*      s[9];
    void*      justPast;
    int        i;

    bClearSlotPoolFlag(p, BSP_ZERO_ALLOCATED_MEMORY);
    for (i = 0; i < 9; i++) {
        s[i] = omalloc(p, "fill and grow");
    }
    g = p->nextSlotPool;
    dump_chain(p);

    printf("give back the one slot that came out of the expanded pool, so it "
           "is empty and cleanup should reclaim it:\n");
    sfree(p, s[8], "the expanded one");
    dump_chain(p);

    justPast = bGetSlot(g, g->numSlots);
    printf("%s ends at %s, which bGetSlotNumber calls slot %d of %d -- one "
           "too far:\n",
           A(g), A(justPast), bGetSlotNumber(g, justPast), g->numSlots);
    sfree(p, justPast, "an address belonging to no pool");
    dump_pool(p);

    bCleanupExpandedSlotPools(p);
    flush_log();
    printf("after cleanup -- the stray address is still on the list, and the "
           "empty pool went anyway:\n");
    dump_chain(p);
    counts(p);
    bDeleteSlotPool(p);
    end_log();
}

// FlushSlotPool on a chain is the documented near-bug: every pool in the
// chain gets its own private free list, only the head's is ever read, and the
// allocation counter is left alone.
static void s_flush(void)
{
    BSlotPool* p = mk(8, 3, "FLUSH", 0);
    int        i;

    bClearSlotPoolFlag(p, BSP_ZERO_ALLOCATED_MEMORY);
    for (i = 0; i < 5; i++) {
        (void)omalloc(p, "fill and grow");
    }
    dump_chain(p);
    printf("flush:\n");
    bFlushSlotPool(p);
    dump_chain(p);
    counts(p);
    printf("the expanded slots are now unreachable; taking 4 gives 3 and a "
           "grow:\n");
    for (i = 0; i < 4; i++) {
        (void)omalloc(p, "after flush");
    }
    dump_chain(p);
    bDeleteSlotPool(p);
    end_log();
}

// The array overloads, which no retail caller uses.
static void s_mallocn(void)
{
    BSlotPool* p = mk(8, 6, "MALLOCN", 0);
    void*      last;
    void*      head;
    void*      h2;
    void*      l2;
    void*      q;

    bClearSlotPoolFlag(p, BSP_ZERO_ALLOCATED_MEMORY);
    last = NULL;
    head = bSlotMallocN(p, 0, &last);
    printf("bSlotMallocN(0) -> %s last=%s (untouched)\n", A(head), A(last));
    flush_log();

    head = bSlotMallocN(p, 3, &last);
    printf("bSlotMallocN(3) -> %s last=%s\n", A(head), A(last));
    flush_log();
    dump_pool(p);
    printf("the chain it handed back:");
    for (q = head; q; q = *(void**)q) {
        printf(" %s", A(q));
    }
    printf("\n");

    h2 = bSlotMallocN(p, 2, NULL);
    printf("bSlotMallocN(2, NULL) -> %s\n", A(h2));
    flush_log();
    dump_pool(p);

    printf("asking for more than is left, with growth allowed:\n");
    l2 = NULL;
    h2 = bSlotMallocN(p, 5, &l2);
    printf("bSlotMallocN(5) -> %s last=%s\n", A(h2), A(l2));
    flush_log();
    dump_chain(p);
    counts(p);

    printf("give the first three back as a chain:\n");
    bSlotFreeN(p, head, last);
    flush_log();
    dump_pool(p);
    counts(p);

    printf("hand back only part of a chain, which is what taking head and "
           "tail separately is for. Everything behind the named tail is "
           "dropped on the floor, and the counter moves by the length the "
           "walk found rather than the length the caller meant -- so the two "
           "have to agree, and the NULL store at 0x0023fcc0 is what makes "
           "them agree:\n");
    l2 = NULL;
    h2 = bSlotMallocN(p, 4, &l2);
    printf("bSlotMallocN(4) -> %s last=%s\n", A(h2), A(l2));
    flush_log();
    q = *(void**)h2;
    printf("hand back %s..%s, abandoning %s onward\n",
           A(h2), A(q), A(*(void**)q));
    bSlotFreeN(p, h2, q);
    flush_log();
    dump_pool(p);
    counts(p);

    printf("and with growth forbidden:\n");
    bClearSlotPoolFlag(p, BSP_OVERFLOW_IF_FULL);
    h2 = bSlotMallocN(p, 99, &l2);
    printf("bSlotMallocN(99) -> %s\n", A(h2));
    dump_pool(p);

    printf("a one-slot chain is its own tail:\n");
    h2 = bSlotMallocN(p, 1, &l2);
    printf("bSlotMallocN(1) -> %s last=%s\n", A(h2), A(l2));
    bSlotFreeN(p, h2, l2);
    dump_pool(p);
    counts(p);
    bDeleteSlotPool(p);
    end_log();
}

// Zeroing an array allocation skips each slot's link word, which is what
// keeps the returned chain walkable.
static void s_mallocnzero(void)
{
    BSlotPool* p = mk(16, 4, "MALLOCNZ", 0);
    void*      head;
    void*      last;
    void*      q;

    head = bSlotMallocN(p, 3, &last);
    printf("bSlotMallocN(3) -> %s last=%s\n", A(head), A(last));
    for (q = head; q; q = *(void**)q) {
        dump_slot(q, 16);
    }
    printf("dirty the payloads, give them back, take them again:\n");
    for (q = head; q; q = *(void**)q) {
        fill_slot(q, 16, 0xdead0000u, LINK_WORDS);
    }
    bSlotFreeN(p, head, last);
    head = bSlotMallocN(p, 3, &last);
    printf("bSlotMallocN(3) -> %s last=%s\n", A(head), A(last));
    for (q = head; q; q = *(void**)q) {
        dump_slot(q, 16);
    }
    counts(p);
    bDeleteSlotPool(p);
    end_log();
}

// The manager's sentinel, and what happens on either side of its lifetime.
static void s_manager(void)
{
    BSlotPool* early;
    BSlotPool* normal;

    printf("shutdown first, so the sentinel is clear:\n");
    bSlotPoolManagerShutdown();
    early = mk(8, 2, "EARLY", 0);
    dump_pool(early);

    printf("init, then a normal pool:\n");
    bSlotPoolManagerInit();
    normal = mk(8, 2, "NORMAL", 0);
    bPrintAllSlotPools();
    flush_log();

    printf("deleting the early one is fine, it is just not on the list:\n");
    bDeleteSlotPool(early);
    flush_log();
    bPrintAllSlotPools();
    flush_log();

    printf("shutdown abandons the list without freeing anything:\n");
    bSlotPoolManagerShutdown();
    bPrintAllSlotPools();
    flush_log();
    printf("deleting after shutdown warns instead of unlinking:\n");
    bDeleteSlotPool(normal);
    flush_log();

    printf("a fresh manager, three pools, then bDeleteAllSlotPools:\n");
    bSlotPoolManagerInit();
    (void)mk(8, 2, "LATE_A", 0);
    (void)mk(8, 2, "LATE_B", 0);
    (void)mk(8, 2, "LATE_C", 0);
    bPrintAllSlotPools();
    flush_log();
    bDeleteAllSlotPools();
    bPrintAllSlotPools();
    end_log();
}

// The whole PrintAllSlotPools table, with the flag combinations that change
// a row.
static void s_print(void)
{
    BSlotPool* a = mk(64, 100, "A_QUITE_LONG_POOL_NAME_TO_TEST_THE_COLUMN", 0);
    BSlotPool* b = mk(8, 1, "B", 1);
    BSlotPool* c = mk(1024, 40, "C", 2);
    int        i;

    bClearSlotPoolFlag(a, BSP_ZERO_ALLOCATED_MEMORY);
    bClearSlotPoolFlag(a, BSP_WARN_IF_OVERFLOW);
    bClearSlotPoolFlag(b, BSP_OVERFLOW_IF_FULL);
    bClearSlotPoolFlag(b, BSP_WARN_IF_NONEMPTY_DELETE);
    bClearSlotPoolFlag(c, 0xfu);

    for (i = 0; i < 7; i++) {
        (void)bSlotOMalloc(a);
    }
    for (i = 0; i < 3; i++) {
        bSlotFree(a, bGetSlot(a, i));
    }
    for (i = 0; i < 6; i++) {
        (void)bSlotOMalloc(c);
    }
    flush_log();
    bPrintAllSlotPools();
    flush_log();

    printf("after growing A past its own slots:\n");
    bSetSlotPoolFlag(a, BSP_OVERFLOW_IF_FULL);
    for (i = 0; i < 100; i++) {
        (void)bSlotOMalloc(a);
    }
    flush_log();
    bPrintAllSlotPools();
    flush_log();

    bDeleteSlotPool(a);
    bDeleteSlotPool(b);
    bDeleteSlotPool(c);
    end_log();
}

// What the port does that the original cannot: survive a heap that says no.
static void s_oom(void)
{
    BSlotPool* p;
    BSlotPool* q;
    int        i;

    printf("the arena will hand out one block and no more:\n");
    arena_reset(1);
    p = mk(8, 4, "OOM", 0);
    dump_pool(p);
    q = mk(8, 4, "TOOBIG", 0);
    printf("second pool -> %s\n", A(q));
    flush_log();
    printf("expanding the first -> %s\n", A(bExpandSlotPool(p, 4)));
    flush_log();
    for (i = 0; i < 6; i++) {
        (void)omalloc(p, "drain past the end");
    }
    dump_chain(p);
    counts(p);
    bDeleteSlotPool(p);
    end_log();
}

// The two documented pathologies, both reachable from ordinary code and
// neither checked for by the original.
static void s_abuse(void)
{
    BSlotPool* p = mk(8, 3, "ABUSE", 0);
    BSlotPool* q = mk(8, 2, "ELSEWHERE", 0);
    void*      a;
    void*      b;
    void*      foreign;

    bClearSlotPoolFlag(p, BSP_ZERO_ALLOCATED_MEMORY);
    bClearSlotPoolFlag(q, BSP_ZERO_ALLOCATED_MEMORY);
    a = omalloc(p, "take");
    b = omalloc(p, "take");
    printf("free the same slot twice -- the free list closes on itself:\n");
    sfree(p, a, "once");
    sfree(p, a, "twice");
    dump_pool(p);
    counts(p);
    printf("taking it back opens the cycle again, one slot short:\n");
    (void)omalloc(p, "take");
    dump_pool(p);
    counts(p);

    printf("free a slot that belongs to a different pool -- nothing checks, "
           "so it joins this pool's free list and will be handed out:\n");
    foreign = omalloc(q, "from the other pool");
    sfree(p, foreign, "foreign");
    dump_pool(p);
    counts(p);
    dump_pool(q);
    counts(q);
    printf("and out it comes:\n");
    (void)omalloc(p, "take the foreign slot");
    dump_pool(p);

    sfree(p, b, "and the real one");
    dump_pool(p);
    counts(p);
    bDeleteSlotPool(p);
    bDeleteSlotPool(q);
    end_log();
}

// A long scripted sequence, because an allocator's bugs live in the order of
// operations rather than in any one of them. The generator is a plain LCG so
// both sides walk the same path.
static void s_stress(void)
{
    BSlotPool* p = mk(12, 5, "STRESS", 0);
    void*      held[64];
    int        n = 0;
    unsigned   seed = 12345u;
    int        step;

    for (step = 0; step < 200; step++) {
        unsigned r;

        seed = seed * 1664525u + 1013904223u;
        r = (seed >> 16) & 0xffu;

        if (r < 110 || n == 0) {
            void* s = bSlotOMalloc(p);

            if (s) {
                held[n++] = s;
            }
            printf("%3d take -> %s  (held %d)\n", step, A(s), n);
        } else if (r < 220) {
            int   k = (int)((seed >> 8) % (unsigned)n);
            void* s = held[k];

            held[k] = held[--n];
            bSlotFree(p, s);
            printf("%3d give %s     (held %d)\n", step, A(s), n);
        } else if (r < 240) {
            bCleanupExpandedSlotPools(p);
            printf("%3d cleanup      (held %d)\n", step, n);
        } else {
            printf("%3d state:\n", step);
            dump_chain(p);
            counts(p);
        }
        flush_log();
        if (n > 40) {
            while (n) {
                bSlotFree(p, held[--n]);
            }
            printf("%3d drained\n", step);
        }
    }
    dump_chain(p);
    counts(p);
    while (n) {
        bSlotFree(p, held[--n]);
    }
    bCleanupExpandedSlotPools(p);
    flush_log();
    dump_chain(p);
    counts(p);
    bDeleteSlotPool(p);
    end_log();
}

// bPList's node pool (bplist.c), which is one pool behind four functions.
// The first bPListInit makes it and a second, asking for another count,
// finds it made. bPListClose deletes it with a node still out and forgets
// it, and a second close does nothing. With no pool, bPNode::Malloc makes
// one of 32 first.
static void pnodes(const char* what)
{
    printf("%s: bPNodeSlotPool %s\n", what, A(bPNodeSlotPool));
    flush_log();
    dump_pool(bPNodeSlotPool);
}

static void* pmalloc(const char* tag)
{
    void* s = bpnode_malloc();

    printf("bPNode::Malloc -> %s   [%s]\n", A(s), tag);
    flush_log();
    return s;
}

static void pfree(void* s, const char* tag)
{
    printf("bPNode::Free(%s)   [%s]\n", A(s), tag);
    bpnode_free(s);
    flush_log();
}

static void s_bplist(void)
{
    int   size = (int)sizeof(bPNode);
    void* s[3];

    pnodes("before");
    bplist_init(5);
    pnodes("bPListInit(5)");
    bplist_init(9);
    pnodes("bPListInit(9)");

    s[0] = pmalloc("first");
    s[1] = pmalloc("second");
    s[2] = pmalloc("third");
    dump_slot(s[1], size);
    fill_slot(s[1], size, 0x5a5a5a5au, 0);
    pfree(s[1], "dirty");
    s[1] = pmalloc("the dirty one again");
    dump_slot(s[1], size);
    pfree(s[0], "back");
    pfree(s[2], "back");
    pnodes("two back");
    counts(bPNodeSlotPool);

    bplist_close();
    pnodes("bPListClose, one still out");
    bplist_close();
    pnodes("bPListClose again");

    s[0] = pmalloc("no pool");
    pnodes("made by Malloc");
    pfree(s[0], "back");
    bplist_close();
    pnodes("closed");
    end_log();
}

// ---------------------------------------------------------------------- main

typedef struct {
    const char* name;
    void      (*fn)(void);
} Scenario;

static const Scenario SCENARIOS[] = {
    { "basic",       s_basic },
    { "queries",     s_queries },
    { "rounding",    s_rounding },
    { "zero",        s_zero },
    { "fast",        s_fast },
    { "expand",      s_expand },
    { "warn",        s_warn },
    { "cleanup",     s_cleanup },
    { "boundary",    s_boundary },
    { "flush",       s_flush },
    { "mallocn",     s_mallocn },
    { "mallocnzero", s_mallocnzero },
    { "manager",     s_manager },
    { "print",       s_print },
    { "oom",         s_oom },
    { "abuse",       s_abuse },
    { "stress",      s_stress },
    { "bplist",      s_bplist },
};

#define NSCENARIOS ((int)(sizeof SCENARIOS / sizeof SCENARIOS[0]))

int main(int argc, char** argv)
{
    int i;
    int j;

    setvbuf(stdout, NULL, _IOLBF, 0);

    for (i = 0; i < NSCENARIOS; i++) {
        int wanted = (argc <= 1);

        for (j = 1; j < argc; j++) {
            if (strcmp(argv[j], SCENARIOS[i].name) == 0) {
                wanted = 1;
            }
        }
        if (!wanted) {
            continue;
        }
        // Every scenario starts from a clean arena and a live manager, so one
        // can be run on its own and still print what it prints in a full run.
        arena_reset(MAX_BLOCKS);
        g_logLen = 0;
        g_log[0] = 0;
        bSetSlotPoolPrintf(log_hook);
        bSetSlotPoolAllocator(arena_alloc, arena_release);
        bSlotPoolManagerInit();

        printf("scenario %s\n", SCENARIOS[i].name);
        SCENARIOS[i].fn();
        // Every scenario ends with the arena's own account of what it still
        // holds, which is the only place a leaked expansion pool shows up.
        dump_arena();
    }
    return 0;
}
