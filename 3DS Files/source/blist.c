// blist -- see blist.h.

#include "blist.h"

void blist_sort(bNode *list, bListInOrderFn in_order)
{
    int32_t moved;

    do {
        bNode *a = list->next;
        bNode *b;

        moved = 0;
        if (a == list || (b = a->next) == list)
            continue;
        do {
            if (in_order(a, b)) {
                a = b;
                b = b->next;
            } else {
                bNode *p;

                moved++;
                b->prev->next = b->next;
                b->next->prev = b->prev;
                p = a->prev;
                p->next = b;
                a->prev = b;
                b->prev = p;
                b->next = a;
                b = a->next;
            }
        } while (a != list && b != list);
    } while (moved != 0);
}
