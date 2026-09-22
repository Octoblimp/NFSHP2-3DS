// vtable -- the old g++ virtual call, as the port makes it.
//
// The PS2 build is g++ 2.9x, and its virtual call is four instructions that
// every dispatching method in the image repeats:
//
//     lw   v0, V(obj)       // the vptr, at the class's own offset V
//     lh   a0, S(v0)        // entry S: the this-adjustment ...
//     lw   v1, S+4(v0)      //          ... and the function
//     jalr v1 ; addu a0, obj, a0
//
// So a vtable is an array of eight-byte entries, {int16 delta, int16 index,
// fn}, entry 0 is empty, and a slot is named by its byte offset S -- 8, 16,
// 24 and on. The vptr is not at offset 0: g++ 2.9x puts it after the data of
// the first class that declares a virtual, which is why CarDriver's is at
// 556 and CarController's at 8.
//
// **The port keeps the vptr as the image's own address**, in a uint32_t at
// the image's offset, exactly as CarDriver, RigidBody and the drivetrain
// already did before anything dispatched through one. What this file adds is
// the other half: a registry from that address to the port's entries, so a
// call site can be written as the image writes it -- the same slot offset,
// the same delta added to the same pointer -- and a harness can install a
// recording table at the real address and watch which slot was taken.
//
// A table's entries are port data, not a copy of the image's. The delta in
// particular is a byte offset *in the port's layout*: PhysicsCar's secondary
// table adjusts by -8 on the console and by whatever the host's slack makes
// it here, so each class that installs a table computes its deltas with
// offsetof.

#ifndef VTABLE_H
#define VTABLE_H

#include <stddef.h>
#include <stdint.h>

typedef void (*VtFn)(void);

typedef struct VtEntry {
    int16_t delta;   // added to `this`, in bytes, before the call
    int16_t index;   // zero in every table this image has; kept for the shape
    VtFn    fn;      // cast to the slot's real type at the call
} VtEntry;

// The slot at byte offset S is entry S/8.
#define VT_SLOT(S) ((S) / 8)

// Registers `count` entries for the image vtable at `image`. Installing the
// same address again replaces the entries -- a harness swaps tables between
// scenarios that way.
void vt_install(uint32_t image, const VtEntry *entries, int count);

// Forgets every table. Harness-only; nothing in the game unregisters.
void vt_reset(void);

// The entry at byte offset `slot` of the table installed for `image`.
//
// Never NULL. A vptr whose table nobody installed means an object of a class
// the port has not brought over was somehow constructed, which is a port bug
// rather than a state the game can be in, so this aborts rather than hand
// back something to call through the wrong signature.
const VtEntry *vt_slot(uint32_t image, int slot);

// `obj + e->delta`, which is the `addu a0, obj, a0` in the delay slot.
static inline void *vt_this(void *obj, const VtEntry *e)
{
    return (char *)obj + e->delta;
}

#endif
