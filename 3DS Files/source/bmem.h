// bmem -- bWare's general heap, as far as the car's classes use it.
//
//   bMalloc(int, const char *, int, int)  0x0023f0b8
//   bFree(void *)                         0x0023f148
//   __builtin_delete                      0x00114ab8, `j bFree`
//
// Every `new` of a class without a pool of its own is a direct call to the
// four-argument bMalloc -- `bMalloc(116, "PhysicsCar", 0, 16)` in
// SetMovementMode -- and every delete of one is `j __builtin_delete`. The
// image's bMalloc sends the name down the debug channel when one is open
// (two bFunkCallASync calls, 0x0023f0fc and 0x0023f118) and then calls
// bMalloc(size, pool), which is bWare's MemoryPool banks. The 3DS has one
// heap, so the port's is malloc's and the name and pool reach only a hook.
//
// Neither clears the block. A field a constructor does not write holds
// whatever the heap had there, on the console and here.
//
// A harness can replace both, together, to see every allocation and free
// the classes make: bSetMemoryHooks(NULL, NULL) puts malloc and free back.
// The slot pools are not this -- bslotpool.h has their own allocator.

#ifndef BMEM_H
#define BMEM_H

#include <stddef.h>

// The size is the port's record size, which on a 64-bit host is wider than
// the image's immediate. `flags` is the image's third argument, 0 at every
// call site the car's classes have; it only ever reached the debug channel.
void *bMalloc(int size, const char *name, int flags, int pool);

// __builtin_delete. bFree(NULL) is a no-op, as free's is.
void bFree(void *p);

typedef void *(*BMemMallocHook)(int size, const char *name, int flags,
                                int pool);
typedef void  (*BMemFreeHook)(void *p);

void bSetMemoryHooks(BMemMallocHook m, BMemFreeHook f);

#endif
