// Port of bSlotPool.obj, 0x0023f508-0x00240198. See docs/formats/bslotpool.md
// for the decode and bslotpool.h for the interface.
//
// Three layers, in the order the object lays them out: the free-function
// forwarders that name the members, SlotPool itself, and the SlotPoolManager
// singleton that owns the list of live pools. The PS2 layout is load-bearing
// rather than incidental -- one allocation holds the 48-byte header and then
// numSlots * slotSize bytes, and bGetSlot / bGetSlotNumber are public
// functions that do that arithmetic in the open -- so the header is pinned by
// static asserts below and must not be rearranged.

#include "bslotpool.h"

#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

// On the target -- ARM32, like the EE -- the header has to come out at the
// PS2's 48 bytes with every field where bWare put it, because that is what
// bGetSlot and bGetSlotNumber compute with. The host that runs the
// cross-check is LP64 and the same declaration is 72 bytes there, which is
// harmless (nothing outside this file assumes a number) but means the
// offsets can only be asserted where they are meant to hold.
#include <limits.h>
#if UINTPTR_MAX == 0xffffffffu
_Static_assert(sizeof(BSlotPool) == 48,
               "BSlotPool header must stay 48 bytes on target: bGetSlot and "
               "bGetSlotNumber index from (char*)pool + 48");
_Static_assert(offsetof(BSlotPool, nextSlotPool) == 8, "field moved");
_Static_assert(offsetof(BSlotPool, debugName) == 12, "field moved");
_Static_assert(offsetof(BSlotPool, freeSlots) == 16, "field moved");
_Static_assert(offsetof(BSlotPool, flags) == 20, "field moved");
_Static_assert(offsetof(BSlotPool, numAllocatedSlots) == 24, "field moved");
_Static_assert(offsetof(BSlotPool, mostNumAllocatedSlots) == 28, "field moved");
_Static_assert(offsetof(BSlotPool, memoryPool) == 32, "field moved");
_Static_assert(offsetof(BSlotPool, numSlots) == 36, "field moved");
_Static_assert(offsetof(BSlotPool, slotSize) == 40, "field moved");
_Static_assert(offsetof(BSlotPool, totalNumSlots) == 44, "field moved");
#endif
// These hold everywhere, and they are the ones the code actually depends on.
_Static_assert(offsetof(BSlotPool, node) == 0,
               "the list links must be first: the manager casts a node back "
               "to a pool");
_Static_assert(sizeof(BSlotPool) >= 12 * 4, "a field went missing");

// The shipped bPrintf format strings, byte for byte out of .rodata. Keeping
// them means a log from the port and a log from the PS2 line up, and it is
// also where the flag names in bslotpool.h come from.
#define BSP_EXPANDED  "WARNING:  Expanded slot pool %s by %d slots\n"
#define BSP_NOCLEAN   "WARNING:  SlotPool::CleanupExpandedSlotPools() unable to cleanup %d expanded slots from %s\n"
#define BSP_NEWEARLY  "WARNING:  SlotPoolManager::NewSlotPool(%s) called before SlotPoolManager::SlotPoolManager()\n"
#define BSP_DELUNINIT "WARNING:  SlotPoolManager::DeleteSlotPool(%s) called on unintialized SlotPoolManager.\n"
#define BSP_NONEMPTY  "WARNING:  DeleteSlotPool() called on nonempty SlotPool %s (%d slots allocated)\n"
#define BSP_HDR1      "                                                   Num            Most\n"
#define BSP_HDR2      "Name                                        Size   Slots  Alloc   Alloc  Overflow         Flags\n"
#define BSP_HDR3      "==================================================================================================================\n"
#define BSP_ROW       "%-40s   %4dK   %4d   %4d   %4d   %4d    "
#define BSP_F0        "  [FLAG_OVERFLOW_IF_FULL]"
#define BSP_F1        "  [ZERO_ALLOCATED_MEMORY]"
#define BSP_F2        "  [WARN_IF_OVERFLOW]"
#define BSP_F3        "  [WARN_IF_NONEMPTY_DELETE]"
#define BSP_NEWLINE   "\n"

// A free slot's first word is the link to the next free slot. The pool never
// reads anything else out of a free slot, and never writes word 0 of a slot
// it has handed out -- except in bSlotOMalloc's zero-fill, which runs after
// the link has been read.
//
// "Word" is the EE's 4 bytes because a pointer is 4 bytes there, and the same
// on ARM32. BSLOTPOOL_LINK_SIZE is that width rather than a literal 4 so the
// module is also correct where a host runs it with 8-byte pointers; on target
// it is 4 and every expression below reduces to the shipped one. A pool whose
// slotSize is smaller than this cannot thread a free list at all -- see the
// precondition in bslotpool.h.
typedef union {
    void* next;
} BSlotLink;

#define BSLOTPOOL_LINK_SIZE ((int)sizeof(void*))

static void* slot_link_get(const void* slot)
{
    return ((const BSlotLink*)slot)->next;
}

static void slot_link_set(void* slot, void* next)
{
    ((BSlotLink*)slot)->next = next;
}

static void* slot_base(const BSlotPool* pool)
{
    return (void*)((char*)pool + BSLOTPOOL_HEADER_SIZE);
}

// ------------------------------------------------------------- diagnostics

static BSlotPoolPrintf g_printf;

void bSetSlotPoolPrintf(BSlotPoolPrintf fn)
{
    g_printf = fn;
}

// One call here is one bPrintf call at 0x00238f28.
#if defined(__GNUC__)
__attribute__((format(printf, 1, 2)))
#endif
static void bsp_printf(const char* fmt, ...)
{
    char    buf[192];
    va_list ap;

    if (!g_printf) {
        return;
    }
    va_start(ap, fmt);
    vsnprintf(buf, sizeof buf, fmt, ap);
    va_end(ap);
    g_printf(buf);
}

// ------------------------------------------------------------ backing heap

static void* default_alloc(size_t bytes, const char* name, int memoryPool)
{
    (void)name;
    (void)memoryPool;
    return malloc(bytes);
}

static void default_release(void* block)
{
    free(block);
}

static BSlotPoolAlloc   g_alloc   = default_alloc;
static BSlotPoolRelease g_release = default_release;

void bSetSlotPoolAllocator(BSlotPoolAlloc alloc, BSlotPoolRelease release)
{
    g_alloc   = alloc   ? alloc   : default_alloc;
    g_release = release ? release : default_release;
}

// ----------------------------------------------------------- the singleton

// SlotPoolManager, 12 bytes at 0x00315268: an `Initialized` sentinel and a
// bTList<SlotPool>, which is one bTNode acting as the head of a circular
// doubly-linked list. Reproduced with the same shape rather than a
// NULL-terminated list, because bPrintAllSlotPools walks it until it comes
// back to the head node (0x00240004) and the order of that walk is what the
// transcript compares.
static struct {
    int           initialized;  // +0
    BSlotPoolNode head;         // +4
} g_mgr;

// __15SlotPoolManager, 0x0023fd18. The 3s it stores into both links first
// (0x0023fd20, 0x0023fd28) are bTNode's poison; bTList then overwrites them
// with the self-pointers that make an empty circular list.
void bSlotPoolManagerInit(void)
{
    g_mgr.head.next  = &g_mgr.head;
    g_mgr.head.prev  = &g_mgr.head;
    g_mgr.initialized = 1;
}

// _$_15SlotPoolManager, 0x0023fd40. Empties the list and clears the sentinel,
// and that is the whole destructor -- see the note in bslotpool.h.
void bSlotPoolManagerShutdown(void)
{
    g_mgr.head.next  = &g_mgr.head;
    g_mgr.head.prev  = &g_mgr.head;
    g_mgr.initialized = 0;
}

// SlotPoolManager::NewSlotPool's tail, 0x0023fe0c: append before the head
// node, i.e. at the tail of the list.
static void list_append(BSlotPool* pool)
{
    BSlotPoolNode* tail = g_mgr.head.prev;

    tail->next      = &pool->node;
    g_mgr.head.prev = &pool->node;
    pool->node.prev = tail;
    pool->node.next = &g_mgr.head;
}

// SlotPoolManager::DeleteSlotPool's unlink, 0x0023fe7c. The 11 stored into
// both links afterwards is bWare's freed-node poison; it is kept because
// anything that walks a deleted pool's links should land somewhere obviously
// wrong rather than somewhere plausible.
static void list_remove(BSlotPool* pool)
{
    BSlotPoolNode* next = pool->node.next;
    BSlotPoolNode* prev = pool->node.prev;

    if (!next || !prev) {
        return;   // never linked -- see the note on new_pool
    }
    prev->next = next;
    next->prev = prev;
    pool->node.next = (BSlotPoolNode*)(uintptr_t)11;
    pool->node.prev = (BSlotPoolNode*)(uintptr_t)11;
}

static BSlotPool* list_first(void)
{
    return g_mgr.head.next == &g_mgr.head
         ? NULL : (BSlotPool*)g_mgr.head.next;
}

static BSlotPool* list_next(const BSlotPool* pool)
{
    return pool->node.next == &g_mgr.head
         ? NULL : (BSlotPool*)pool->node.next;
}

// --------------------------------------------------------------- life cycle

// SlotPool::FlushSlotPool, 0x0023f6f0.
//
// Walks the expansion chain and gives *each* pool in it a free list of its
// own, running over that pool's own slots and terminated with NULL. That is
// the faithful behaviour and it is very nearly a bug: nothing ever reads a
// non-head pool's freeSlots, so flushing a pool that has expanded strands
// every expanded slot, and numAllocatedSlots is not reset either. It is safe
// where the original uses it -- inside SlotPool::NewSlotPool, on a chain one
// long -- and the retail build never calls it anywhere else.
//
// Note the loop writes the terminating NULL even when numSlots is 0
// (0x0023f748 is reached with a1 still at the slot base), which is a write
// four bytes past a zero-slot pool's allocation. Reproduced; nothing on the
// disc creates one.
void bFlushSlotPool(BSlotPool* pool)
{
    while (pool) {
        char* slot = (char*)slot_base(pool);
        int   size = pool->slotSize;
        int   last = pool->numSlots - 1;
        int   i;

        pool->freeSlots = slot;

        for (i = 0; i < last; i++) {
            slot_link_set(slot, slot + size);
            slot += size;
        }
        slot_link_set(slot, NULL);

        pool = pool->nextSlotPool;
    }
}

// SlotPool::NewSlotPool, 0x0023f638. A static member, so no rounding of
// slotSize happens here -- the manager layer does it.
//
// One divergence, and it fixes a latent bug rather than introducing one. The
// original writes ten fields into the fresh block (0x0023f684-0x0023f6b0) and
// the bTNode links at +0/+4 are not among them, so a pool starts life with
// garbage where its list links go. That is harmless for a pool the manager
// links (the link overwrites them) and for an expanded pool (never linked),
// but not for the third case the code explicitly supports: a pool created
// while the sentinel is clear is deliberately left off the list
// (0x0023fdf0), and deleting it later, once the manager is up, takes the
// unlink branch at 0x0023fe7c unconditionally and stores through whatever
// those two words happen to contain. The port clears them here and skips the
// unlink when they are clear.
static BSlotPool* new_pool(int slotSize, int numSlots, const char* name,
                           int memoryPool)
{
    BSlotPool* pool;
    size_t     bytes;

    // 0x0023f650 / 0x0023f674: `mult a0,s3,s1` then `addiu a0,a0,48`, a
    // 32-bit signed product. The port widens it, so a request the EE would
    // have wrapped into a small allocation fails here instead.
    bytes = (size_t)BSLOTPOOL_HEADER_SIZE + (size_t)slotSize * (size_t)numSlots;

    pool = (BSlotPool*)g_alloc(bytes, name, memoryPool);
    if (!pool) {
        return NULL;
    }

    pool->slotSize              = slotSize;
    pool->memoryPool            = memoryPool;
    pool->debugName             = name;
    pool->totalNumSlots         = numSlots;
    pool->numSlots              = numSlots;
    pool->freeSlots             = NULL;
    pool->nextSlotPool          = NULL;
    pool->numAllocatedSlots     = 0;
    pool->mostNumAllocatedSlots = 0;
    pool->flags                 = BSP_DEFAULT_FLAGS;
    pool->node.next             = NULL;   // not in the original; see above
    pool->node.prev             = NULL;

    bFlushSlotPool(pool);
    return pool;
}

// SlotPool::DeleteSlotPool, 0x0023f6d8: `if (p) bFree(p)`, one pool, not the
// chain.
static void delete_one(BSlotPool* pool)
{
    if (pool) {
        g_release(pool);
    }
}

// SlotPoolManager::NewSlotPool, 0x0023fda8, behind the bNewSlotPool
// forwarder at 0x0023f508.
BSlotPool* bNewSlotPool(int slotSize, int numSlots, const char* name,
                        int memoryPool)
{
    BSlotPool* pool = new_pool((slotSize + 3) & ~3, numSlots, name,
                               memoryPool);

    if (!pool) {
        return NULL;
    }
    // 0x0023fdf0 tests the sentinel against 1 exactly, where DeleteSlotPool
    // tests it against 0. Same thing for a sentinel that is only ever 0 or 1,
    // kept asymmetric because the original is.
    if (g_mgr.initialized != 1) {
        bsp_printf(BSP_NEWEARLY, pool->debugName);
        return pool;
    }
    list_append(pool);
    return pool;
}

// SlotPoolManager::DeleteSlotPool, 0x0023fe40, behind bDeleteSlotPool
// (0x0023f540).
void bDeleteSlotPool(BSlotPool* pool)
{
    BSlotPool* next;

    if (!pool) {
        return;
    }

    if (g_mgr.initialized) {
        list_remove(pool);
    } else {
        bsp_printf(BSP_DELUNINIT, pool->debugName);
    }

    if ((pool->flags & BSP_WARN_IF_NONEMPTY_DELETE)
        && pool->numAllocatedSlots > 0) {
        bsp_printf(BSP_NONEMPTY, pool->debugName,
                   (int)pool->numAllocatedSlots);
    }

    // 0x0023fec0: the whole expansion chain goes, head first.
    while (pool) {
        next = pool->nextSlotPool;
        delete_one(pool);
        pool = next;
    }
}

// Not in the original -- see bslotpool.h.
void bDeleteAllSlotPools(void)
{
    BSlotPool* pool;

    while ((pool = list_first()) != NULL) {
        bDeleteSlotPool(pool);
    }
}

// --------------------------------------------------------------- expansion

// SlotPool::ExpandSlotPool, 0x0023f760.
BSlotPool* bExpandSlotPool(BSlotPool* pool, int n)
{
    BSlotPool* grown;
    char*      lastSlot;
    void*      oldFree;

    if (pool->flags & BSP_WARN_IF_OVERFLOW) {
        bsp_printf(BSP_EXPANDED, pool->debugName, n);
    }

    grown = new_pool(pool->slotSize, n, pool->debugName, pool->memoryPool);
    if (!grown) {
        // The original does not check, and stores through the null pointer
        // four instructions later at 0x0023f7c8. Returning NULL is the one
        // behavioural change in this function; every caller already copes
        // with a pool that did not grow, because they re-read freeSlots.
        return NULL;
    }

    oldFree = pool->freeSlots;          // 0x0023f7b8, read before the stores

    grown->nextSlotPool = pool->nextSlotPool;
    grown->flags        = pool->flags;
    pool->nextSlotPool  = grown;
    pool->totalNumSlots += n;

    // Splice the new pool's free list onto the front of this one's. The
    // original computes the last slot as ((n - 1) * slotSize / 4) * 4 bytes
    // past the slot base (0x0023f7d8-0x0023f7ec, a movn-guarded divide that
    // rounds toward zero); slotSize is always a multiple of 4, so that is
    // exactly (n - 1) * slotSize.
    lastSlot = (char*)slot_base(grown) + (ptrdiff_t)(n - 1) * grown->slotSize;
    slot_link_set(lastSlot, oldFree);
    pool->freeSlots  = grown->freeSlots;
    grown->freeSlots = NULL;

    return grown;
}

// --------------------------------------------------------------- allocation

// The `numSlots / 4 + 1` that both Malloc paths grow by (0x0023fa5c and
// 0x0023fba8: a movn-guarded arithmetic shift, i.e. a divide that rounds
// toward zero).
static int grow_by(const BSlotPool* pool)
{
    return pool->numSlots / 4 + 1;
}

static void note_high_water(BSlotPool* pool, int allocated)
{
    pool->numAllocatedSlots = allocated;
    if (pool->mostNumAllocatedSlots < allocated) {
        pool->mostNumAllocatedSlots = allocated;
    }
}

// SlotPool::Malloc, 0x0023fa28 -- reached through bOMalloc (0x0023f578).
void* bSlotOMalloc(BSlotPool* pool)
{
    void* slot = pool->freeSlots;

    if (!slot && (pool->flags & BSP_OVERFLOW_IF_FULL)) {
        bExpandSlotPool(pool, grow_by(pool));
        slot = pool->freeSlots;
    }
    if (!slot) {
        return NULL;
    }

    pool->freeSlots = slot_link_get(slot);

    if (pool->flags & BSP_ZERO_ALLOCATED_MEMORY) {
        // The whole slot, link word included -- it has already been read.
        // 0x0023fa98 is an arithmetic shift, so a negative slotSize would
        // round toward zero and the blez below would skip the loop.
        int words = pool->slotSize / 4;
        if (words > 0) {
            memset(slot, 0, (size_t)words * 4);
        }
    }

    note_high_water(pool, pool->numAllocatedSlots + 1);
    return slot;
}

// SlotPool::FastMalloc, 0x0023faf8 -- reached through bMalloc (0x0023f558).
// No expand and no clear, but it still moves the high-water mark.
void* bSlotMalloc(BSlotPool* pool)
{
    void* slot = pool->freeSlots;

    if (!slot) {
        return NULL;
    }
    pool->freeSlots = slot_link_get(slot);
    note_high_water(pool, pool->numAllocatedSlots + 1);
    return slot;
}

// SlotPool::Free, 0x0023fb30.
void bSlotFree(BSlotPool* pool, void* slot)
{
    // No NULL check and no ownership check, exactly as shipped -- see the
    // warning in bslotpool.h.
    slot_link_set(slot, pool->freeSlots);
    pool->freeSlots = slot;
    pool->numAllocatedSlots -= 1;
}

// SlotPool::Malloc(int, void**), 0x0023fb50. No caller in the retail build.
void* bSlotMallocN(BSlotPool* pool, int n, void** last)
{
    void* head;
    void* tail;
    int   i;

    if (n == 0) {
        return NULL;
    }

    // 0x0023fb78: the decision to grow is made from the accounting, not from
    // the free list, and it asks for whichever is larger of the usual quarter
    // and n itself (0x0023fbbc, movn).
    if (pool->totalNumSlots - pool->numAllocatedSlots < n) {
        int grow;

        if (!(pool->flags & BSP_OVERFLOW_IF_FULL)) {
            return NULL;
        }
        grow = grow_by(pool);
        if (grow < n) {
            grow = n;
        }
        bExpandSlotPool(pool, grow);
    }

    head = pool->freeSlots;
    if (!head) {
        return NULL;
    }

    // Walk n-1 links forward. The chain can run out before that even after an
    // expand, because the expand is sized from the accounting and a negative
    // numAllocatedSlots (see bSlotFree) makes the accounting lie.
    tail = head;
    for (i = 0; i < n - 1; i++) {
        tail = slot_link_get(tail);
        if (!tail) {
            return NULL;
        }
    }

    pool->freeSlots = slot_link_get(tail);
    slot_link_set(tail, NULL);      // 0x0023fc14, before the `last` test
    if (last) {
        *last = tail;
    }

    note_high_water(pool, pool->numAllocatedSlots + n);

    if (pool->flags & BSP_ZERO_ALLOCATED_MEMORY) {
        // 0x0023fc58 starts the word index at 1, not 0: the link word is
        // skipped so the chain this call is handing back survives the clear.
        // Skipping one pointer rather than a literal four bytes is the same
        // thing on target and the only thing that works on an LP64 host.
        int   keep  = BSLOTPOOL_LINK_SIZE;
        int   clear = pool->slotSize - keep;
        void* p     = head;

        while (p) {
            void* nxt = slot_link_get(p);   // 0x0023fc68, before clearing
            if (clear > 0) {
                memset((char*)p + keep, 0, (size_t)clear);
            }
            p = nxt;
        }
    }

    return head;
}

// SlotPool::Free(void*, void*), 0x0023fcc0. No caller in the retail build.
void bSlotFreeN(BSlotPool* pool, void* head, void* tail)
{
    void* p;
    int   n = 0;

    // Terminating the chain first is what bounds the count below; it also
    // means tail is written through before head is even looked at, so a NULL
    // head does not save a caller who passed a bad tail.
    slot_link_set(tail, NULL);

    for (p = head; p; p = slot_link_get(p)) {
        n++;
    }

    slot_link_set(tail, pool->freeSlots);
    pool->freeSlots = head;
    pool->numAllocatedSlots -= n;
}

// ------------------------------------------------------------------ queries

// 0x0023f5c8. `divu`, so the subtraction is read as unsigned: a pointer below
// the slot array gives a huge index rather than a negative one. Reproduced.
int bGetSlotNumber(const BSlotPool* pool, const void* slot)
{
    uint32_t off = (uint32_t)((const char*)slot - (const char*)pool
                              - BSLOTPOOL_HEADER_SIZE);
    return (int)(off / (uint32_t)pool->slotSize);
}

// 0x0023f5f0.
void* bGetSlot(const BSlotPool* pool, int i)
{
    return (char*)slot_base(pool) + (ptrdiff_t)i * pool->slotSize;
}

// 0x0023f608. Compares against totalNumSlots, not numSlots.
int bIsSlotPoolFull(const BSlotPool* pool)
{
    return pool->numAllocatedSlots == pool->totalNumSlots;
}

// 0x0023f620.
int bCountFreeSlots(const BSlotPool* pool)
{
    return pool->totalNumSlots - pool->numAllocatedSlots;
}

// 0x0023f630.
int bCountTotalSlots(const BSlotPool* pool)
{
    return pool->totalNumSlots;
}

int bCountAllocatedSlots(const BSlotPool* pool)
{
    return pool->numAllocatedSlots;
}

int bCountMostAllocatedSlots(const BSlotPool* pool)
{
    return pool->mostNumAllocatedSlots;
}

const char* bGetSlotPoolName(const BSlotPool* pool)
{
    return pool->debugName;
}

uint32_t bGetSlotPoolFlags(const BSlotPool* pool)
{
    return pool->flags;
}

void bSetSlotPoolFlag(BSlotPool* pool, uint32_t flag)
{
    pool->flags |= flag;
}

void bClearSlotPoolFlag(BSlotPool* pool, uint32_t flag)
{
    pool->flags &= ~flag;
}

// The name and signature are recovered: `HasOverflowed::140:` on the SlotPool
// class, type 140 being a function of no arguments returning int
// (docs/mdebug_raw_strings.txt:25543). Only the body is inferred -- it has no
// out-of-line address, so there is no listing to decode -- and this is the
// reading of "overflowed" that the rest of the module supports, since
// totalNumSlots only ever parts company with numSlots through an expand.
int bHasSlotPoolOverflowed(const BSlotPool* pool)
{
    return pool->totalNumSlots != pool->numSlots;
}

// ----------------------------------------------------------------- cleanup

// Which pool in the expansion chain owns a slot, or NULL if none does. The
// caller starts the scan at the first *expanded* pool, never at the head:
// the head is not a cleanup candidate, and 0x0023f888 starts there for
// exactly that reason, so slots belonging to the head simply match nothing.
static BSlotPool* owner_of(BSlotPool* chain, const void* slot)
{
    BSlotPool* p;

    for (p = chain; p; p = p->nextSlotPool) {
        // Same unsigned divide as bGetSlotNumber (0x0023f894, 0x0023f8e0),
        // which is what makes a slot sitting below this pool fail the range
        // test instead of matching.
        uint32_t off = (uint32_t)((const char*)slot - (const char*)p
                                  - BSLOTPOOL_HEADER_SIZE);
        uint32_t idx = off / (uint32_t)p->slotSize;

        if ((int32_t)idx >= 0 && (int32_t)idx < p->numSlots) {
            return p;
        }
    }
    return NULL;
}

// SlotPool::CleanupExpandedSlotPools, 0x0023f820. Three passes.
void bCleanupExpandedSlotPools(BSlotPool* pool)
{
    BSlotPool* first = pool->nextSlotPool;
    BSlotPool* p;
    BSlotPool* prev;
    void*      slot;

    if (!first) {
        return;
    }

    // 1. 0x0023f858 -- assume every expanded pool is fully in use.
    for (p = first; p; p = p->nextSlotPool) {
        p->numAllocatedSlots = p->numSlots;
    }

    // 2. 0x0023f880 -- walk the free list and take one off the owning pool
    //    for each free slot. Slots belonging to the head pool match nothing
    //    and are skipped. After this, each expanded pool's counter is its
    //    real in-use count.
    for (slot = pool->freeSlots; slot; slot = slot_link_get(slot)) {
        BSlotPool* owner = owner_of(first, slot);
        if (owner) {
            owner->numAllocatedSlots -= 1;
        }
    }

    // 3. 0x0023f928 -- delete every expanded pool that came out empty,
    //    pulling its slots off the free list on the way.
    prev = pool;
    p    = first;
    while (p) {
        BSlotPool* next = p->nextSlotPool;

        if (p->numAllocatedSlots != 0) {
            if (pool->flags & BSP_WARN_IF_OVERFLOW) {
                bsp_printf(BSP_NOCLEAN, (int)p->numSlots, pool->debugName);
            }
        } else {
            void** link    = &pool->freeSlots;
            int    removed = 0;

            while (*link) {
                void* here = *link;
                void* nxt  = slot_link_get(here);

                if (owner_of(p, here) == p) {
                    *link = nxt;            // unlink, leave `link` where it is
                    removed++;
                } else {
                    link = &((BSlotLink*)here)->next;
                }
            }

            if (removed != p->numSlots) {
                // The original traps here (`break` at 0x0023f9bc). The two
                // passes use identical arithmetic over the same list, so this
                // is unreachable unless the free list has been corrupted --
                // which is a reason to leave the pool alone, not to take the
                // console down with it. The pool is kept, with its recount
                // left as pass 2 computed it.
                bsp_printf(BSP_NOCLEAN, (int)p->numSlots, pool->debugName);
                prev = p;
                p    = next;
                continue;
            }

            prev->nextSlotPool = next;
            pool->totalNumSlots -= p->numSlots;
            delete_one(p);
            p = prev;                        // 0x0023f9d8: prev does not move
        }

        prev = p;
        p    = next;
    }
}

// SlotPoolManager::CleanupExpandedSlotPools, 0x00240028.
void bCleanupAllExpandedSlotPools(void)
{
    BSlotPool* p;

    for (p = list_first(); p; p = list_next(p)) {
        bCleanupExpandedSlotPools(p);
    }
}

// SlotPoolManager::PrintAllSlotPools, 0x0023fef8: three header lines, then
// one row per pool with the flag names and a newline appended as separate
// bPrintf calls.
void bPrintAllSlotPools(void)
{
    BSlotPool* p;

    bsp_printf(BSP_HDR1);
    bsp_printf(BSP_HDR2);
    bsp_printf(BSP_HDR3);

    for (p = list_first(); p; p = list_next(p)) {
        // 0x0023ff64-0x0023ff88: a 32-bit signed product, then a
        // movn-guarded shift, i.e. bytes / 1024 rounding toward zero.
        int32_t bytes = (int32_t)((uint32_t)p->totalNumSlots
                                  * (uint32_t)p->slotSize);

        // The casts are the port's, not the ROM's: int32_t is `long` on
        // devkitARM and `int` on the EE, so %d needs one to stay honest
        // without touching the shipped format string.
        bsp_printf(BSP_ROW, p->debugName, (int)(bytes / 1024),
                   (int)p->totalNumSlots, (int)p->numAllocatedSlots,
                   (int)p->mostNumAllocatedSlots,
                   (int)(p->totalNumSlots - p->numSlots));

        if (p->flags & BSP_OVERFLOW_IF_FULL)        bsp_printf(BSP_F0);
        if (p->flags & BSP_ZERO_ALLOCATED_MEMORY)   bsp_printf(BSP_F1);
        if (p->flags & BSP_WARN_IF_OVERFLOW)        bsp_printf(BSP_F2);
        if (p->flags & BSP_WARN_IF_NONEMPTY_DELETE) bsp_printf(BSP_F3);
        bsp_printf(BSP_NEWLINE);
    }
}
