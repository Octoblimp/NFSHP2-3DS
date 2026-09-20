// bslotpool -- bware's fixed-size-block allocator, out of bSlotPool.obj
// (0x0023f508-0x00240198 in NFSHP2.ELF, 3216 bytes, 34 symbols).
//
// A slot pool is one allocation holding a 48-byte header followed by
// numSlots * slotSize bytes, with the free list threaded through the free
// slots themselves: word 0 of a free slot is the pointer to the next one.
// Allocating is four loads and three stores, releasing is three stores, and
// nothing searches or coalesces. That is why the engine leans on it -- the
// ELF declares 57 named `*SlotPool` globals, from `WheelSlotPool` and
// `ContactSlotPool` in the physics to `ParticleSlotPool`, `EventSlotPool`
// and `TrackPolygonCollisionBodySlotPool`, and every one of those object
// types is created and destroyed through this file.
//
// On the 3DS the backing allocation is an ordinary malloc, which is the heap
// that heapcfg.c sizes -- see bSetSlotPoolAllocator below if a pool ever has
// to come out of linear memory instead.
//
// Written up address by address in docs/formats/bslotpool.md; cross-checked
// by tools/bslotpool_check.py against a second implementation. Deliberately
// free of <3ds.h> so tools/src/bslotpool_test.c can drive it on the host.
//
// Names. The original is C++ and overloads on argument type; C cannot, so
// the five overloaded free functions are renamed and everything else keeps
// its bWare name exactly:
//
//     bMalloc(SlotPool*)                -> bSlotMalloc     (0x0023f558)
//     bOMalloc(SlotPool*)               -> bSlotOMalloc    (0x0023f578)
//     bFree(SlotPool*, void*)           -> bSlotFree       (0x0023f598)
//     bMalloc(SlotPool*, int, void**)   -> bSlotMallocN    (0x0023f5a0)
//     bFree(SlotPool*, void*, void*)    -> bSlotFreeN      (0x0023f5c0)
//
// Confusingly, the original's bMalloc is the *fast* path and bOMalloc is the
// full one. That is not a typo in the port: 0x0023f558 tail-calls
// SlotPool::FastMalloc and 0x0023f578 tail-calls SlotPool::Malloc.
#ifndef BSLOTPOOL_H
#define BSLOTPOOL_H

#include <stddef.h>
#include <stdint.h>

typedef struct BSlotPool BSlotPool;

// ---------------------------------------------------------------- the flags

// bWare's own names and values, recovered whole rather than invented here.
// The enum is `SlotPoolFlags`, named in the .mdebug type info for
// SlotPool::SetFlag / ClearFlag and spelled out in full at
// docs/mdebug_raw_strings.txt:25546:
//
//     SLOTPOOL_FLAG_OVERFLOW_IF_FULL:1
//     SLOTPOOL_FLAG_ZERO_ALLOCATED_MEMORY:2
//     SLOTPOOL_FLAG_WARN_IF_OVERFLOW:4
//     SLOTPOOL_FLAG_WARN_IF_NONEMPTY_DELETE:8
//
// The strings PrintAllSlotPools appends to each row (0x002a2fd0, 0x002a2ff0,
// 0x002a3010, 0x002a3028) name the same four in the same order, so the two
// sources agree.
//
// SlotPool::NewSlotPool sets all four unconditionally (0x0023f680 loads 15
// into Flags), so a pool starts fully instrumented and callers clear what
// they do not want.
#define BSP_OVERFLOW_IF_FULL       0x01u  // grow instead of returning NULL
#define BSP_ZERO_ALLOCATED_MEMORY  0x02u  // clear the slot on the way out
#define BSP_WARN_IF_OVERFLOW       0x04u  // report every expand and cleanup
#define BSP_WARN_IF_NONEMPTY_DELETE 0x08u // report slots still held at delete
#define BSP_DEFAULT_FLAGS          0x0fu

// ------------------------------------------------------------- the two types

// bTNode<SlotPool>, the intrusive link the manager's list is built from. It
// is the first base of SlotPool, so a pool's first two words are its links
// and the list head inside the manager is a bare node of the same shape --
// which is how the original's circular list closes on itself.
typedef struct BSlotPoolNode {
    struct BSlotPoolNode* next;  // +0
    struct BSlotPoolNode* prev;  // +4
} BSlotPoolNode;

// The header is 48 bytes and the slot array starts immediately after it.
// That is not an implementation detail to be tidied away: bGetSlot and
// bGetSlotNumber are public and do `(char*)pool + 48 + i * slotSize` in the
// open (0x0023f5f0, 0x0023f5c8), and NewSlotPool asks the heap for
// `slotSize * numSlots + 48` (0x0023f674). Every field is 4 bytes on both the
// EE and ARM32, so the layout carries over unchanged and bslotpool.c
// static-asserts it -- but only where pointers are four bytes wide, because
// the host that runs tools/src/bslotpool_test.c is LP64 and the same struct
// is 72 bytes there. Nothing in the module writes 48 down; it all goes
// through BSLOTPOOL_HEADER_SIZE, and the cross-check's transcript names slots
// by pool and index rather than by address so it does not depend on which.
//
// The .mdebug type info says sizeof(SlotPool) is 52, not 48, because the C++
// declaration ends in a one-element `SlotPoolEntry Slots[1]` trailing array
// at +48. 48 is the header; 52 is the header plus the first link word of the
// first slot.
struct BSlotPool {
    BSlotPoolNode node;                 // +0   the manager's list links
    BSlotPool*  nextSlotPool;           // +8   expansion chain
    const char* debugName;              // +12
    void*       freeSlots;              // +16  head of the free list
    uint32_t    flags;                  // +20
    int32_t     numAllocatedSlots;      // +24
    int32_t     mostNumAllocatedSlots;  // +28  high-water mark
    int32_t     memoryPool;             // +32  bWare heap id, recorded only
    int32_t     numSlots;               // +36  this pool's own slots
    int32_t     slotSize;               // +40  rounded up to a multiple of 4
    int32_t     totalNumSlots;          // +44  this pool plus its expansions
};

#define BSLOTPOOL_HEADER_SIZE ((size_t)sizeof(BSlotPool))

// ------------------------------------------------------------- the two hooks

// Every diagnostic in the object goes through bPrintf (0x00238f28). The port
// routes them through this hook so the 3DS build stays free of stdio and so
// the cross-check can capture them; a NULL hook (the default) discards
// everything. One call here is one bPrintf call there, including the three
// separate calls PrintAllSlotPools makes for a row's flag names and the
// fourth for its newline -- the format strings are the shipped ones.
typedef void (*BSlotPoolPrintf)(const char* text);
void bSetSlotPoolPrintf(BSlotPoolPrintf fn);

// Where a pool's one backing block comes from. The original calls
// bMalloc(bytes, name, 0, memoryPool) (0x0023f670), which routes through
// bWare's MemoryPool bank system; the 3DS has one heap, so the default here
// is malloc/free and memoryPool is recorded but unused. Swap it if a pool
// ever has to live in linear memory, or to give a test a deterministic arena.
// Both must be set together; passing NULL for either restores the default.
typedef void* (*BSlotPoolAlloc)(size_t bytes, const char* name,
                                int memoryPool);
typedef void  (*BSlotPoolRelease)(void* block);
void bSetSlotPoolAllocator(BSlotPoolAlloc alloc, BSlotPoolRelease release);

// --------------------------------------------------------------- life cycle

// The manager is a file-scope singleton: on the PS2 a static SlotPoolManager
// at 0x00315268 whose constructor runs from _GLOBAL_$I$ (0x00240080) and
// whose destructor runs from _GLOBAL_$D$ (0x00240070). C has no static
// constructors, so the port makes both explicit, and they are not cosmetic.
// The manager's first word is an `Initialized` sentinel, and both entry
// points check it: bNewSlotPool on a sentinel that is not 1 creates the pool
// but leaves it off the list (0x0023fdf0), and bDeleteSlotPool on a zero
// sentinel warns rather than unlinking (0x0023fe5c). Pools built outside the
// manager's lifetime work; they are just invisible to bPrintAllSlotPools and
// to bCleanupAllExpandedSlotPools.
void bSlotPoolManagerInit(void);

// ~SlotPoolManager (0x0023fd40) clears the sentinel and empties the list, and
// that is *all* it does -- it resets the head node to point at itself before
// calling ~bTList (0x0023fd5c, 0x0023fd68), so the walk that destructor would
// have made finds nothing, and ~SlotPool (0x00240108) is only ~bNode anyway.
// No pool memory is released. Faithful, and harmless at PS2 process exit.
// Call bDeleteAllSlotPools first if the port's own pools should go back to
// the heap.
void bSlotPoolManagerShutdown(void);

// Not in the original. Deletes every pool still on the manager's list, in
// the order bPrintAllSlotPools would list them. The port has this because a
// 3DS build that relaunches wants its memory back.
void bDeleteAllSlotPools(void);

// slotSize is rounded up to a multiple of 4 -- SlotPoolManager::NewSlotPool
// does it (0x0023fdac: `addiu v0,a1,3` then `and a0,v0,-4`), SlotPool's own
// static NewSlotPool does not, which is what makes the free-list threading
// and the zero-fill loops word-exact. Returns NULL if the backing allocation
// fails; the original's bMalloc cannot fail, so this is a port-only path.
//
// Precondition, unchecked here as it is unchecked there: slotSize must be at
// least one pointer wide, because the free list is threaded through the free
// slots. That is 4 bytes on the EE and 4 on ARM32, so every pool on the disc
// satisfies it by construction; it is written down because the host that
// runs the cross-check has 8-byte pointers and a 4-byte slot there would
// scribble past its neighbour.
BSlotPool* bNewSlotPool(int slotSize, int numSlots, const char* name,
                        int memoryPool);

// Unlinks the pool from the manager and frees it and every pool it expanded
// into (0x0023fec0). Does nothing on NULL.
void bDeleteSlotPool(BSlotPool* pool);

// Rebuilds the free list. Read docs/formats/bslotpool.md before calling this
// on a pool that has expanded: it gives each pool in the chain its own
// separate free list and does not reset numAllocatedSlots, which orphans
// every expanded slot. The retail build never calls it -- its only use is
// inside SlotPool::NewSlotPool, on a pool whose chain is one long.
void bFlushSlotPool(BSlotPool* pool);

// --------------------------------------------------------------- allocation

// The full path (SlotPool::Malloc, 0x0023fa28): expands when empty if
// BSP_OVERFLOW_IF_FULL is set, clears the whole slot if
// BSP_ZERO_ALLOCATED_MEMORY is set. NULL when the pool is empty and cannot
// grow.
void* bSlotOMalloc(BSlotPool* pool);

// The short path (SlotPool::FastMalloc, 0x0023faf8): no expand and no clear,
// but it still moves the high-water mark. Note which name is which -- see
// the note at the top of this file.
void* bSlotMalloc(BSlotPool* pool);

// Returns a slot. Does not check that it came from this pool, and does not
// check for NULL: 0x0023fb3c stores through the pointer before anything else
// happens. On the EE that quietly writes to low RAM, on ARM it is a data
// abort, so this is one place the port is less forgiving than the original
// rather than more. The counter is decremented whatever happens, so a double
// free drives numAllocatedSlots negative and puts a cycle in the free list.
void bSlotFree(BSlotPool* pool, void* slot);

// Takes n slots at once and hands them back as a chain linked through each
// slot's first word, terminated with NULL. `last` receives the tail when it
// is not NULL. The zero-fill, when enabled, starts at word 1 (0x0023fc58
// loads 1, not 0) so the chain survives it. NULL if n is 0 or the pool
// cannot supply n slots. No caller in the retail build.
void* bSlotMallocN(BSlotPool* pool, int n, void** last);

// Returns a chain built by bSlotMallocN. `tail` must be the last slot; it is
// written through at 0x0023fcc0, before `head` is even examined, so it has to
// be valid even when head is NULL. No caller in the retail build.
void bSlotFreeN(BSlotPool* pool, void* head, void* tail);

// ------------------------------------------------------------------ queries

// Slot index of a pointer, as ((char*)slot - ((char*)pool + 48)) / slotSize.
// `divu` at 0x0023f5d4, so the subtraction is read as unsigned: a pointer
// below the slot array comes back as a very large number, not a negative one.
int bGetSlotNumber(const BSlotPool* pool, const void* slot);

// Address of slot i (0x0023f5f0). No range check.
void* bGetSlot(const BSlotPool* pool, int i);

// 0x0023f608. Compares against totalNumSlots, so a pool that can still expand
// reports full when its current slots run out.
int bIsSlotPoolFull(const BSlotPool* pool);

int bCountFreeSlots(const BSlotPool* pool);   // 0x0023f620
int bCountTotalSlots(const BSlotPool* pool);  // 0x0023f630

// SlotPool's inline accessors. These have no symbols of their own -- they are
// inlined at every call site -- so the bodies are read off the field offsets
// the out-of-line code uses, except HasOverflowed, which is inferred from its
// name and from PrintAllSlotPools printing TotalNumSlots - NumSlots under an
// "Overflow" heading (0x0023ff70). Stated rather than claimed.
int         bCountAllocatedSlots(const BSlotPool* pool);
int         bCountMostAllocatedSlots(const BSlotPool* pool);
const char* bGetSlotPoolName(const BSlotPool* pool);
uint32_t    bGetSlotPoolFlags(const BSlotPool* pool);
void        bSetSlotPoolFlag(BSlotPool* pool, uint32_t flag);
void        bClearSlotPoolFlag(BSlotPool* pool, uint32_t flag);
int         bHasSlotPoolOverflowed(const BSlotPool* pool);

// --------------------------------------------------------------- expansion

// Grows the pool by n slots (0x0023f760): allocates a second pool of the same
// slot size, inherits this pool's flags into it, links it into the chain and
// splices its free slots onto the front of this one's free list. Returns the
// new pool, or NULL if the allocation failed -- the original does not check
// and stores through the null pointer four instructions later (0x0023f7c8).
BSlotPool* bExpandSlotPool(BSlotPool* pool, int n);

// Frees every expanded pool that has become completely unused and returns its
// slots to the accounting (0x0023f820, three passes, the largest routine in
// the object). Reports each surviving pool when BSP_WARN_IF_OVERFLOW is set.
void bCleanupExpandedSlotPools(BSlotPool* pool);

// The same, for every pool on the manager's list (0x00240028).
void bCleanupAllExpandedSlotPools(void);

// One row per live pool through the printf hook (0x0023fef8), under the
// shipped three-line header.
void bPrintAllSlotPools(void);

#endif
