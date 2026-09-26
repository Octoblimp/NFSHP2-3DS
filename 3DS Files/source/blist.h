// blist -- bWare's intrusive list, the methods the port has reached.
//
// A bList is its own sentinel: a bNode, eight bytes, two links, pointing at
// itself when the list is empty. A bTList<T> is a bList whose nodes are T's
// first eight bytes, so any record that begins with its links can be sorted
// through a cast. Most of the port's lists spell out their own node type
// (ContactNode, CarNode, WorldList); this is the shape they all share.
//
// bList::Sort (0x00238328) is ported here because five bTList<T>::Sort
// instantiations reach it: World's cars, the flailer's object chunks, the
// visible cars, the queued files and the tourney points. AddSorted, which
// TestForContact uses, is still contact.c's own.

#ifndef BLIST_H
#define BLIST_H

#include <stdint.h>

typedef struct bNode {
    struct bNode *next;   // 0
    struct bNode *prev;   // 4
} bNode;

// Nonzero when a may stay in front of b.
typedef int32_t (*bListInOrderFn)(bNode *a, bNode *b);

// 0x00238328. A bubble sort. Each pass walks the list with a node a and
// the node b after it. When in_order(a, b) is nonzero, a moves on to b.
// When it is zero, b is unlinked and put back in front of a, and a stays
// where it is. The passes repeat until one moves nothing. A list of fewer
// than two nodes takes one pass and is left alone.
//
// While b is off the list, the listing poisons both its links with 11
// (bNode's debug fill) and then overwrites them straight away. The port
// leaves the fill out.
void blist_sort(bNode *list, bListInOrderFn in_order);

#endif
