// realtime_test -- the harness tools/realtime_check.py runs against the
// clock object, 3DS Files/source/realtime.c.
//
// It reads a script of hex words from argv[1], one op and its operands at a
// time (the checker has the list), and prints what the model prints: one
// line an op, the joylog's calls as they happen, and the eighteen globals
// after every op that can move them. joylog.c is the port's own, with a
// logging repeat behind its two seams, as in joystick_test.c. bGetTicker
// answers from the script's ticks and logs each read, for MainLoop's
// measure (prepare_real_timestep_from_ticker).

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bticker.h"
#include "joylog.h"
#include "realtime.h"
#include "replay.h"

enum {
    OP_TAG = 1, OP_SET_MODE, OP_GET_MODE, OP_FROMQ, OP_QUANT, OP_PREP_REAL,
    OP_ADV_REAL, OP_RESET_WORLD, OP_PREP_WORLD, OP_ADV_WORLD, OP_FLAGS,
    OP_FEED, OP_POKE, OP_DUMP, OP_TICKS, OP_SET_TICKER, OP_MEASURE,
};

// In address order, gp-20264 up: the order the checker reads them in.
static void *const GLOBALS[18] = {
    &FrameCounter, &CurrentVideoMode, &RealTimer, &RealTime,
    &RealTimeFrames, &RealTimeElapsed, &RealTimeElapsedQuantized,
    &RealTimeElapsedFrame, &RealTimeElapsedError, &RealLoopCounter,
    &WorldTimer, &WorldTimeSeconds, &WorldTime, &WorldTimeFrames,
    &WorldTimeElapsed, &WorldTimeElapsedFrame, &WorldLoopCounter,
    &NeedToPrepareWorldTimestep,
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

static float as_float(uint32_t b)
{
    float f;

    memcpy(&f, &b, 4);
    return f;
}

static uint32_t float_bits(float f)
{
    uint32_t b;

    memcpy(&b, &f, 4);
    return b;
}

static uint32_t global(int i)
{
    uint32_t b;

    memcpy(&b, GLOBALS[i], 4);
    return b;
}

static void dump(void)
{
    int i;

    printf("  real ");
    for (i = 0; i < 10; i++)
        printf(" %08x", (unsigned)global(i));
    printf("\n  world");
    for (i = 10; i < 18; i++)
        printf(" %08x", (unsigned)global(i));
    printf("\n");
}

// ------------------------------------------------------------- the joylog

static int32_t feed[256];
static int feed_head, feed_tail;
static int the_repeat;

static int32_t jl_get(int32_t bits, int32_t ch)
{
    int32_t v = feed_head < feed_tail ? feed[feed_head++] : 0;

    printf("  jl get bits %d ch %d -> %d\n", bits, ch, v);
    return v;
}

static void jl_add(int32_t value, int32_t bits, int32_t ch)
{
    printf("  jl add %d bits %d ch %d\n", value, bits, ch);
}

// ------------------------------------------------------------- the ticker

#define MAX_TICKS 64

static uint32_t ticks[MAX_TICKS];
static int ticks_head, ticks_tail;
static uint32_t frame_ticker;     // MainLoop's s2

static uint32_t scripted_ticker(void)
{
    uint32_t v = ticks_head < ticks_tail ? ticks[ticks_head++] : 0;

    printf("  tick -> %08x\n", (unsigned)v);
    if (ticks_head == ticks_tail)
        ticks_head = ticks_tail = 0;
    return v;
}

int main(int argc, char **argv)
{
    unsigned int op;

    if (argc != 2 || (script = fopen(argv[1], "r")) == NULL) {
        fprintf(stderr, "usage: realtime_test SCRIPT\n");
        return 2;
    }
    gJoylogRepeatGetData = jl_get;
    gJoylogRepeatAddData = jl_add;
    bSetTickerSource(scripted_ticker);

    while (fscanf(script, "%x", &op) == 1) {
        switch (op) {
        case OP_TAG:
            printf("[%u]\n", (unsigned)next());
            break;
        case OP_SET_MODE: {
            int32_t m = (int32_t)next();
            printf("set mode %d -> %d\n", m, SetVideoMode(m));
            break;
        }
        case OP_GET_MODE:
            printf("get mode -> %d\n", GetVideoMode());
            break;
        case OP_FROMQ: {
            int32_t q = (int32_t)next();
            printf("fromq %d -> %08x\n", q,
                   (unsigned)float_bits(GetRealTimeElapsedFromQuantized(q)));
            break;
        }
        case OP_QUANT: {
            uint32_t b = next();
            printf("quant %08x -> %d\n", (unsigned)b,
                   GetQuantizedRealTimeElapsed(as_float(b)));
            break;
        }
        case OP_PREP_REAL: {
            uint32_t b = next();
            printf("prep real %08x\n", (unsigned)b);
            PrepareRealTimestep(as_float(b));
            dump();
            break;
        }
        case OP_ADV_REAL:
            printf("adv real\n");
            AdvanceRealTime();
            dump();
            break;
        case OP_RESET_WORLD:
            printf("reset world\n");
            ResetWorldTime();
            dump();
            break;
        case OP_PREP_WORLD: {
            uint32_t b = next();
            printf("prep world %08x\n", (unsigned)b);
            PrepareWorldTimestep(as_float(b));
            dump();
            break;
        }
        case OP_ADV_WORLD:
            printf("adv world\n");
            AdvanceWorldTime();
            dump();
            break;
        case OP_FLAGS: {
            int32_t r = (int32_t)next();
            int32_t c = (int32_t)next();
            int32_t p = (int32_t)next();
            Joylog_ReplayingFlag = r;
            Joylog_CapturingFlag = c;
            Joylog_pRepeat = p ? (void *)&the_repeat : NULL;
            printf("flags %d %d %d\n", r, c, p);
            break;
        }
        case OP_FEED:
            if (feed_tail == 256) {
                fprintf(stderr, "feed overflow\n");
                return 2;
            }
            feed[feed_tail++] = (int32_t)next();
            break;
        case OP_POKE: {
            uint32_t i = next();
            uint32_t v = next();
            if (i >= 18) {
                fprintf(stderr, "poke %u\n", (unsigned)i);
                return 2;
            }
            memcpy(GLOBALS[i], &v, 4);
            printf("poke %u %08x\n", (unsigned)i, (unsigned)v);
            break;
        }
        case OP_DUMP:
            dump();
            break;
        case OP_TICKS: {
            uint32_t n = next();
            while (n-- > 0) {
                if (ticks_tail == MAX_TICKS) {
                    fprintf(stderr, "ticks overflow\n");
                    return 2;
                }
                ticks[ticks_tail++] = next();
            }
            break;
        }
        case OP_SET_TICKER:
            frame_ticker = next();
            printf("ticker %08x\n", (unsigned)frame_ticker);
            break;
        case OP_MEASURE:
            printf("measure %08x\n", (unsigned)frame_ticker);
            prepare_real_timestep_from_ticker(&frame_ticker);
            dump();
            printf("  ticker %08x\n", (unsigned)frame_ticker);
            break;
        default:
            fprintf(stderr, "op %u\n", op);
            return 2;
        }
    }
    return 0;
}

// ----------------------------------------------- the snapshots, unreached
// The replay snapshot code in realtime.c (TASKS 72d) calls these;
// nothing here takes a snapshot.

static void snapshot_unreached_72d(const char *f)
{
    fprintf(stderr, "%s reached\n", f);
    exit(3);
}

void ReplaySnapshot_MoveData(ReplaySnapshot *s, void *p, int32_t stored,
                             int32_t size, int32_t is_signed)
{
    (void)s; (void)p; (void)stored; (void)size; (void)is_signed;
    snapshot_unreached_72d("ReplaySnapshot_MoveData");
}

void ReplaySnapshot_BeginSection(ReplaySnapshot *s, void *object,
                                 const char *name)
{
    (void)s; (void)object; (void)name;
    snapshot_unreached_72d("ReplaySnapshot_BeginSection");
}

void ReplaySnapshot_EndSection(ReplaySnapshot *s)
{
    (void)s;
    snapshot_unreached_72d("ReplaySnapshot_EndSection");
}

void ReplaySnapshot_VerifyData(ReplaySnapshot *s, void *p, int32_t stored,
                               int32_t size, int32_t is_signed)
{
    (void)s; (void)p; (void)stored; (void)size; (void)is_signed;
    snapshot_unreached_72d("ReplaySnapshot_VerifyData");
}
