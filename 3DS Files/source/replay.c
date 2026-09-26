// replay -- see replay.h.

#include "replay.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "p32.h"

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

// 0x0013c290. The compare is against the string at 0x00292b80,
// "INSTANT_REPLAY", and never against `description`: every caller's event
// lands on the instant-replay snapshots and no others. The image's compare
// is bStrCmp, a signed-char difference that is 0 exactly when the two
// strings are equal, and only its zero is tested, so strcmp stands in.
void ReplayManager_RegisterInterestingEvent(ReplayManager *rm, float value,
                                            const char *description)
{
    const void *head = rm->ReplaySnapshotList;
    ReplaySnapshot *s;

    (void)description;
    if (!rm->CapturingFlag)
        return;
    for (s = p32_ptr(rm->ReplaySnapshotList[0]); (const void *)s != head;
         s = p32_ptr(s->pNext))
        if (strcmp(s->Name, "INSTANT_REPLAY") == 0)
            s->TotalInterestingValue = s->TotalInterestingValue + value;
}

// 0x0013c310.
void ReplayManager_InvalidateInterestingEvents(ReplayManager *rm)
{
    ReplayManager_RegisterInterestingEvent(rm, -99.0f, "Invalidate");
}
