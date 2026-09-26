#!/usr/bin/env python3
r"""Cross-check the bware slot-pool allocator against a second implementation.

`3DS Files/source/bslotpool.c` is the port of `bSlotPool.obj` -- fixed-size
blocks carved out of one bMalloc, a free list threaded through word 0 of every
free slot, an expansion chain when a pool runs dry, and a manager that keeps
every pool on a list so the whole lot can be printed. This file is that
allocator written again, in Python, from the disassembly at 0x0023f508 rather
than from the C. `tools/src/bslotpool_test.c` drives the port through eighteen
scripted sequences and prints a transcript; this prints the same transcript
from the model, and the diff is the test. The eighteenth is `bplist.c`, the
bPNode pool on top (bList.obj's last four functions, 0x002383f8..0x0023849c).

Why write it twice, when the C is a transcription of the same listing:

  * An allocator has no return value worth checking on its own. `Malloc`
    returning "the third slot" is right or wrong only relative to every
    allocate, release, expand and clean-up that came before it, so what is
    compared here is the whole *sequence*: after each step both sides print
    the pool chain, the free list in order, and the six counters.

  * The free list is a LIFO with no coalescing, no ownership check and no
    double-free check, so the order slots come back in is part of the
    contract. `CleanupExpandedSlotPools` then splices one pool's slots out of
    the middle of that list (0x0023f960), and getting the splice subtly wrong
    -- dropping the node before the run, say -- still leaves a plausible
    list. Only a literal second walk catches it.

  * Three counters disagree with each other on purpose. `numAllocatedSlots`
    on an expansion pool is not maintained during normal use at all: cleanup
    reconstructs it by setting it to `numSlots` and then decrementing once
    per free slot it finds (0x0023f858, 0x0023f880). `FlushSlotPool` rebuilds
    every pool's free list but leaves the counters alone (0x0023f6f0), and
    `mostNumAllocatedSlots` is moved by `FastMalloc` even on the path that
    returns nothing. A model that "tidied" any of that would hide a real
    difference.

  * The arithmetic is the EE's. `GetSlotNumber` divides *unsigned*
    (0x0023f5d4), so a pointer below the slot array comes back as 357913939
    rather than -2; the quarter-plus-one growth rule rounds toward zero
    through a movn (0x0023fa64); the kilobyte column is an arithmetic shift
    of a signed product (0x0023ff88). All three are modelled literally.

Two arrangements let a 64-bit host stand in for the 3DS at all:

  * `HDR` is computed from the host's pointer width the way the port's struct
    is laid out -- five pointers then seven 32-bit words -- which is 72 here
    and exactly the PS2's 48 when a pointer is four bytes wide. Addresses are
    never printed raw: a pointer prints as the arena block that contains it
    and the slot index within it (`P2#5`), so the transcript says the same
    thing at either width.

  * A slot's link word is a pointer, so slot contents print as the link plus
    the payload words after it, and a pool whose slotSize is under a pointer
    wide is never walked.

Four places where this follows the port rather than the ROM, because the
port deliberately diverges (all four are in docs/formats/bslotpool.md):

  * `ExpandSlotPool` checks that the new pool was allocated. The original
    dereferences it unconditionally at 0x0023f7c8.
  * A new pool's list links start NULL and unlinking a pool that was never
    linked does nothing. `SlotPool::NewSlotPool` never writes +0/+4, so
    deleting a pool created while the manager was down walks garbage at
    0x0023fe7c.
  * The array-allocate zero pass skips one pointer rather than a literal four
    bytes (0x0023fc58), which is the same four bytes on any 32-bit target.
  * The third cleanup pass logs and keeps the pool when its two recounts
    disagree. The original traps (`break` at 0x0023f9bc), which is a way of
    taking the console down over a free list that is already corrupt.

Usage:
    python tools/bslotpool_check.py
    python tools/bslotpool_check.py --scenario stress
    python tools/bslotpool_check.py --dump out.txt
"""
import argparse
import difflib
import os
import struct
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hostbuild

NL = chr(10)

SOURCES = [
    "tools/src/bslotpool_test.c",
    "3DS Files/source/bslotpool.c",
    "3DS Files/source/bplist.c",
]

# --------------------------------------------------------------------- shapes

PTR = struct.calcsize("P")
# The header is the two bTNode links, nextSlotPool, debugName and freeSlots --
# five pointers -- followed by flags and six counters. 48 bytes when a pointer
# is four wide, which is what the PS2 allocates at 0x0023f674.
HDR = (5 * PTR + 7 * 4 + PTR - 1) & ~(PTR - 1)
LINK_SIZE = PTR
LINK_WORDS = LINK_SIZE // 4

ARENA_SIZE = 1 << 18
MAX_BLOCKS = 64
FREE_WALK_MAX = 64
BASE = 1 << 24          # so that address 0 is never a real block

# The report strings, straight out of .rodata at 0x002a2ce0..0x002a3028 and
# 0x00324f80. They are also where bware's own names for the four flags are.
S_EXPANDED = "WARNING:  Expanded slot pool %s by %d slots" + NL
S_NOCLEAN = ("WARNING:  SlotPool::CleanupExpandedSlotPools() unable to cleanup"
             " %d expanded slots from %s" + NL)
S_NEWEARLY = ("WARNING:  SlotPoolManager::NewSlotPool(%s) called before "
              "SlotPoolManager::SlotPoolManager()" + NL)
S_DELUNINIT = ("WARNING:  SlotPoolManager::DeleteSlotPool(%s) called on "
               "unintialized SlotPoolManager." + NL)
S_NONEMPTY = ("WARNING:  DeleteSlotPool() called on nonempty SlotPool %s "
              "(%d slots allocated)" + NL)
S_HDR1 = "                                                   Num            Most" + NL
S_HDR2 = ("Name                                        Size   Slots  Alloc   "
          "Alloc  Overflow         Flags" + NL)
S_HDR3 = "=" * 114 + NL
S_ROW = "%-40s   %4dK   %4d   %4d   %4d   %4d    "
S_FLAG = ["  [FLAG_OVERFLOW_IF_FULL]", "  [ZERO_ALLOCATED_MEMORY]",
          "  [WARN_IF_OVERFLOW]", "  [WARN_IF_NONEMPTY_DELETE]"]

OVERFLOW_IF_FULL = 0x01
ZERO_ALLOCATED_MEMORY = 0x02
WARN_IF_OVERFLOW = 0x04
WARN_IF_NONEMPTY_DELETE = 0x08


def u32(x):
    return x & 0xffffffff


def i32(x):
    x &= 0xffffffff
    return x - (1 << 32) if x >= 0x80000000 else x


def sra2(x):
    """The EE's `addiu v0,x,3 / movn v0,x,(x>=0) / sra v0,v0,2` -- x/4 rounded
    toward zero, as at 0x0023fa5c and 0x0023f7d4."""
    return (x if x >= 0 else x + 3) >> 2


# ---------------------------------------------------------------- the arena

MEM = bytearray(ARENA_SIZE)
BLOCKS = []          # [base, bytes, live]
POOLS = {}           # base -> Pool
CURSOR = [0]
BUDGET = [MAX_BLOCKS]


def arena_reset(budget):
    del BLOCKS[:]
    POOLS.clear()
    CURSOR[0] = 0
    BUDGET[0] = budget
    MEM[:] = b"\xaa" * ARENA_SIZE


def arena_alloc(nbytes):
    need = (nbytes + 16 + 15) & ~15
    if (len(BLOCKS) >= BUDGET[0] or len(BLOCKS) >= MAX_BLOCKS
            or CURSOR[0] + need > ARENA_SIZE):
        return 0
    p = BASE + CURSOR[0]
    CURSOR[0] += need
    MEM[p - BASE:p - BASE + need] = b"\xcd" * need
    BLOCKS.append([p, nbytes, True])
    return p


def arena_release(block):
    for b in BLOCKS:
        if b[0] == block:
            b[2] = False
            return
    emit("!! released a block the arena never handed out")


def rd(a):
    return int.from_bytes(MEM[a - BASE:a - BASE + PTR], "little")


def wr(a, v):
    MEM[a - BASE:a - BASE + PTR] = int(v).to_bytes(PTR, "little")


def rdw(a):
    return int.from_bytes(MEM[a - BASE:a - BASE + 4], "little")


def wrw(a, v):
    MEM[a - BASE:a - BASE + 4] = u32(v).to_bytes(4, "little")


# --------------------------------------------------------------------- output

OUT = []


def emit(line):
    OUT.append(line)


def A(p):
    """A pointer as the block that holds it and the slot within it."""
    if not p:
        return "nil"
    for i, (base, nbytes, live) in enumerate(BLOCKS):
        if not base <= p < base + nbytes:
            continue
        off = p - base
        if not live:
            return "P%d!+%d" % (i, off)
        if off < HDR:
            return "P%d" % i if off == 0 else "P%d+%d" % (i, off)
        rel = off - HDR
        idx, rem = divmod(rel, POOLS[base].size)
        return "P%d#%d+%d" % (i, idx, rem) if rem else "P%d#%d" % (i, idx)
    return "??"


def dump_arena():
    """Which arena blocks are still checked out.

    Nothing else in the transcript says this. A(p) only reports a block's
    liveness while something still prints a pointer into it, and after a
    teardown nothing does -- so a bDeleteSlotPool that frees the head of an
    expansion chain and drops the rest reads identically to one that frees
    the lot.
    """
    emit("arena:"
         + "".join(" P%d=%s" % (i, "live" if b[2] else "free")
                   for i, b in enumerate(BLOCKS))
         + " (%d)" % len(BLOCKS))


LOG = [""]


def bprintf(text):
    LOG[0] += text


def flush_log():
    buf = LOG[0]
    cut = buf.rfind(NL)
    if cut < 0:
        return
    for line in buf[:cut].split(NL):
        emit("log| " + line)
    LOG[0] = buf[cut + 1:]


def end_log():
    flush_log()
    if LOG[0]:
        emit("log| %s <partial>" % LOG[0])
        LOG[0] = ""


# ------------------------------------------------------------- the allocator

class Pool(object):
    __slots__ = ("base", "next", "name", "free", "flags", "alloc", "most",
                 "mem", "num", "size", "total", "linked")


def new_slot_pool(slot_size, num_slots, name, mem_pool):
    """SlotPool::NewSlotPool, 0x0023f638. One bMalloc for the header and every
    slot; ten fields written; the eleventh and twelfth -- the list links at +0
    and +4 -- left as the heap gave them, which is the bug the port fixes."""
    base = arena_alloc(HDR + slot_size * num_slots)     # 0x0023f650, 0x0023f674
    if not base:
        return 0
    p = Pool()
    p.base = base
    p.size = slot_size          # 0x0023f684
    p.mem = mem_pool            # 0x0023f688
    p.name = name               # 0x0023f690
    p.total = num_slots         # 0x0023f694
    p.num = num_slots           # 0x0023f698
    p.free = 0                  # 0x0023f69c
    p.next = 0                  # 0x0023f6a0
    p.alloc = 0                 # 0x0023f6a4
    p.most = 0                  # 0x0023f6a8
    p.flags = 15                # 0x0023f6b0, from the 15 at 0x0023f680
    p.linked = False            # the port's NULL links; not in the original
    POOLS[base] = p
    flush_slot_pool(base)       # 0x0023f6ac
    return base


def delete_one(base):
    """SlotPool::DeleteSlotPool, 0x0023f6d8 -- one pool, not the chain."""
    if base:
        arena_release(base)


def flush_slot_pool(base):
    """SlotPool::FlushSlotPool, 0x0023f6f0. Every pool in the chain gets its
    own free list threaded through its own slots; only the head's is ever
    read again."""
    a = base
    while a:
        p = POOLS[a]
        s = a + HDR             # 0x0023f700
        p.free = s              # 0x0023f714
        for _ in range(p.num - 1):
            wr(s, s + p.size)   # 0x0023f728
            s += p.size
        wr(s, 0)                # 0x0023f740
        a = p.next              # 0x0023f718


def expand_slot_pool(base, n):
    """SlotPool::ExpandSlotPool, 0x0023f760. A whole second pool, spliced in
    right behind the head, with the head's free list hung off the end of the
    new one's."""
    p = POOLS[base]
    if p.flags & WARN_IF_OVERFLOW:                      # 0x0023f778
        bprintf(S_EXPANDED % (p.name, n))
    nb = new_slot_pool(p.size, n, p.name, p.mem)        # 0x0023f7a4
    if not nb:
        return 0                # the port's NULL check; not in the original
    q = POOLS[nb]
    old_free = p.free           # 0x0023f7b8
    q.next = p.next             # 0x0023f7c8
    p.total += n                # 0x0023f7e0
    p.next = nb                 # 0x0023f7e8
    last = sra2((n - 1) * p.size) * 4                   # 0x0023f7d8..0x0023f7ec
    wr(nb + HDR + last, old_free)                       # 0x0023f7fc
    q.flags = p.flags           # 0x0023f800
    p.free = q.free             # 0x0023f808
    q.free = 0                  # 0x0023f810
    return nb


def slot_omalloc(base):
    """SlotPool::Malloc, 0x0023fa28. Grows when empty and the flag allows it,
    then clears the slot if the other flag says so."""
    p = POOLS[base]
    s = p.free                                          # 0x0023fa38
    if s == 0 and (p.flags & OVERFLOW_IF_FULL):         # 0x0023fa48
        expand_slot_pool(base, sra2(p.num) + 1)         # 0x0023fa6c
        s = p.free                                      # 0x0023fa74
    if s == 0:
        return 0
    p.free = rd(s)                                      # 0x0023fa90
    if p.flags & ZERO_ALLOCATED_MEMORY:                 # 0x0023fa88
        for i in range(p.size >> 2):                    # 0x0023faa8
            wrw(s + 4 * i, 0)
    p.alloc += 1                                        # 0x0023fad8
    if p.most < p.alloc:                                # 0x0023fad0
        p.most = p.alloc
    return s


def slot_malloc(base):
    """SlotPool::FastMalloc, 0x0023faf8. No growth, no clearing -- but the
    high-water mark moves before the free list is even looked at."""
    p = POOLS[base]
    s = p.free                                          # 0x0023fafc
    v1 = p.alloc + 1                                    # 0x0023fb04
    if s == 0:
        return 0
    if p.most < v1:                                     # 0x0023fb0c
        p.most = v1
    p.free = rd(s)                                      # 0x0023fb1c
    p.alloc = v1                                        # 0x0023fb20
    return s


def slot_free(base, s):
    """SlotPool::Free, 0x0023fb30. Five instructions: no NULL check, no
    ownership check, no double-free check."""
    p = POOLS[base]
    wr(s, p.free)                                       # 0x0023fb3c
    p.free = s                                          # 0x0023fb40
    p.alloc -= 1                                        # 0x0023fb48


def slot_malloc_n(base, n):
    """SlotPool::Malloc(int, void**), 0x0023fb50. Hands back a run of the free
    list still chained together. Returns (head, last-or-None)."""
    p = POOLS[base]
    if n == 0:                                          # 0x0023fb70
        return 0, None
    if p.total - p.alloc < n:                           # 0x0023fb84
        if not (p.flags & OVERFLOW_IF_FULL):            # 0x0023fb98
            return 0, None
        k = sra2(p.num) + 1                             # 0x0023fbb8
        if k < n:                                       # 0x0023fbc4
            k = n
        expand_slot_pool(base, k)                       # 0x0023fbc0
    head = p.free                                       # 0x0023fb8c / 0x0023fbc8
    if head == 0:                                       # 0x0023fbd0
        return 0, None
    v1 = head
    if n - 1 > 0:                                       # 0x0023fbdc
        v1 = rd(v1)                                     # 0x0023fbe4
        walked = 0
        while True:
            if v1 == 0:                                 # 0x0023fbe8
                return 0, None
            walked += 1
            if walked >= n - 1:                         # 0x0023fbf0
                break
            v1 = rd(v1)                                 # 0x0023fbf8
    if v1 == 0:                                         # 0x0023fbfc
        return 0, None
    p.free = rd(v1)                                     # 0x0023fc0c
    wr(v1, 0)                                           # 0x0023fc14
    p.alloc += n                                        # 0x0023fc30
    if p.most < p.alloc:                                # 0x0023fc28
        p.most = p.alloc
    if p.flags & ZERO_ALLOCATED_MEMORY:                 # 0x0023fc3c
        q = head
        while q:                                        # 0x0023fc58
            nxt = rd(q)                                 # 0x0023fc68, before the clear
            # The original starts the word index at 1, which is half of a host
            # link. The port skips one pointer; the same four bytes on target.
            for i in range(LINK_WORDS, p.size >> 2):    # 0x0023fc70
                wrw(q + 4 * i, 0)
            q = nxt
    return head, v1


def slot_free_n(base, head, tail):
    """SlotPool::Free(void*, void*), 0x0023fcc0. Terminates the chain first so
    that counting it terminates too."""
    p = POOLS[base]
    wr(tail, 0)                                         # 0x0023fcc0
    cnt = 0
    if head:                                            # 0x0023fcc8
        v1 = head
        while True:
            v1 = rd(v1)                                 # 0x0023fcd8
            cnt += 1
            if v1 == 0:
                break
    wr(tail, p.free)                                    # 0x0023fd08
    p.free = head                                       # 0x0023fd0c
    p.alloc -= cnt                                      # 0x0023fd14


def owner_index(pool_base, slot):
    """The `(slot - 48 - pool) / slotSize` at 0x0023f894 and 0x0023f96c: an
    unsigned 32-bit divide whose quotient is then tested as signed, so a slot
    below the pool is rejected twice over."""
    return i32(u32(slot - HDR - pool_base) // POOLS[pool_base].size)


def cleanup_expanded(base):
    """SlotPool::CleanupExpandedSlotPools, 0x0023f820. Three passes: assume
    every expanded slot is busy, walk the head's free list crossing them off,
    then delete the expansions that came out at zero."""
    head = POOLS[base]
    first = head.next                                   # 0x0023f840
    if not first:
        return

    s = first                                           # 0x0023f858
    while s:
        POOLS[s].alloc = POOLS[s].num
        s = POOLS[s].next

    a2 = head.free                                      # 0x0023f84c
    while a2:                                           # 0x0023f880
        nxt = rd(a2)                                    # 0x0023f8a8, delay slot
        k = owner_index(first, a2)
        if 0 <= k < POOLS[first].num:                   # 0x0023f8b0
            POOLS[first].alloc -= 1                     # 0x0023f8c8
        else:
            a1 = POOLS[first].next                      # 0x0023f8d0
            while a1:                                   # 0x0023f8d4
                k = owner_index(a1, a2)
                if 0 <= k < POOLS[a1].num:              # 0x0023f8fc
                    POOLS[a1].alloc -= 1                # 0x0023f914
                    break
                a1 = POOLS[a1].next
        a2 = nxt

    s0 = first                                          # 0x0023f928
    s2 = base
    while s0:                                           # 0x0023f938
        s3 = POOLS[s0].next
        if POOLS[s0].alloc != 0:
            if head.flags & WARN_IF_OVERFLOW:           # 0x0023f9e0
                bprintf(S_NOCLEAN % (POOLS[s0].num, head.name))
        else:
            gone = POOLS[s0]
            v1 = head.free                              # 0x0023f940
            prev = None                                 # 0x0023f94c, &head->free
            removed = 0
            while v1:                                   # 0x0023f960
                nxt = rd(v1)                            # 0x0023f978
                k = i32(u32(v1 - HDR - s0) // gone.size)
                if 0 <= k < gone.num:                   # 0x0023f97c
                    if prev is None:
                        head.free = nxt                 # 0x0023f988
                    else:
                        wr(prev, nxt)
                    removed += 1                        # 0x0023f990
                else:
                    prev = v1                           # 0x0023f994
                v1 = nxt                                # 0x0023f998
            # 0x0023f9bc traps when `removed != gone.num`; it cannot fire
            # here, because pass two counted the same list the same way.
            POOLS[s2].next = s3                         # 0x0023f9c4
            head.total -= gone.num                      # 0x0023f9d0
            delete_one(s0)                              # 0x0023f9cc
            s0 = s2                                     # 0x0023f9d8
        s2 = s0                                         # 0x0023f9f8
        s0 = s3


# ----------------------------------------------------------------- the manager

class Manager(object):
    def __init__(self):
        self.initialized = 0
        self.pools = []


MGR = Manager()


def manager_init():
    """SlotPoolManager::SlotPoolManager, 0x0023fd18 -- an empty circular list
    and the sentinel word set to 1."""
    MGR.pools = []
    MGR.initialized = 1                                 # 0x0023fd3c


def manager_shutdown():
    """~SlotPoolManager, 0x0023fd40. The list is emptied and the sentinel
    cleared *before* ~bTList runs, so nothing on it is freed."""
    MGR.pools = []                                      # 0x0023fd5c, 0x0023fd68
    MGR.initialized = 0                                 # 0x0023fd60


def b_new_slot_pool(slot_size, num_slots, name, mem_pool):
    """SlotPoolManager::NewSlotPool, 0x0023fda8. The only place slotSize is
    rounded up to a multiple of four."""
    base = new_slot_pool((slot_size + 3) & ~3, num_slots, name, mem_pool)
    if not base:                                        # 0x0023fddc
        return 0
    if MGR.initialized != 1:                            # 0x0023fdf0
        bprintf(S_NEWEARLY % POOLS[base].name)
        return base
    MGR.pools.append(base)                              # 0x0023fe0c
    POOLS[base].linked = True
    return base


def b_delete_slot_pool(base):
    """SlotPoolManager::DeleteSlotPool, 0x0023fe40 -- unlink, warn, then free
    the head and everything it expanded into."""
    if not base:                                        # 0x0023fe50
        return
    p = POOLS[base]
    if MGR.initialized == 0:                            # 0x0023fe58
        bprintf(S_DELUNINIT % p.name)
    elif p.linked:              # the port's guard; the original always unlinks
        MGR.pools.remove(base)                          # 0x0023fe7c
        p.linked = False
    if (p.flags & WARN_IF_NONEMPTY_DELETE) and p.alloc > 0:     # 0x0023fe98
        bprintf(S_NONEMPTY % (p.name, p.alloc))
    s = base                                            # 0x0023fec8
    while s:
        nxt = POOLS[s].next
        delete_one(s)                                   # 0x0023fed0
        s = nxt


def b_delete_all_slot_pools():
    """Not in the original: the port's way of emptying the manager."""
    while MGR.pools:
        b_delete_slot_pool(MGR.pools[0])


def b_print_all_slot_pools():
    """SlotPoolManager::PrintAllSlotPools, 0x0023fef8. One row is up to six
    separate bPrintf calls and only the last ends the line."""
    bprintf(S_HDR1)
    bprintf(S_HDR2)
    bprintf(S_HDR3)
    for base in MGR.pools:
        p = POOLS[base]
        kb = i32(p.total * p.size)                      # 0x0023ff64
        kb = (kb if kb >= 0 else kb + 1023) >> 10       # 0x0023ff80
        bprintf(S_ROW % (p.name, kb, p.total, p.alloc, p.most,
                         p.total - p.num))
        for i in range(4):                              # 0x0023ff90..0x0023ffe8
            if p.flags & (1 << i):
                bprintf(S_FLAG[i])
        bprintf(NL)                                     # 0x0023fff8


def get_slot_number(base, slot):
    """SlotPool::GetSlotNumber, 0x0023f5c8 -- an unsigned divide of a signed
    difference, returned as an int."""
    return i32(u32(slot - base - HDR) // POOLS[base].size)


def get_slot(base, i):
    """SlotPool::GetSlot, 0x0023f5f0."""
    return base + HDR + i * POOLS[base].size


def is_full(base):
    p = POOLS[base]                                     # 0x0023f608
    return 1 if p.alloc == p.total else 0


def count_free(base):
    p = POOLS[base]                                     # 0x0023f620
    return p.total - p.alloc


def has_overflowed(base):
    p = POOLS[base]
    return 1 if p.total != p.num else 0


# ------------------------------------------------------------- state dumps

def dump_free(base):
    p = POOLS[base]
    if p.size < LINK_SIZE:
        emit("  free: <slot narrower than a host pointer, not walked>")
        return
    out = ["  free:"]
    q = p.free
    n = 0
    while q and n < FREE_WALK_MAX:
        out.append(" " + A(q))
        q = rd(q)
        n += 1
    if q:
        out.append(" ...(%d+, cycle or overlong)" % n)
    else:
        out.append(" (%d)" % n)
    emit("".join(out))


def dump_pool(base):
    if not base:
        emit("pool nil")
        return
    p = POOLS[base]
    emit("pool '%s' %s size=%d num=%d total=%d alloc=%d most=%d "
         "flags=0x%02x mem=%d next=%s"
         % (p.name, A(base), p.size, p.num, p.total, p.alloc, p.most,
            u32(p.flags), p.mem, A(p.next)))
    dump_free(base)


def dump_chain(base):
    out = ["chain:"]
    n = 0
    a = base
    while a:
        out.append(" %s[%d]" % (A(a), POOLS[a].num))
        n += 1
        a = POOLS[a].next
    out.append(" (%d)" % n)
    emit("".join(out))
    a = base
    while a:
        dump_pool(a)
        a = POOLS[a].next


def dump_slot(slot, slot_size):
    out = ["  slot %s link=%s payload:" % (A(slot), A(rd(slot)))]
    for i in range(LINK_WORDS, slot_size // 4):
        out.append(" %08x" % rdw(slot + 4 * i))
    emit("".join(out))


def fill_slot(slot, slot_size, seed, from_word):
    for i in range(from_word, slot_size // 4):
        wrw(slot + 4 * i, seed + i * 0x01010101)


# ------------------------------------------------------------------ helpers

def mk(slot_size, num_slots, name, mem_pool):
    p = b_new_slot_pool(slot_size, num_slots, name, mem_pool)
    emit("bNewSlotPool(%d, %d, '%s', %d) -> %s"
         % (slot_size, num_slots, name, mem_pool, A(p)))
    flush_log()
    return p


def omalloc(base, tag):
    s = slot_omalloc(base)
    emit("bSlotOMalloc(%s) -> %s   [%s]" % (A(base), A(s), tag))
    flush_log()
    return s


def fmalloc(base, tag):
    s = slot_malloc(base)
    emit("bSlotMalloc(%s) -> %s   [%s]" % (A(base), A(s), tag))
    flush_log()
    return s


def sfree(base, slot, tag):
    emit("bSlotFree(%s, %s)   [%s]" % (A(base), A(slot), tag))
    slot_free(base, slot)
    flush_log()


def counts(base):
    p = POOLS[base]
    emit("counts full=%d free=%d total=%d alloc=%d most=%d over=%d "
         "flags=0x%02x name='%s'"
         % (is_full(base), count_free(base), p.total, p.alloc, p.most,
            has_overflowed(base), u32(p.flags), p.name))


# ---------------------------------------------------------------- scenarios

def s_basic():
    p = mk(8, 4, "BASIC", 0)
    POOLS[p].flags &= ~ZERO_ALLOCATED_MEMORY
    POOLS[p].flags &= ~OVERFLOW_IF_FULL
    dump_pool(p)
    counts(p)

    s = [omalloc(p, "take") for _ in range(4)]
    dump_pool(p)
    counts(p)
    emit("one too many:")
    omalloc(p, "empty")

    for i in range(4):
        sfree(p, s[i], "give back in order")
    dump_pool(p)
    counts(p)

    s = [omalloc(p, "take again") for _ in range(4)]
    for i in range(3, -1, -1):
        sfree(p, s[i], "give back reversed")
    dump_pool(p)
    counts(p)

    b_delete_slot_pool(p)
    emit("deleted")
    end_log()


def s_queries():
    p = mk(12, 5, "QUERIES", 3)
    for i in range(-2, 7):
        s = get_slot(p, i)
        emit("bGetSlot(%2d) -> %-8s bGetSlotNumber -> %11d (0x%08x)"
             % (i, A(s), get_slot_number(p, s),
                u32(get_slot_number(p, s))))
    emit("one byte before the array: bGetSlotNumber -> %11d (0x%08x)"
         % (get_slot_number(p, get_slot(p, 0) - 1),
            u32(get_slot_number(p, get_slot(p, 0) - 1))))
    emit("one byte into slot 0:      bGetSlotNumber -> %11d"
         % get_slot_number(p, get_slot(p, 0) + 1))
    counts(p)
    slot_omalloc(p)
    counts(p)
    b_delete_slot_pool(p)
    end_log()


def s_rounding():
    for want in [1, 2, 3, 4, 5, 7, 8, 9, 12, 13, 16, 31, 32, 33]:
        p = mk(want, 3, "ROUND", 0)
        emit("asked %2d -> slotSize %2d, slot1 %s, slot2 %s"
             % (want, POOLS[p].size, A(get_slot(p, 1)), A(get_slot(p, 2))))
        dump_free(p)
        b_delete_slot_pool(p)
    end_log()


def s_zero():
    p = mk(16, 3, "ZERO", 0)
    emit("flags default 0x%02x" % u32(POOLS[p].flags))
    a = omalloc(p, "fresh, zeroed")
    dump_slot(a, 16)
    fill_slot(a, 16, 0x11111111, 0)
    dump_slot(a, 16)
    sfree(p, a, "back")
    dump_slot(a, 16)
    b = omalloc(p, "same slot, zeroed again")
    dump_slot(b, 16)

    emit("now with the flag off:")
    POOLS[p].flags &= ~ZERO_ALLOCATED_MEMORY
    fill_slot(b, 16, 0x22222222, 0)
    sfree(p, b, "back")
    b = omalloc(p, "dirty")
    dump_slot(b, 16)

    emit("FastMalloc never clears, whatever the flag says:")
    POOLS[p].flags |= ZERO_ALLOCATED_MEMORY
    fill_slot(b, 16, 0x33333333, 0)
    sfree(p, b, "back")
    b = fmalloc(p, "fast")
    dump_slot(b, 16)

    b_delete_slot_pool(p)
    end_log()


def s_fast():
    p = mk(8, 2, "FAST", 0)
    POOLS[p].flags &= ~ZERO_ALLOCATED_MEMORY
    s = [fmalloc(p, "fast") for _ in range(4)]
    dump_chain(p)
    counts(p)
    for i in range(2):
        sfree(p, s[i], "back")
    emit("and now the slow path, which grows:")
    for _ in range(4):
        omalloc(p, "slow")
    dump_chain(p)
    counts(p)
    b_delete_slot_pool(p)
    end_log()


def s_expand():
    p = mk(8, 8, "EXPAND", 2)
    POOLS[p].flags &= ~ZERO_ALLOCATED_MEMORY
    for _ in range(8):
        omalloc(p, "fill it")
    dump_chain(p)
    emit("the ninth grows it by numSlots/4 + 1 = %d:" % (8 // 4 + 1))
    omalloc(p, "grow")
    dump_chain(p)
    counts(p)
    for _ in range(9, 12):
        omalloc(p, "eat the expansion")
    dump_chain(p)
    emit("and again -- note numSlots is still the original 8:")
    omalloc(p, "grow again")
    dump_chain(p)
    counts(p)

    emit("with the flag off it just fails:")
    POOLS[p].flags &= ~OVERFLOW_IF_FULL
    for _ in range(13, 16):
        omalloc(p, "drain")
    omalloc(p, "no grow")
    dump_chain(p)

    emit("an explicit expand, flag or no flag:")
    expand_slot_pool(p, 3)
    dump_chain(p)
    counts(p)
    b_delete_slot_pool(p)
    end_log()


def s_warn():
    p = mk(8, 4, "WARN", 0)
    s = [omalloc(p, "fill and grow") for _ in range(6)]
    dump_chain(p)
    emit("hold one expanded slot, release the rest, then clean up:")
    for i in range(5):
        sfree(p, s[i], "back")
    cleanup_expanded(p)
    flush_log()
    dump_chain(p)
    sfree(p, s[5], "the last one")
    cleanup_expanded(p)
    flush_log()
    dump_chain(p)
    emit("deleting it while it still holds slots:")
    omalloc(p, "hold")
    b_delete_slot_pool(p)
    end_log()


def s_cleanup():
    p = mk(8, 4, "CLEANUP", 0)
    POOLS[p].flags &= ~ZERO_ALLOCATED_MEMORY
    s = [omalloc(p, "fill") for _ in range(10)]
    dump_chain(p)
    emit("free everything except the sixth slot handed out:")
    for i in range(len(s)):
        if i != 5:
            sfree(p, s[i], "back")
    dump_chain(p)
    cleanup_expanded(p)
    flush_log()
    emit("after cleanup:")
    dump_chain(p)
    counts(p)
    emit("release the survivor and clean up again:")
    sfree(p, s[5], "back")
    cleanup_expanded(p)
    flush_log()
    dump_chain(p)
    counts(p)
    emit("cleanup on a pool that never grew does nothing:")
    cleanup_expanded(p)
    dump_chain(p)
    b_delete_slot_pool(p)
    end_log()


def s_boundary():
    """The range test at 0x0023f894 / 0x0023f8e0 is half-open, so an address
    one slot array past an expanded pool belongs to nobody. bSlotFree checks
    nothing, so the harness puts one on the free list on purpose."""
    p = mk(8, 8, "BOUNDARY", 0)
    POOLS[p].flags &= ~ZERO_ALLOCATED_MEMORY
    s = [omalloc(p, "fill and grow") for _ in range(9)]
    g = POOLS[p].next
    dump_chain(p)

    emit("give back the one slot that came out of the expanded pool, so it "
         "is empty and cleanup should reclaim it:")
    sfree(p, s[8], "the expanded one")
    dump_chain(p)

    just_past = get_slot(g, POOLS[g].num)
    emit("%s ends at %s, which bGetSlotNumber calls slot %d of %d -- one "
         "too far:"
         % (A(g), A(just_past), get_slot_number(g, just_past), POOLS[g].num))
    sfree(p, just_past, "an address belonging to no pool")
    dump_pool(p)

    cleanup_expanded(p)
    flush_log()
    emit("after cleanup -- the stray address is still on the list, and the "
         "empty pool went anyway:")
    dump_chain(p)
    counts(p)
    b_delete_slot_pool(p)
    end_log()


def s_flush():
    p = mk(8, 3, "FLUSH", 0)
    POOLS[p].flags &= ~ZERO_ALLOCATED_MEMORY
    for _ in range(5):
        omalloc(p, "fill and grow")
    dump_chain(p)
    emit("flush:")
    flush_slot_pool(p)
    dump_chain(p)
    counts(p)
    emit("the expanded slots are now unreachable; taking 4 gives 3 and a "
         "grow:")
    for _ in range(4):
        omalloc(p, "after flush")
    dump_chain(p)
    b_delete_slot_pool(p)
    end_log()


def s_mallocn():
    p = mk(8, 6, "MALLOCN", 0)
    POOLS[p].flags &= ~ZERO_ALLOCATED_MEMORY

    last = 0
    head, got = slot_malloc_n(p, 0)
    if got is not None:
        last = got
    emit("bSlotMallocN(0) -> %s last=%s (untouched)" % (A(head), A(last)))
    flush_log()

    head, got = slot_malloc_n(p, 3)
    if got is not None:
        last = got
    emit("bSlotMallocN(3) -> %s last=%s" % (A(head), A(last)))
    flush_log()
    dump_pool(p)
    out = ["the chain it handed back:"]
    q = head
    while q:
        out.append(" " + A(q))
        q = rd(q)
    emit("".join(out))

    h2, _ = slot_malloc_n(p, 2)
    emit("bSlotMallocN(2, NULL) -> %s" % A(h2))
    flush_log()
    dump_pool(p)

    emit("asking for more than is left, with growth allowed:")
    l2 = 0
    h2, got = slot_malloc_n(p, 5)
    if got is not None:
        l2 = got
    emit("bSlotMallocN(5) -> %s last=%s" % (A(h2), A(l2)))
    flush_log()
    dump_chain(p)
    counts(p)

    emit("give the first three back as a chain:")
    slot_free_n(p, head, last)
    flush_log()
    dump_pool(p)
    counts(p)

    emit("hand back only part of a chain, which is what taking head and "
         "tail separately is for. Everything behind the named tail is "
         "dropped on the floor, and the counter moves by the length the "
         "walk found rather than the length the caller meant -- so the two "
         "have to agree, and the NULL store at 0x0023fcc0 is what makes "
         "them agree:")
    l2 = 0
    h2, got = slot_malloc_n(p, 4)
    if got is not None:
        l2 = got
    emit("bSlotMallocN(4) -> %s last=%s" % (A(h2), A(l2)))
    flush_log()
    q = rd(h2)
    emit("hand back %s..%s, abandoning %s onward" % (A(h2), A(q), A(rd(q))))
    slot_free_n(p, h2, q)
    flush_log()
    dump_pool(p)
    counts(p)

    emit("and with growth forbidden:")
    POOLS[p].flags &= ~OVERFLOW_IF_FULL
    h2, got = slot_malloc_n(p, 99)
    if got is not None:
        l2 = got
    emit("bSlotMallocN(99) -> %s" % A(h2))
    dump_pool(p)

    emit("a one-slot chain is its own tail:")
    h2, got = slot_malloc_n(p, 1)
    if got is not None:
        l2 = got
    emit("bSlotMallocN(1) -> %s last=%s" % (A(h2), A(l2)))
    slot_free_n(p, h2, l2)
    dump_pool(p)
    counts(p)
    b_delete_slot_pool(p)
    end_log()


def s_mallocnzero():
    p = mk(16, 4, "MALLOCNZ", 0)
    head, last = slot_malloc_n(p, 3)
    emit("bSlotMallocN(3) -> %s last=%s" % (A(head), A(last)))
    q = head
    while q:
        dump_slot(q, 16)
        q = rd(q)
    emit("dirty the payloads, give them back, take them again:")
    q = head
    while q:
        fill_slot(q, 16, 0xdead0000, LINK_WORDS)
        q = rd(q)
    slot_free_n(p, head, last)
    head, last = slot_malloc_n(p, 3)
    emit("bSlotMallocN(3) -> %s last=%s" % (A(head), A(last)))
    q = head
    while q:
        dump_slot(q, 16)
        q = rd(q)
    counts(p)
    b_delete_slot_pool(p)
    end_log()


def s_manager():
    emit("shutdown first, so the sentinel is clear:")
    manager_shutdown()
    early = mk(8, 2, "EARLY", 0)
    dump_pool(early)

    emit("init, then a normal pool:")
    manager_init()
    normal = mk(8, 2, "NORMAL", 0)
    b_print_all_slot_pools()
    flush_log()

    emit("deleting the early one is fine, it is just not on the list:")
    b_delete_slot_pool(early)
    flush_log()
    b_print_all_slot_pools()
    flush_log()

    emit("shutdown abandons the list without freeing anything:")
    manager_shutdown()
    b_print_all_slot_pools()
    flush_log()
    emit("deleting after shutdown warns instead of unlinking:")
    b_delete_slot_pool(normal)
    flush_log()

    emit("a fresh manager, three pools, then bDeleteAllSlotPools:")
    manager_init()
    mk(8, 2, "LATE_A", 0)
    mk(8, 2, "LATE_B", 0)
    mk(8, 2, "LATE_C", 0)
    b_print_all_slot_pools()
    flush_log()
    b_delete_all_slot_pools()
    b_print_all_slot_pools()
    end_log()


def s_print():
    a = mk(64, 100, "A_QUITE_LONG_POOL_NAME_TO_TEST_THE_COLUMN", 0)
    b = mk(8, 1, "B", 1)
    c = mk(1024, 40, "C", 2)

    POOLS[a].flags &= ~ZERO_ALLOCATED_MEMORY
    POOLS[a].flags &= ~WARN_IF_OVERFLOW
    POOLS[b].flags &= ~OVERFLOW_IF_FULL
    POOLS[b].flags &= ~WARN_IF_NONEMPTY_DELETE
    POOLS[c].flags &= ~0xf

    for _ in range(7):
        slot_omalloc(a)
    for i in range(3):
        slot_free(a, get_slot(a, i))
    for _ in range(6):
        slot_omalloc(c)
    flush_log()
    b_print_all_slot_pools()
    flush_log()

    emit("after growing A past its own slots:")
    POOLS[a].flags |= OVERFLOW_IF_FULL
    for _ in range(100):
        slot_omalloc(a)
    flush_log()
    b_print_all_slot_pools()
    flush_log()

    b_delete_slot_pool(a)
    b_delete_slot_pool(b)
    b_delete_slot_pool(c)
    end_log()


def s_oom():
    emit("the arena will hand out one block and no more:")
    arena_reset(1)
    p = mk(8, 4, "OOM", 0)
    dump_pool(p)
    q = mk(8, 4, "TOOBIG", 0)
    emit("second pool -> %s" % A(q))
    flush_log()
    emit("expanding the first -> %s" % A(expand_slot_pool(p, 4)))
    flush_log()
    for _ in range(6):
        omalloc(p, "drain past the end")
    dump_chain(p)
    counts(p)
    b_delete_slot_pool(p)
    end_log()


def s_abuse():
    p = mk(8, 3, "ABUSE", 0)
    q = mk(8, 2, "ELSEWHERE", 0)
    POOLS[p].flags &= ~ZERO_ALLOCATED_MEMORY
    POOLS[q].flags &= ~ZERO_ALLOCATED_MEMORY
    a = omalloc(p, "take")
    b = omalloc(p, "take")
    emit("free the same slot twice -- the free list closes on itself:")
    sfree(p, a, "once")
    sfree(p, a, "twice")
    dump_pool(p)
    counts(p)
    emit("taking it back opens the cycle again, one slot short:")
    omalloc(p, "take")
    dump_pool(p)
    counts(p)

    emit("free a slot that belongs to a different pool -- nothing checks, "
         "so it joins this pool's free list and will be handed out:")
    foreign = omalloc(q, "from the other pool")
    sfree(p, foreign, "foreign")
    dump_pool(p)
    counts(p)
    dump_pool(q)
    counts(q)
    emit("and out it comes:")
    omalloc(p, "take the foreign slot")
    dump_pool(p)

    sfree(p, b, "and the real one")
    dump_pool(p)
    counts(p)
    b_delete_slot_pool(p)
    b_delete_slot_pool(q)
    end_log()


def s_stress():
    p = mk(12, 5, "STRESS", 0)
    held = []
    seed = 12345

    for step in range(200):
        seed = u32(seed * 1664525 + 1013904223)
        r = (seed >> 16) & 0xff

        if r < 110 or not held:
            s = slot_omalloc(p)
            if s:
                held.append(s)
            emit("%3d take -> %s  (held %d)" % (step, A(s), len(held)))
        elif r < 220:
            k = (seed >> 8) % len(held)
            s = held[k]
            held[k] = held[-1]
            held.pop()
            slot_free(p, s)
            emit("%3d give %s     (held %d)" % (step, A(s), len(held)))
        elif r < 240:
            cleanup_expanded(p)
            emit("%3d cleanup      (held %d)" % (step, len(held)))
        else:
            emit("%3d state:" % step)
            dump_chain(p)
            counts(p)
        flush_log()
        if len(held) > 40:
            while held:
                slot_free(p, held.pop())
            emit("%3d drained" % step)

    dump_chain(p)
    counts(p)
    while held:
        slot_free(p, held.pop())
    cleanup_expanded(p)
    flush_log()
    dump_chain(p)
    counts(p)
    b_delete_slot_pool(p)
    end_log()


# ------------------------------------------------------------------- bPList

BPNODE_SIZE = 3 * PTR   # bNode's two links and the object: 12 on the EE
BPL = [0]               # bPNodeSlotPool, gp-15772


def bplist_init(n):
    """bPListInit, 0x002383f8: a pool only if there is none."""
    if not BPL[0]:                                      # 0x00238400
        BPL[0] = b_new_slot_pool(BPNODE_SIZE, n, "bPNode SlotPool", 16)


def bplist_close():
    """bPListClose, 0x00238430."""
    if BPL[0]:                                          # 0x00238438
        b_delete_slot_pool(BPL[0])
        BPL[0] = 0                                      # 0x00238448


def bpnode_malloc():
    """bPNode::Malloc, 0x00238458: a pool of 32 first, if there is none."""
    if not BPL[0]:                                      # 0x00238460
        bplist_init(32)
    return slot_omalloc(BPL[0])


def bpnode_free(s):
    """bPNode::Free, 0x00238488. With no pool the listing reaches a
    `break`; the scenario never frees into none."""
    slot_free(BPL[0], s)


def pnodes(what):
    emit("%s: bPNodeSlotPool %s" % (what, A(BPL[0])))
    flush_log()
    dump_pool(BPL[0])


def pmalloc(tag):
    s = bpnode_malloc()
    emit("bPNode::Malloc -> %s   [%s]" % (A(s), tag))
    flush_log()
    return s


def pfree(s, tag):
    emit("bPNode::Free(%s)   [%s]" % (A(s), tag))
    bpnode_free(s)
    flush_log()


def s_bplist():
    s = [0, 0, 0]
    pnodes("before")
    bplist_init(5)
    pnodes("bPListInit(5)")
    bplist_init(9)
    pnodes("bPListInit(9)")

    s[0] = pmalloc("first")
    s[1] = pmalloc("second")
    s[2] = pmalloc("third")
    dump_slot(s[1], BPNODE_SIZE)
    fill_slot(s[1], BPNODE_SIZE, 0x5a5a5a5a, 0)
    pfree(s[1], "dirty")
    s[1] = pmalloc("the dirty one again")
    dump_slot(s[1], BPNODE_SIZE)
    pfree(s[0], "back")
    pfree(s[2], "back")
    pnodes("two back")
    counts(BPL[0])

    bplist_close()
    pnodes("bPListClose, one still out")
    bplist_close()
    pnodes("bPListClose again")

    s[0] = pmalloc("no pool")
    pnodes("made by Malloc")
    pfree(s[0], "back")
    bplist_close()
    pnodes("closed")
    end_log()


SCENARIOS = [
    ("basic", s_basic),
    ("queries", s_queries),
    ("rounding", s_rounding),
    ("zero", s_zero),
    ("fast", s_fast),
    ("expand", s_expand),
    ("warn", s_warn),
    ("cleanup", s_cleanup),
    ("boundary", s_boundary),
    ("flush", s_flush),
    ("mallocn", s_mallocn),
    ("mallocnzero", s_mallocnzero),
    ("manager", s_manager),
    ("print", s_print),
    ("oom", s_oom),
    ("abuse", s_abuse),
    ("stress", s_stress),
    ("bplist", s_bplist),
]


def model(names):
    del OUT[:]
    for name, fn in SCENARIOS:
        if names and name not in names:
            continue
        arena_reset(MAX_BLOCKS)
        LOG[0] = ""
        manager_init()
        emit("scenario %s" % name)
        fn()
        # The arena's own account of what it still holds, which is the
        # only place a leaked expansion pool shows up.
        dump_arena()
    return NL.join(OUT) + NL


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", action="append",
                    help="run only this scenario (repeatable)")
    ap.add_argument("--dump", help="write both transcripts next to this path")
    args = ap.parse_args()

    names = args.scenario or []
    known = [s[0] for s in SCENARIOS]
    for n in names:
        if n not in known:
            sys.exit("unknown scenario: %s" % n)

    with tempfile.TemporaryDirectory() as tmp:
        exe = hostbuild.build(tmp, SOURCES, name="bslotpool_test")
        # A free list is a linked list with no bound on it, so a pool that has
        # been damaged -- by a mutation, or by a real mistake -- can leave
        # bCleanupExpandedSlotPools walking a cycle forever. Fail rather than
        # hang; a harness that does not finish is a difference too.
        try:
            r = subprocess.run([str(exe)] + names, capture_output=True,
                               text=True, timeout=120)
        except subprocess.TimeoutExpired:
            sys.exit("harness did not finish within 120s (a cycle in a free "
                     "list, most likely)")
        if r.returncode != 0:
            # A cygwin-built exe reports a fatal signal the POSIX way,
            # as signal << 8, and dies with nothing on stderr. Say so,
            # rather than leaving a bare 2816 to be decoded by hand.
            why = "exit %d" % r.returncode
            if r.returncode > 255 and r.returncode % 256 == 0:
                why = "killed by signal %d" % (r.returncode // 256)
            sys.exit("harness failed (%s):%s%s"
                     % (why, NL, r.stderr or "(nothing on stderr)"))
        port = r.stdout.replace(chr(13) + NL, NL)

    ours = model(names)

    if args.dump:
        with open(args.dump + ".port.txt", "w", newline=NL) as fh:
            fh.write(port)
        with open(args.dump + ".model.txt", "w", newline=NL) as fh:
            fh.write(ours)

    a = port.splitlines()
    b = ours.splitlines()
    diff = [ln for ln in difflib.unified_diff(a, b, "port", "model",
                                              lineterm="", n=1)]
    n = len([ln for ln in diff
             if ln[:1] in "+-" and not ln.startswith(("+++", "---"))])
    count = len(names) if names else len(SCENARIOS)
    print("%d scenarios, %d lines, %d differ" % (count, len(a), n))
    if diff:
        print(NL.join(diff[:120]))
        if len(diff) > 120:
            print("... %d more diff lines" % (len(diff) - 120))
    return 1 if diff else 0


if __name__ == "__main__":
    sys.exit(main())
