// bplist -- the nodes of a bPList: bPNode, a bNode with a pointer to the
// object it lists, from a slot pool of its own. The last four functions of
// bList.obj, 0x002383f8 .. 0x0023849c.
//
// A bPList<T> lists objects that do not begin with links of their own, or
// that are on another list already: World's AICarList holds the AI racers
// this way while CarList holds every car. AddRacingCar, the skid sets, the
// acid emitters, the end-game screens and the event tree take nodes from
// the pool; a bPList's destructor, and each of those owners, gives them
// back. `bPNode:Tt118=s12`.
//
// This is apart from blist.c so that a harness can link the list code and
// stub the pool, as world_test does.

#ifndef BPLIST_H
#define BPLIST_H

#include <stdint.h>

#include "blist.h"
#include "bslotpool.h"

typedef struct bPNode {
    bNode  Node;     // 0
    void  *Object;   // 8
} bPNode;

// gp-15772, 0x00324e54. NULL until bplist_init.
extern BSlotPool *bPNodeSlotPool;

// 0x002383f8, bPListInit. A pool of `n` nodes named "bPNode SlotPool" in
// memory pool 16, unless there is one already. InitializeEverything calls
// it with 1536 and then 2048, so the second does nothing.
void bplist_init(int32_t n);

// 0x00238430, bPListClose. The pool deleted and forgotten, if there is
// one. Nothing calls it.
void bplist_close(void);

// 0x00238458, bPNode::Malloc: bOMalloc on the pool, which is made with 32
// nodes first if there is none.
bPNode *bpnode_malloc(void);

// 0x00238488, bPNode::Free: bFree on the pool. With no pool the listing
// reaches a `break`; the port aborts.
void bpnode_free(void *p);

#endif
