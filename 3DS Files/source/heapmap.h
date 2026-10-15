// heapmap -- the malloc heap in pieces, walked from newlib's own chunks.
//
// mallinfo() says how much is free, not in how many pieces. The track's
// bundles are single blocks of up to 9 MB (heapcfg.c), and a second race
// can find 21 MB free and no 5 MB of it in one piece: bMalloc's abort,
// "5034396 bytes for TRACKS\TEX11LOCATION.BIN", on a wireless Next Race
// (Session 109). The map says how large the largest free piece is and
// what lies between the pieces.
//
// newlib's malloc is dlmalloc 2.6.4 (mallocr.c): every chunk is a size
// word after the previous chunk's, from __malloc_sbrk_base up to the top
// chunk, av_[2], and a chunk is in use when the next one's PREV_INUSE bit
// says so. The walk holds the malloc lock.

#ifndef HEAPMAP_H
#define HEAPMAP_H

#include <stdint.h>

typedef struct {
    uint32_t used;      // bytes in chunks in use, headers included
    uint32_t free;      // bytes in free chunks, the top's included
    uint32_t largest;   // the largest free chunk
    uint32_t top;       // the top chunk's
    uint32_t pieces;    // free chunks of 64 KB or more, the top's included
    int      ok;        // 0: there is no heap yet, or a chunk did not read
} HeapMap;

void heapmap_take(HeapMap* m);

// A line for each free chunk of `min` bytes or more, in address order: its
// offset into the heap and size, and the run in use before it -- its
// blocks, bytes, and largest block, named when bMalloc made it. Then the
// run after the last.
void heapmap_lines(void (*line)(const char* text), uint32_t min);

// bMalloc's blocks of HEAPMAP_NAMED bytes or more keep their names for the
// lines (bmem.c's gBMemNoteFn and gBMemForgetFn).
#define HEAPMAP_NAMED (64u * 1024)
void heapmap_note(void* p, int size, const char* name);
void heapmap_forget(void* p);

// A line for each named block from lo up to hi, the linear heap's blocks
// from the pool's top among them: its size and name.
void heapmap_named(void (*line)(const char* text), uint32_t lo, uint32_t hi);

#endif
