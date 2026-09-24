// joylog -- see joylog.h.

#include "joylog.h"

#include <stdio.h>
#include <stdlib.h>

int32_t Joylog_ReplayingFlag;
int32_t Joylog_CapturingFlag;
void   *Joylog_pRepeat;

JoylogGetDataFn gJoylogRepeatGetData;
JoylogAddDataFn gJoylogRepeatAddData;

static void no_repeat(void)
{
    fprintf(stderr, "joylog: bRepeat is not ported\n");
    abort();
}

int32_t Joylog_GetData(int32_t bits, int32_t channel)
{
    if (Joylog_pRepeat == NULL)
        return 0;
    if (gJoylogRepeatGetData == NULL)
        no_repeat();
    return gJoylogRepeatGetData(bits, channel);
}

void Joylog_AddData(int32_t value, int32_t bits, int32_t channel)
{
    if (Joylog_pRepeat == NULL || !Joylog_CapturingFlag)
        return;
    if (gJoylogRepeatAddData == NULL)
        no_repeat();
    gJoylogRepeatAddData(value, bits, channel);
}
