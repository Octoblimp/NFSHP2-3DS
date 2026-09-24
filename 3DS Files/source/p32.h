// p32 -- a pointer kept in a 32-bit slot, as the image keeps them.
//
// Every intrusive list in the image is a bNode, two words at the front of
// the object: Next and Prev. The component records the port already has --
// RigidBody, Wheel, Suspension, Engine, DriveTrain -- declare those words as
// uint32_t so that their layouts stay exact and their checkers can hold
// every offset to the image, and until PhysicsSystem nothing followed them.
//
// On the 3DS a pointer *is* 32 bits, so a slot holds the address and these
// are casts. On the 64-bit host that runs the checkers it is not, and a
// slot holds a handle instead: an index into a registry of every pointer
// that has been stored, plus one, so that 0 stays NULL. The code that walks
// a list is the same text on both, which is the point -- a harness exercises
// the walk the handheld will run, not a host-only variant of it.
//
// The registry only grows. Nothing in the game frees a handle, because on
// the handheld there is nothing to free; a harness that builds and tears
// down many objects calls p32_reset() between scenarios.

#ifndef P32_H
#define P32_H

#include <stdint.h>

#if UINTPTR_MAX == 0xffffffffu

static inline uint32_t p32_of(const void *p)
{
    return (uint32_t)(uintptr_t)p;
}

static inline void *p32_ptr(uint32_t h)
{
    return (void *)(uintptr_t)h;
}

static inline void p32_reset(void)
{
}

#else

// The handle for `p`, registering it the first time it is seen. NULL is 0.
// Aborts when the registry is full, which a harness would have to try hard
// to reach and the game cannot.
uint32_t p32_of(const void *p);

// The pointer behind a handle. 0 is NULL; a handle that was never handed
// out aborts, because the only way to get one is a corrupted slot.
void *p32_ptr(uint32_t h);

// Forgets every handle. Harness-only.
void p32_reset(void);

#endif

#endif
