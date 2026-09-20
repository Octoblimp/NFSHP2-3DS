#!/usr/bin/env python3
"""Mutation-test `tools/bslotpool_check.py`.

A cross-check that cannot fail proves nothing. Every entry in MUTANTS below
is one single-edit change to `3DS Files/source/bslotpool.c`, and the check is
expected to notice: a non-zero `differ` count, or a run that does not finish
at all, because a mutation that corrupts a free list makes the harness walk a
bad pointer. Both count. A mutation that changes nothing is either a hole in
the test deck or an equivalent mutant, and the difference matters -- see
EQUIVALENT.

```
python tools/bslotpool_mutate.py                # the whole set, ~20 minutes
python tools/bslotpool_mutate.py flush-head-only cleanup-prev-advances
python tools/bslotpool_mutate.py --list
```

This edits a tracked source file in place and puts it back in a `finally`,
so an ordinary failure or a Ctrl-C leaves the tree clean. A hard kill does
not run that, which is what `.mutate-backup` is for: it holds the original
while a run is in flight, and the next run refuses to start until the tree
has been restored from it.

Why this lives in `tools/` when the bvector and bmath runners did not: those
were written in a scratchpad and thrown away, and rebuilding this one from
nothing cost a session. The mutation set is the part worth keeping -- it is
a list of every behavioural claim the module makes, in a form that fails
loudly when one of them stops being checked.
"""
import os
import re
import subprocess
import sys

NL = chr(10)
SRC = "3DS Files/source/bslotpool.c"
BACKUP = SRC + ".mutate-backup"
CHECK = [sys.executable, "tools/bslotpool_check.py"]

# (name, old, new) -- `old` must occur exactly once.
MUTANTS = [
    # ---------------------------------------------------------- life cycle
    ("round-slotsize",
     "new_pool((slotSize + 3) & ~3, numSlots, name,",
     "new_pool(slotSize, numSlots, name,"),
    ("flush-short-by-one",
     "int   last = pool->numSlots - 1;",
     "int   last = pool->numSlots - 2;"),
    ("flush-head-only",
     "        pool = pool->nextSlotPool;",
     "        pool = NULL;"),
    ("newpool-links-garbage",
     "    pool->node.next             = NULL;   // not in the original; see above" + NL
     + "    pool->node.prev             = NULL;",
     "    pool->node.next             = (BSlotPoolNode*)(uintptr_t)3;" + NL
     + "    pool->node.prev             = (BSlotPoolNode*)(uintptr_t)3;"),
    ("delete-head-only",
     "    while (pool) {" + NL
     + "        next = pool->nextSlotPool;" + NL
     + "        delete_one(pool);",
     "    while (pool) {" + NL
     + "        next = NULL;" + NL
     + "        delete_one(pool);"),

    # ---------------------------------------------------------- the list
    ("list-append-at-head",
     "    tail->next      = &pool->node;" + NL
     + "    g_mgr.head.prev = &pool->node;" + NL
     + "    pool->node.prev = tail;" + NL
     + "    pool->node.next = &g_mgr.head;",
     "    BSlotPoolNode* head = g_mgr.head.next;" + NL
     + "    (void)tail;" + NL
     + "    g_mgr.head.next = &pool->node;" + NL
     + "    head->prev      = &pool->node;" + NL
     + "    pool->node.prev = &g_mgr.head;" + NL
     + "    pool->node.next = head;"),
    ("list-remove-no-guard",
     "    if (!next || !prev) {" + NL
     + "        return;   // never linked -- see the note on new_pool",
     "    if (0) {" + NL
     + "        return;   // never linked -- see the note on new_pool"),

    # ---------------------------------------------------------- allocation
    ("malloc-no-expand",
     "    if (!slot && (pool->flags & BSP_OVERFLOW_IF_FULL)) {",
     "    if (0) {"),
    ("malloc-zero-skips-link",
     "        int words = pool->slotSize / 4;",
     "        int words = pool->slotSize / 4 - 1;"),
    ("fastmalloc-no-highwater",
     "    pool->freeSlots = slot_link_get(slot);" + NL
     + "    note_high_water(pool, pool->numAllocatedSlots + 1);" + NL
     + "    return slot;",
     "    pool->freeSlots = slot_link_get(slot);" + NL
     + "    pool->numAllocatedSlots += 1;" + NL
     + "    return slot;"),
    ("highwater-tracks-current",
     "    if (pool->mostNumAllocatedSlots < allocated) {" + NL
     + "        pool->mostNumAllocatedSlots = allocated;" + NL
     + "    }",
     "    pool->mostNumAllocatedSlots = allocated;"),
    ("free-no-decrement",
     "    pool->freeSlots = slot;" + NL
     + "    pool->numAllocatedSlots -= 1;",
     "    pool->freeSlots = slot;"),
    ("grow-by-no-plus-one",
     "    return pool->numSlots / 4 + 1;",
     "    return pool->numSlots / 4 + 2;"),

    # ---------------------------------------------------------- expansion
    ("expand-total-assign",
     "    pool->totalNumSlots += n;",
     "    pool->totalNumSlots = n;"),
    ("expand-splice-first-slot",
     "    lastSlot = (char*)slot_base(grown) + (ptrdiff_t)(n - 1) * grown->slotSize;",
     "    lastSlot = (char*)slot_base(grown);"),
    ("expand-drops-old-free",
     "    slot_link_set(lastSlot, oldFree);",
     "    (void)oldFree; slot_link_set(lastSlot, NULL);"),
    ("expand-keeps-old-head",
     "    pool->freeSlots  = grown->freeSlots;",
     "    pool->freeSlots  = oldFree;"),

    # ---------------------------------------------------------- MallocN
    ("mallocn-grow-test-off",
     "    if (pool->totalNumSlots - pool->numAllocatedSlots < n) {",
     "    if (pool->totalNumSlots - pool->numAllocatedSlots <= n) {"),
    ("mallocn-no-grow-max",
     "        if (grow < n) {" + NL
     + "            grow = n;" + NL
     + "        }",
     "        if (0) {" + NL
     + "            grow = n;" + NL
     + "        }"),
    ("mallocn-clears-link",
     "        int   keep  = BSLOTPOOL_LINK_SIZE;",
     "        int   keep  = 0;"),
    ("freen-count-off",
     "    for (p = head; p; p = slot_link_get(p)) {" + NL
     + "        n++;" + NL
     + "    }",
     "    for (p = head; p; p = slot_link_get(p)) {" + NL
     + "        n++;" + NL
     + "    }" + NL
     + "    n--;"),

    # ---------------------------------------------------------- queries
    ("slotnumber-signed-divide",
     "    return (int)(off / (uint32_t)pool->slotSize);",
     "    return (int)((int32_t)off / pool->slotSize);"),
    ("isfull-against-numslots",
     "    return pool->numAllocatedSlots == pool->totalNumSlots;",
     "    return pool->numAllocatedSlots == pool->numSlots;"),
    ("countfree-against-numslots",
     "    return pool->totalNumSlots - pool->numAllocatedSlots;",
     "    return pool->numSlots - pool->numAllocatedSlots;"),
    ("overflowed-against-total",
     "    return pool->totalNumSlots != pool->numSlots;",
     "    return pool->totalNumSlots != pool->numAllocatedSlots;"),

    # ---------------------------------------------------------- cleanup
    ("owner-range-inclusive",
     "        if ((int32_t)idx >= 0 && (int32_t)idx < p->numSlots) {",
     "        if ((int32_t)idx >= 0 && (int32_t)idx <= p->numSlots) {"),
    ("cleanup-pass1-from-head",
     "    for (p = first; p; p = p->nextSlotPool) {" + NL
     + "        p->numAllocatedSlots = p->numSlots;",
     "    for (p = pool; p; p = p->nextSlotPool) {" + NL
     + "        p->numAllocatedSlots = p->numSlots;"),
    ("cleanup-pass2-from-head",
     "        BSlotPool* owner = owner_of(first, slot);",
     "        BSlotPool* owner = owner_of(pool, slot);"),
    ("cleanup-unlink-from-head",
     "            prev->nextSlotPool = next;",
     "            pool->nextSlotPool = next;"),
    ("cleanup-total-by-one",
     "            pool->totalNumSlots -= p->numSlots;",
     "            pool->totalNumSlots -= 1;"),
    ("cleanup-prev-advances",
     "            p = prev;                        // 0x0023f9d8: prev does not move",
     "            p = next;"),

    # ---------------------------------------------------- the printed rows
    ("print-kilobytes-1000",
     "        bsp_printf(BSP_ROW, p->debugName, (int)(bytes / 1024),",
     "        bsp_printf(BSP_ROW, p->debugName, (int)(bytes / 1000),"),
    ("print-alloc-columns-swapped",
     "                   (int)p->totalNumSlots, (int)p->numAllocatedSlots," + NL
     + "                   (int)p->mostNumAllocatedSlots,",
     "                   (int)p->totalNumSlots, (int)p->mostNumAllocatedSlots," + NL
     + "                   (int)p->numAllocatedSlots,"),
    ("print-overflow-negated",
     "                   (int)(p->totalNumSlots - p->numSlots));",
     "                   (int)(p->numSlots - p->totalNumSlots));"),
    ("noclean-prints-allocated",
     "                bsp_printf(BSP_NOCLEAN, (int)p->numSlots, pool->debugName);" + NL
     + "            }" + NL
     + "        } else {",
     "                bsp_printf(BSP_NOCLEAN, (int)p->numAllocatedSlots, pool->debugName);" + NL
     + "            }" + NL
     + "        } else {"),
    ("nonempty-prints-total",
     "        bsp_printf(BSP_NONEMPTY, pool->debugName," + NL
     + "                   (int)pool->numAllocatedSlots);",
     "        bsp_printf(BSP_NONEMPTY, pool->debugName," + NL
     + "                   (int)pool->totalNumSlots);"),
    ("print-skips-flag-newline",
     "        bsp_printf(BSP_NEWLINE);",
     "        (void)0;"),
]

# Changes that cannot be caught, and should not be re-added to MUTANTS by a
# later session wondering why they are missing. Each is listed with the reason
# it is an equivalent mutant rather than a hole in the test deck.
EQUIVALENT = [
    # bNewSlotPool tests the sentinel against 1 and bDeleteSlotPool tests it
    # against 0. The port keeps that asymmetry because the ROM has it, but
    # nothing can set the sentinel to anything but 0 or 1 -- only
    # bSlotPoolManagerInit and bSlotPoolManagerShutdown write it, and the
    # struct is file-static -- so the two spellings agree on every reachable
    # state. A scenario cannot separate them; only a debugger could.
    ("sentinel-asymmetry",
     "    if (g_mgr.initialized != 1) {",
     "    if (!g_mgr.initialized) {"),
]


def read():
    # newline="" keeps the file's own line endings intact on the round trip;
    # bslotpool.c is LF and must stay that way.
    with open(SRC, "r", newline="") as fh:
        return fh.read()


def write(text):
    with open(SRC, "w", newline="") as fh:
        fh.write(text)


def backup_take(original):
    """Park the pristine source where a killed run can be recovered from."""
    if os.path.exists(BACKUP):
        sys.exit("%s already exists, which means a previous run was killed "
                 "while the source was mutated. Compare it against %s and "
                 "restore by hand, then delete it." % (BACKUP, SRC))
    with open(BACKUP, "w", newline="") as fh:
        fh.write(original)


def backup_drop():
    if os.path.exists(BACKUP):
        os.remove(BACKUP)


def run_check():
    """-> (label, caught, warned).

    `caught` means the cross-check noticed: either a non-zero differ count or
    a run that did not finish. `warned` means the mutant did not compile
    cleanly -- that is a defect in the mutation, not a result, because a
    warning is the compiler catching it rather than the checker.

    The label has to be picked carefully. hostbuild prints `compiler
    warnings:` as the *first* line of stdout and keeps going, so reading line
    1 reports the warning and hides why the run actually stopped.
    """
    try:
        r = subprocess.run(CHECK, capture_output=True, text=True, timeout=900)
    except subprocess.TimeoutExpired:
        return "did not finish in 900s", True, False

    out = (r.stdout or "") + (r.stderr or "")
    warned = "compiler warnings:" in out

    for line in out.splitlines():
        m = re.search(r"([0-9]+) differ", line)
        if m:
            n = int(m.group(1))
            return "%d lines differ" % n, n > 0, warned

    # No differ line: the check exited before it got that far. Take the line
    # that says why -- not line 1, which is the compiler's, and not the last
    # line, which is whatever the harness's stderr trailed off with.
    lines = [ln.strip() for ln in out.strip().splitlines() if ln.strip()]
    reason = "no differ line"
    for line in lines:
        if line.startswith(("harness failed", "compile failed",
                            "harness did not finish")):
            reason = line.rstrip(":")
            break
    else:
        for line in reversed(lines):
            if not line.startswith("compiler warnings:"):
                reason = line
                break
    return reason[:60], r.returncode != 0, warned


def main():
    only = [a for a in sys.argv[1:] if not a.startswith("-")]

    if "--list" in sys.argv[1:]:
        for name, _, _ in MUTANTS:
            print(name)
        for name, _, _ in EQUIVALENT:
            print("%s   (equivalent, not counted)" % name)
        return 0

    original = read()
    unknown = [a for a in only
               if a not in [m[0] for m in MUTANTS]]
    if unknown:
        sys.exit("unknown mutation: %s" % ", ".join(unknown))

    # Both lists are validated, not just the ones about to run: a pattern
    # that has rotted away from the source is the failure this catches, and
    # it is silent if only the selected ones are checked.
    for name, old, new in MUTANTS + EQUIVALENT:
        if old not in original:
            sys.exit("pattern for %s does not match the source" % name)
        if original.count(old) != 1:
            sys.exit("pattern for %s matches %d times"
                     % (name, original.count(old)))

    label, caught, warned = run_check()
    print("%-30s %s" % ("(baseline)", label))
    if caught or warned:
        sys.exit("baseline does not pass clean; fix that first")

    results = []
    backup_take(original)
    try:
        for name, old, new in MUTANTS:
            if only and name not in only:
                continue
            write(original.replace(old, new))
            label, caught, warned = run_check()
            results.append((name, label, caught, warned))
            print("%-30s %-34s %s%s"
                  % (name, label, "caught" if caught else "MISSED",
                     "  (does not compile clean)" if warned else ""))
    finally:
        write(original)
        backup_drop()

    n = len(results)
    got = len([r for r in results if r[2]])
    print("")
    print("%d/%d mutations caught" % (got, n))
    missed = [r[0] for r in results if not r[2]]
    if missed:
        print("missed: %s" % ", ".join(missed))
    warns = [r[0] for r in results if r[3]]
    if warns:
        print("did not compile clean: %s" % ", ".join(warns))
    return 0 if got == n and not warns else 1


if __name__ == "__main__":
    sys.exit(main())
