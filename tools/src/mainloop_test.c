// mainloop_test -- the harness tools/mainloop_check.py runs against
// MainLoop's frame profiler: CalculateFrameRate (mainloop.c) and the two
// times it reads, GetWaitForBufferSwapTime and GetVifTime (edisplay.c).
//
// It reads a script of hex words from argv[1], one op and its operands at a
// time (the checker has the list), and prints what the model prints: one
// line an op, and the profiler's globals after each op that can move them.

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "edisplay.h"
#include "mainloop.h"
#include "realtime.h"

enum {
    OP_TAG = 1, OP_SET_TICK, OP_SET_WAIT, OP_SET_VIF, OP_SET_FRAMES,
    OP_WAIT_TIME, OP_VIF_TIME, OP_CALC, OP_DUMP,
};

static FILE *script;

static uint32_t next(void)
{
    unsigned int w;

    if (fscanf(script, "%x", &w) != 1) {
        fprintf(stderr, "script ends inside an op\n");
        exit(2);
    }
    return (uint32_t)w;
}

static uint32_t float_bits(float f)
{
    uint32_t b;

    memcpy(&b, &f, 4);
    return b;
}

static void dump(void)
{
    const uint32_t *t = &MainLoopTiming.StartTime;
    int i;

    printf("  prev  %08x %08x %08x %08x\n",
           (unsigned)float_bits(PreviousCpuFrameTime),
           (unsigned)float_bits(PreviousGpuFrameTime),
           (unsigned)float_bits(PreviousCpuFrameRate),
           (unsigned)float_bits(PreviousGpuFrameRate));
    printf("  ticks");
    for (i = 0; i < 10; i++)
        printf(" %08x", (unsigned)t[i]);
    printf("\n  wait %08x vif %08x frames %08x\n",
           (unsigned)WaitBufferSwapTime, (unsigned)VifTime,
           (unsigned)RealTimeFrames);
}

int main(int argc, char **argv)
{
    unsigned int op;

    if (argc != 2 || (script = fopen(argv[1], "r")) == NULL) {
        fprintf(stderr, "usage: mainloop_test SCRIPT\n");
        return 2;
    }

    while (fscanf(script, "%x", &op) == 1) {
        switch (op) {
        case OP_TAG:
            printf("[%u]\n", (unsigned)next());
            break;
        case OP_SET_TICK: {
            uint32_t i = next();
            uint32_t v = next();
            if (i >= 10) {
                fprintf(stderr, "tick %u\n", (unsigned)i);
                return 2;
            }
            (&MainLoopTiming.StartTime)[i] = v;
            printf("tick %u %08x\n", (unsigned)i, (unsigned)v);
            break;
        }
        case OP_SET_WAIT:
            WaitBufferSwapTime = (int32_t)next();
            printf("wait %08x\n", (unsigned)WaitBufferSwapTime);
            break;
        case OP_SET_VIF:
            VifTime = (int32_t)next();
            printf("vif %08x\n", (unsigned)VifTime);
            break;
        case OP_SET_FRAMES:
            RealTimeFrames = (int32_t)next();
            printf("frames %08x\n", (unsigned)RealTimeFrames);
            break;
        case OP_WAIT_TIME:
            printf("wait time -> %08x\n",
                   (unsigned)float_bits(GetWaitForBufferSwapTime()));
            break;
        case OP_VIF_TIME:
            printf("vif time -> %08x\n", (unsigned)float_bits(GetVifTime()));
            break;
        case OP_CALC:
            printf("calc\n");
            CalculateFrameRate();
            dump();
            break;
        case OP_DUMP:
            dump();
            break;
        default:
            fprintf(stderr, "op %u\n", op);
            return 2;
        }
    }
    return 0;
}
