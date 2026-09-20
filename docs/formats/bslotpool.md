# bSlotPool -- the fixed-size block allocator

**Status: ported and cross-checked.** The port is
`3DS Files/source/bslotpool.c` / `.h`; `tools/bslotpool_check.py` holds it to
this document with 17 scenarios and 990 lines of transcript, diffed against a
Python model written from the disassembly rather than from the C, and
mutation-tested so that a checker which cannot fail does not get to claim a
pass. Every rule below carries the address it came from; where a claim rests
on something weaker than a direct reading, it says so.

`bSlotPool.obj` is `0x0023f508`-`0x00240198`, 3216 bytes, 34 symbols. It is
the engine's answer to "I need ten thousand of these and I need them now":
one heap allocation holds a header and every slot, a free list is threaded
through word 0 of the free slots, and allocating is three loads and two
stores with no search and no coalescing. Nothing is ever given back to the
heap except by deleting the whole pool, or by `CleanupExpandedSlotPools`
dropping an expansion that has gone quiet.

It sits directly on `bMalloc__FiPCcii` (`0x0023f0b8`), so on the 3DS it sits
on whatever `heapcfg.c` sized -- the port calls `malloc` by default and
takes a hook for anything else.

---

## Types

From the `.mdebug` STABS (`docs/mdebug_structs.txt:10445`, raw at
`docs/mdebug_raw_strings.txt:25543`):

```
SlotPool (52 bytes)                 SlotPoolManager (12 bytes)
  +0   bTNode<SlotPool>  (base)       +0   int  Initialized
  +8   SlotPool* NextSlotPool         +4   bTList<SlotPool> SlotPoolList
  +12  const char* DebugName
  +16  void* FreeSlots              SlotPoolEntry (4 bytes)
  +20  SlotPoolFlags Flags            +0   SlotPoolEntry* Next
  +24  int NumAllocatedSlots
  +28  int MostNumAllocatedSlots    bTNode<T> : bNode (8 bytes)
  +32  int MemoryPool                 +0   Next
  +36  int NumSlots                   +4   Prev
  +40  int SlotSize
  +44  int TotalNumSlots
  +48  void* Slots[1]
```

The 52 is the 48-byte header plus the one-element `Slots` array that stands
in for the slot block; `NewSlotPool` allocates `48 + numSlots * slotSize`
(`0x0023f674`) and every slot address in the object is computed as
`pool + 48 + i * slotSize`. **48, not 52.** `SlotPoolEntry` is bWare's name
for what a free slot looks like while it is free: one `Next`, nothing else.

The flag enum is recovered whole (`docs/mdebug_raw_strings.txt:25546`):

```
SlotPoolFlags:
  SLOTPOOL_FLAG_OVERFLOW_IF_FULL        1    grow instead of returning NULL
  SLOTPOOL_FLAG_ZERO_ALLOCATED_MEMORY   2    clear the slot on the way out
  SLOTPOOL_FLAG_WARN_IF_OVERFLOW        4    report every expand and cleanup
  SLOTPOOL_FLAG_WARN_IF_NONEMPTY_DELETE 8    report slots still held at delete
```

All four are on by default (`addiu v0,zero,15` at `0x0023f680`, stored at
`0x0023f6b0`), including in the retail build. The report strings at
`0x002a2fd0`-`0x002a3028` print them as `[FLAG_OVERFLOW_IF_FULL]`,
`[ZERO_ALLOCATED_MEMORY]`, `[WARN_IF_OVERFLOW]`,
`[WARN_IF_NONEMPTY_DELETE]` -- the first strips `SLOTPOOL_` and the other
three strip `SLOTPOOL_FLAG_`, which is bWare's own copy-paste slip and is
reproduced.

There are **two** `SlotPool` definitions in the debug info, type#122 and
type#128 (`docs/mdebug_raw_strings.txt:25543` and `:25544`). They are
identical except that only the second declares `Malloc(int, void**)` and
`Free(void*, void*)`, so the array overloads were added to the header partway
through the project and some translation units were compiled against the
older one. Nothing on the disc calls them.

---

## Layout of the object

| address | symbol | note |
|---------|--------|------|
| `0x0023f508` | `bNewSlotPool(int,int,const char*,int)` | forwarder |
| `0x0023f540` | `bDeleteSlotPool(SlotPool*)` | forwarder |
| `0x0023f550` | `bFlushSlotPool(SlotPool*)` | forwarder |
| `0x0023f558` | `bSlotMalloc(SlotPool*)` | to `FastMalloc` |
| `0x0023f578` | `bSlotOMalloc(SlotPool*)` | to `Malloc` |
| `0x0023f598` | `bSlotFree(SlotPool*,void*)` | forwarder |
| `0x0023f5a0` | `bSlotMalloc(SlotPool*,int,void**)` | forwarder |
| `0x0023f5c0` | `bSlotFree(SlotPool*,void*,void*)` | forwarder |
| `0x0023f5c8` | `SlotPool::GetSlotNumber` | |
| `0x0023f5f0` | `SlotPool::GetSlot` | |
| `0x0023f608` | `SlotPool::IsFull` | |
| `0x0023f620` | `SlotPool::CountFreeSlots` | |
| `0x0023f630` | `SlotPool::CountTotalSlots` | |
| `0x0023f638` | `SlotPool::NewSlotPool` | static member |
| `0x0023f6d8` | `SlotPool::DeleteSlotPool` | static member, one pool |
| `0x0023f6f0` | `SlotPool::FlushSlotPool` | |
| `0x0023f760` | `SlotPool::ExpandSlotPool` | |
| `0x0023f820` | `SlotPool::CleanupExpandedSlotPools` | |
| `0x0023fa28` | `SlotPool::Malloc` | |
| `0x0023faf8` | `SlotPool::FastMalloc` | |
| `0x0023fb30` | `SlotPool::Free` | |
| `0x0023fb50` | `SlotPool::Malloc(int,void**)` | |
| `0x0023fcc0` | `SlotPool::Free(void*,void*)` | |
| `0x0023fd18` | `SlotPoolManager::SlotPoolManager` | |
| `0x0023fd40` | `SlotPoolManager::~SlotPoolManager` | |
| `0x0023fda8` | `SlotPoolManager::NewSlotPool` | |
| `0x0023fe40` | `SlotPoolManager::DeleteSlotPool` | |
| `0x0023fef8` | `SlotPoolManager::PrintAllSlotPools` | |
| `0x00240028` | `SlotPoolManager::CleanupExpandedSlotPools` | |
| `0x00240070` | static destructor thunk for the global manager | |
| `0x00240080` | static constructor thunk for the global manager | |
| `0x00240090` | `~bTList<SlotPool>` | |
| `0x00240108` | `~SlotPool` | tail-calls `~bTNode<SlotPool>` |
| `0x00240190` | `~bTNode<SlotPool>` | tail-calls `~bNode` |

with three more compiler-emitted destructor/`operator delete` thunks between
`0x00240110` and `0x00240188` that nothing in this object reaches.

The global manager is at `0x00315268` (`lui/addiu 0x0031,21096`, e.g.
`0x0023f524`).

`GetName`, `GetFlags`, `SetFlag`, `ClearFlag`, `HasOverflowed`,
`CountAllocatedSlots` and `CountMostAllocatedSlots` are declared in the debug
info but no out-of-line body was emitted -- they are inlined everywhere. The
port provides the obvious bodies. `HasOverflowed` is the only one where the
obvious body is a guess; the evidence for `TotalNumSlots != NumSlots` is the
Overflow column of the report, which is `TotalNumSlots - NumSlots`
(`0x0023ff70`).

### Calling convention

`SlotPoolManager::NewSlotPool` takes five arguments and reads the fifth from
`t0` (`move a3,t0` at `0x0023fdd4`), which is the EE gcc ABI: `a0`-`a3` then
`t0`-`t3`.

---

## The layers

Three of them, in the order the object lays them out.

**The free functions** (`0x0023f508`-`0x0023f5c4`) exist only to name the
members; each is a jump or a call-and-return. `bSlotMalloc` goes to
`FastMalloc` and `bSlotOMalloc` goes to `Malloc`, which is the reverse of
what the names suggest and is the single easiest thing to get backwards in
this object.

**`SlotPool`** owns the slots and the expansion chain. Nothing here touches
the manager's list.

**`SlotPoolManager`** is one global with an `Initialized` sentinel and a
circular list of every pool made through it. It rounds `slotSize`, appends
and unlinks, and prints the table.

---

## SlotPool::NewSlotPool, `0x0023f638`

```
bytes = slotSize * numSlots + 48        0x0023f650, 0x0023f674
pool  = bMalloc(bytes, name, 0, memoryPool)
if (!pool) return NULL                  0x0023f67c
pool->SlotSize     = slotSize           0x0023f684
pool->MemoryPool   = memoryPool         0x0023f688
pool->DebugName    = name               0x0023f690
pool->TotalNumSlots= numSlots           0x0023f694
pool->NumSlots     = numSlots           0x0023f698
pool->FreeSlots    = NULL               0x0023f69c
pool->NextSlotPool = NULL               0x0023f6a0
pool->NumAllocatedSlots     = 0         0x0023f6a4
pool->MostNumAllocatedSlots = 0         0x0023f6a8
pool->Flags        = 15                 0x0023f6b0
FlushSlotPool(pool)                     0x0023f6ac
```

Ten fields. **The two `bTNode` links at +0 and +4 are not among them**, so a
pool starts life with whatever the heap left there. See the divergences
below; this is a real bug, not a curiosity.

The product at `0x0023f650` is a 32-bit signed `mult`, so a request big
enough to overflow it wraps into a small allocation and the pool hands out
slots that run off the end. The port widens it to `size_t`, which turns that
into an allocation failure.

## SlotPool::FlushSlotPool, `0x0023f6f0`

Threads a free list through a pool's slots, terminated with NULL, and then
**walks `NextSlotPool` and does the same to every pool in the chain**
(`0x0023f74c`). Each pool gets its own private list in its own `FreeSlots`.

Nothing ever reads a non-head pool's `FreeSlots` -- `Malloc` only ever looks
at the head's (`0x0023fa38`) -- so flushing a pool that has expanded strands
every expanded slot, and `NumAllocatedSlots` is not reset either. It is safe
where the original uses it, which is inside `NewSlotPool` on a chain one long,
and the retail build calls it nowhere else. Reproduced as shipped; the
`flush` scenario is that behaviour written down.

When `NumSlots` is 0 the loop is skipped but the terminating NULL is still
written at the slot base (`0x0023f744`), four bytes past the allocation.
Reproduced; nothing on the disc creates a zero-slot pool.

## SlotPool::ExpandSlotPool, `0x0023f760`

```
if (Flags & WARN_IF_OVERFLOW)  bPrintf("Expanded slot pool %s by %d slots")
grown = NewSlotPool(SlotSize, n, DebugName, MemoryPool)   0x0023f7a4
grown->NextSlotPool = this->NextSlotPool                  0x0023f7c8
this->TotalNumSlots += n                                  0x0023f7e0
this->NextSlotPool   = grown                              0x0023f7e8
*(grown + 48 + (n-1)*SlotSize) = this->FreeSlots          0x0023f7fc
grown->Flags     = this->Flags                            0x0023f800
this->FreeSlots  = grown->FreeSlots                       0x0023f808
grown->FreeSlots = NULL                                   0x0023f810
```

The new pool goes in immediately behind the head, so the chain ends up in
reverse order of creation. The new pool's ready-made free list is hung on the
front of the head's and the tail of it is stitched to what the head had, so
one expand costs no walking at all.

The warning is printed **before** the allocation, so an expand that fails
still logs. The `(n-1)*SlotSize` is rounded toward zero to a multiple of 4 by
a movn-guarded shift (`0x0023f7d8`-`0x0023f7ec`); `SlotSize` is already a
multiple of 4, so this is exactly `(n-1)*SlotSize`.

There is **no check that `grown` is non-NULL**. `0x0023f7c8` stores through
it four instructions after the call. On the PS2 this is survivable in the
sense that the heap never failed; on a handheld it is not, and the port
returns NULL instead. That is divergence 1.

## SlotPool::Malloc, `0x0023fa28` and FastMalloc, `0x0023faf8`

The two differ in exactly two things, and the `fast` and `zero` scenarios
exist to pin them down:

| | `Malloc` (`bSlotOMalloc`) | `FastMalloc` (`bSlotMalloc`) |
|---|---|---|
| empty pool | expands if `OVERFLOW_IF_FULL` | returns NULL |
| `ZERO_ALLOCATED_MEMORY` | clears the slot | ignores the flag |
| high-water mark | moved | moved |

The growth step is `NumSlots / 4 + 1` (`0x0023fa5c`-`0x0023fa70`), computed
from `NumSlots`, which never changes -- so the tenth expansion of an 8-slot
pool is still 3 slots, not a quarter of what the pool has grown to. The
divide rounds toward zero through a movn, so a pool of 1, 2 or 3 slots grows
by exactly 1.

`Malloc`'s zero-fill clears the **whole** slot including word 0
(`0x0023faa8`), which is safe because the link was read at `0x0023fa80`,
four instructions earlier.

`FastMalloc` computes `NumAllocatedSlots + 1` before it tests the free list
(`0x0023fb04`) but branches away to the return before storing it
(`0x0023fb00`), so an allocation that fails moves nothing.

## SlotPool::Free, `0x0023fb30`

Five instructions:

```
*slot = FreeSlots; FreeSlots = slot; NumAllocatedSlots--
```

No NULL check, no ownership check, no double-free check, no attempt to work
out which pool in the chain the slot came from -- it goes on the head's list
whatever it is. All three of the resulting hazards are real and reachable,
and the `abuse` scenario walks into each of them deliberately:

* **Double free** closes the list into a one-element cycle: `*slot = slot`.
  The pool then hands the same slot out forever and `NumAllocatedSlots` goes
  negative.
* **Freeing a foreign slot** puts another pool's memory on this pool's free
  list, and this pool will hand it out.
* **Freeing NULL** stores through address 0.

The port reproduces all three. It is tempting to add the checks, but this
allocator is on the hot path for particles and traffic, and a port that
silently tolerates a double free is a port that hides the bug rather than the
one that reproduces it.

## SlotPool::Malloc(int, void\*\*), `0x0023fb50`

Hands back `n` slots still chained together, with `*last` set to the tail.
No caller in the retail build.

The decision to grow comes from the accounting, not from the list:
`TotalNumSlots - NumAllocatedSlots < n` (`0x0023fb84`). It asks for the
larger of the usual quarter and `n` itself (`0x0023fbc4`, movn). Then it
walks `n-1` links, and if the list runs out on the way it returns NULL having
already... nothing, in fact: the walk is read-only, so a short list costs
only the expand that preceded it.

The zero pass (`0x0023fc58`) starts the word index at **1**, not 0. That is
what keeps the chain it is handing back walkable: the link word survives the
clear. Skipping one pointer rather than a literal four bytes is the same four
bytes on any 32-bit target and the only thing that works on an LP64 host --
divergence 3.

## SlotPool::Free(void\*, void\*), `0x0023fcc0`

Terminates the chain at `tail` **first** (`0x0023fcc0`, the very first
instruction), then counts from `head` until NULL, then splices. The
termination is what bounds the count; it also means a bad `tail` is stored
through before `head` is even looked at.

## SlotPool::CleanupExpandedSlotPools, `0x0023f820`

The most intricate function in the object, and the one a second
implementation earns its keep on. Three passes.

**Pass 1** (`0x0023f858`): for every pool in the expansion chain, set
`NumAllocatedSlots = NumSlots`. Assume everything is busy. An expansion
pool's counter is not maintained during normal use at all -- `Malloc` and
`Free` only ever touch the head's -- so cleanup reconstructs it.

**Pass 2** (`0x0023f880`): walk the head's free list. For each free slot,
find the first pool in the **expansion** chain that owns it and decrement
that pool's counter. The scan starts at the first expansion, never at the
head (`0x0023f888`), so the head's own free slots match nothing and are
skipped. After this pass every expansion's counter is its true in-use count.

Ownership is `(slot - 48 - pool) / SlotSize` as an **unsigned** divide
(`0x0023f894`) whose quotient is then tested with `bltz` and against
`NumSlots`. A slot below a pool produces a huge quotient and fails both
tests.

**Pass 3** (`0x0023f928`): for each expansion in order:

* counter non-zero: leave it, and if the head has `WARN_IF_OVERFLOW`, log
  `unable to cleanup %d expanded slots from %s` -- with the *head's* name and
  the *expansion's* `NumSlots` (`0x0023f9ec`, `0x0023f9f4`).
* counter zero: walk the head's free list again and splice out every slot
  belonging to this pool (`0x0023f960`-`0x0023f998`), keeping the rest in
  order; then unlink the pool from the chain, subtract its `NumSlots` from
  the head's `TotalNumSlots`, and free it.

The splice keeps a pointer to the *previous link location* rather than to the
previous node, which is why removing a run of consecutive entries works. The
`move a2,v1` at `0x0023f994` is reached from both the hit and the miss path
and is a no-op on the hit path, which is easy to misread as "advance the
previous pointer even when we removed a node" -- it is not.

`0x0023f9bc` is a `break` -- a trap -- taken when the number of slots spliced
out does not equal the pool's `NumSlots`. The two passes use identical
arithmetic over the same list, so it cannot fire unless the free list has
been corrupted. The port logs and keeps the pool instead of taking the
console down: divergence 4, and it is unreachable in all 16 scenarios.

Note what cleanup does **not** do: it never touches the head pool's
`NumAllocatedSlots`. After a cleanup the head's counter still describes the
whole chain, while each surviving expansion's counter describes only itself.
The `cleanup` and `warn` scenarios both check that.

---

## The manager

**Constructor** (`0x0023fd18`): writes bTNode's poison 3 into both links,
then makes the list head point at itself both ways, then sets
`Initialized = 1`.

**`NewSlotPool`** (`0x0023fda8`): rounds `slotSize` up to a multiple of 4
(`(n+3) & ~3`, `0x0023fdac`/`0x0023fdcc`) -- **this is the only place
rounding happens anywhere in the object**, which is what keeps the free-list
threading word-exact. Then `SlotPool::NewSlotPool`, then: if
`Initialized != 1`, print `called before SlotPoolManager::SlotPoolManager()`
and return the pool **unlinked**; otherwise append it at the tail.

Note the asymmetry: `NewSlotPool` tests `Initialized != 1` (`0x0023fdf0`)
and `DeleteSlotPool` tests `Initialized == 0` (`0x0023fe58`). Identical for a
sentinel that is only ever 0 or 1; kept as written.

**`DeleteSlotPool`** (`0x0023fe40`): if the manager is down, warn
(`called on unintialized SlotPoolManager.` -- bWare's typo, kept); otherwise
unlink and poison both links with 11. Then, if `WARN_IF_NONEMPTY_DELETE` and
`NumAllocatedSlots > 0`, warn. Then free the head pool and the whole
expansion chain behind it (`0x0023fec0`).

The unlink at `0x0023fe7c` is **unconditional** when the manager is up, which
combines with `NewSlotPool` never initialising +0/+4 to give the crash the
`manager` scenario found: create a pool while the sentinel is clear (legal,
explicitly supported, prints a warning and hands the pool back), bring the
manager up, delete the pool, and the unlink stores through two words of heap
garbage. The port clears the links at creation and skips the unlink when they
are clear -- divergence 2. This was found by the harness, not by reading.

**Destructor** (`0x0023fd40`): sets the list head to point at itself and
clears `Initialized`, **and only then** calls `~bTList<SlotPool>`, which
therefore walks an empty list. **Nothing is freed.** Every pool made through
the manager is leaked at shutdown, by construction. On a console that is
about to reset this is free; the port keeps the behaviour and adds
`bDeleteAllSlotPools` for callers that want the other thing.

**`PrintAllSlotPools`** (`0x0023fef8`) is **compiled into the retail build,
not stubbed** -- it has an out-of-line address, a 304-byte body (`0x0023fef8`-`0x00240028`) and its
format strings sit in `.rodata` with the rest of the module's. So the
high-water mark this allocator keeps was readable on a shipped disc, and the
port keeps the whole debug path rather than eliding it. Three header lines,
then one row per pool built out of **up to six separate `bPrintf` calls** -- the row, then one
per set flag, then a bare `"\n"` (`0x0023fff8`). Anything that captures
`bPrintf` a call at a time has to buffer, which is why the harness prints
`log|` lines only when a newline arrives.

The Size column is `TotalNumSlots * SlotSize` bytes divided by 1024 rounding
toward zero (`0x0023ff64`-`0x0023ff88`), from a 32-bit signed product; the
Num Slots column is `TotalNumSlots`, not `NumSlots`; the Overflow column is
`TotalNumSlots - NumSlots`.

---

## Divergences in the port

Four, all of them documented in the source at the point of divergence, and
all four are also why the Python model is not simply "the C again":

1. **`ExpandSlotPool` checks its allocation** and returns NULL
   (`0x0023f7c8` stores through it unconditionally). Every caller already
   copes, because they all re-read `FreeSlots` afterwards.
2. **A new pool's list links start NULL, and unlinking a pool that was never
   linked does nothing** (`0x0023f684`-`0x0023f6b0` never writes them;
   `0x0023fe7c` unlinks unconditionally).
3. **The array-allocate zero pass skips one pointer, not a literal four
   bytes** (`0x0023fc58`). Identical on target.
4. **The trap at `0x0023f9bc` becomes a log line** and the pool is kept.

And two widenings that are not behaviour changes on target: the allocation
size is computed in `size_t` rather than a 32-bit signed `mult`, and the free
slot's link is `sizeof(void*)` wide rather than a literal 4.

Everything else is reproduced, including the things that look like bugs:
`FlushSlotPool` stranding an expansion's slots, the growth step being
computed from `NumSlots` forever, `Free` checking nothing, the manager
freeing nothing at shutdown, and the flag-name inconsistency in the report.

---

## Cross-check

`tools/bslotpool_check.py` builds `tools/src/bslotpool_test.c` against the
port, runs 17 scripted scenarios, and diffs the transcript against a Python
model of the same 34 symbols written from the listing above.

```
17 scenarios, 990 lines, 0 differ   (37/37 mutations caught)
```

An allocator has no return value worth checking on its own, so what is
compared is the sequence: after each step both sides print the pool chain,
the free list in order, and the six counters. The scenarios are `basic`,
`queries`, `rounding`, `zero`, `fast`, `expand`, `warn`, `cleanup`,
`boundary`, `flush`, `mallocn`, `mallocnzero`, `manager`, `print`, `oom`,
`abuse` and a 200-step `stress` driven by an LCG. Each one ends with an
`arena:` line naming every block the arena handed out and whether it is still
checked out -- see the mutation note below for why that line exists.

Two arrangements make a 64-bit host able to stand in for the 3DS:

* **Addresses are never printed raw.** The allocator hook is pointed at a
  bump arena that registers every block, and a pointer prints as the block
  and the slot within it: `P2#5` is slot 5 of the third block this scenario
  allocated, `P2#5+3` three bytes into it, `P2` a header, `P2!+0` a released
  block, `??` an address in no block. The model computes its header size from
  the host's pointer width the same way the port's struct does -- five
  pointers then seven 32-bit words, which is 72 on this host and exactly the
  PS2's 48 when a pointer is 4 bytes wide.
* **Slot contents print as the link plus the payload after it**, never as a
  flat word dump, because the link is 8 bytes here and 4 on target; and a
  pool whose `slotSize` is under a pointer wide is never walked. Fresh blocks
  are filled with `0xCD` so an uninitialised word reads differently from a
  zeroed one, released blocks are never reused, and the arena's capacity is a
  block count rather than a byte count.

### Mutation test

37 single-edit changes to the port, each expected to move the diff. All 37
are caught:

```bash
python tools/bslotpool_mutate.py          # ~20 minutes, one build per mutation
```

Unlike the bvector and bmath runners, this one is kept. The mutation set is
a list of every behavioural claim the module makes, in a form that fails
loudly when one of them stops being checked, and rebuilding it from nothing
cost a session. Six of the 37 are caught by the harness dying rather than by
a transcript difference -- a mutation that breaks the free list makes the
harness walk a bad pointer -- which is a detection, but a less informative
one than a diff.

**One real hole, found by the mutation that made `bDeleteSlotPool` free only
the head of an expansion chain and drop the rest: 0 lines differed.** The
transcript reported a block's liveness only as a side effect of printing a
pointer into it (`P2!+0`), and after a teardown nothing prints one, so a
leaked expansion pool was invisible. Both sides now end every scenario with
an `arena:` line stating it outright, and the mutation moves 10 lines.

**One equivalent mutant, deliberately not counted.** `bNewSlotPool` tests the
manager's sentinel against 1 while `bDeleteSlotPool` tests it against 0
(`0x0023fdf0` vs `0x0023fe40`); the port keeps the asymmetry because the ROM
has it. Only `bSlotPoolManagerInit` and `bSlotPoolManagerShutdown` ever write
that field, and it is file-static, so it is never anything but 0 or 1 and the
two spellings cannot be told apart from outside. It is recorded in the
runner's `EQUIVALENT` list so a later session does not re-add it as a miss.

Two mutations were defective rather than uncaught, and are worth naming
because both looked like deck holes at first:

* clobbering only `node.next` in `new_pool` left `node.prev` NULL, so
  `list_remove`'s guard still fired and the mutant behaved exactly like the
  port. The divergence being tested is that *both* links start as garbage in
  the original; mutating both segfaults, as it should.
* dropping the `oldFree` splice in `bExpandSlotPool` left the variable
  unused, so `-Wall` caught it before the checker could. A mutation the
  compiler rejects tests the compiler, not the cross-check.
