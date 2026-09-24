// replay -- see replay.h.

#include "replay.h"

#include <stdio.h>
#include <stdlib.h>

ReplayManager *pReplayManager;

ReplayGetDataFn gReplayManagerGetData;
ReplayAddDataFn gReplayManagerAddData;

static void no_replay(void)
{
    fprintf(stderr, "replay: ReplayManager is not ported\n");
    abort();
}

int32_t ReplayManager_GetData(ReplayManager *rm, int32_t bits,
                              int32_t channel)
{
    if (gReplayManagerGetData == NULL)
        no_replay();
    return gReplayManagerGetData(rm, bits, channel);
}

void ReplayManager_AddData(ReplayManager *rm, int32_t value, int32_t bits,
                           int32_t channel)
{
    if (gReplayManagerAddData == NULL)
        no_replay();
    gReplayManagerAddData(rm, value, bits, channel);
}
