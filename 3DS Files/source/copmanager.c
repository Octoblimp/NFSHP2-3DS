// copmanager -- see copmanager.h.

#include "copmanager.h"

#include "car.h"

tCopManager *pCopManager;       // 0x00331bec

tCop *(*gCopManagerGetCopByCarFn)(tCopManager *m, struct Car *c);
tCop *(*gCopManagerGetCopByChaseFn)(tCopManager *m, struct Car *c);

int32_t copmanager_should_display_busted_text(const tCopManager *m)
{
    const tCarPulloverInfo *pl = (const tCarPulloverInfo *)(const void *)
        ((const uint8_t *)m + COPMANAGER_PULLOVERS);
    int i;

    for (i = 0; i < COPMANAGER_NUM_PULLOVERS; i++)
        if (pl[i].bActive && pl[i].bShouldDisplayBustedText)
            return 1;
    return 0;
}

tPursuit *copmanager_is_being_pursued(tCopManager *m, struct Car *c)
{
    tPursuitNode *list = &copmanager_head(m)->PursuitList;
    tPursuitNode *n;

    for (n = list->Next; n != list; n = n->Next)
        if (((tPursuit *)(void *)n)->pChasedCar == c)
            return (tPursuit *)(void *)n;
    return NULL;
}

int32_t copmanager_get_pursuit_level_for_hud(tCopManager *m, struct Car *c)
{
    tPursuit *p = copmanager_is_being_pursued(m, c);

    return p != NULL ? p->nHUDPursuitLevel : 0;
}

int32_t copmanager_get_num_tickets(tCopManager *m, struct Car *c)
{
    const tCarPulloverInfo *pl = (const tCarPulloverInfo *)(const void *)
        ((const uint8_t *)m + COPMANAGER_PULLOVERS);

    return pl[c->CarIndex].nNumTickets;
}
