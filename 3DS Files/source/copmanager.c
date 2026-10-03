// copmanager -- see copmanager.h.

#include "copmanager.h"

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
