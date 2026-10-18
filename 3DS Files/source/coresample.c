// coresample -- see coresample.h.

#include "coresample.h"

#include <stdio.h>

#include <3ds.h>

// Between samples. Each is the sampler's sleep, a kernel call, and the
// kernel's lock is shared by the cores: 5,000 a second, not more.
#define SAMPLE_NS (200 * 1000LL)

volatile uint8_t CoreSampleStage;
volatile uint8_t CoreSamplePart;

// The sampler's alone to write; the line reads them as they are, and keeps
// what it read last, so neither thread clears the other's.
static volatile uint32_t s_count[CS_STAGES][CS_PARTS];
static uint32_t          s_last[CS_STAGES][CS_PARTS];
static Thread            s_thread;
static volatile bool     s_stop;

static const char* const kStage[CS_STAGES] = {
    "other", "waits", "cull", "envmap", "mirror", "sky", "models",
    "scenery", "cars", "hud", "bottom", "submit",
};

static const char* const kPart[CS_PARTS] = {
    "none", "solid", "matrix", "batches", "bind", "model", "pass", "cull",
    "draw", "lit", "send",
};

// The stages whose parts the line has.
static const uint8_t kParted[] = {
    CS_STAGE_ENVMAP, CS_STAGE_MODELS, CS_STAGE_SCENERY, CS_STAGE_CARS,
};

static void sample_main(void* arg)
{
    (void)arg;
    while (!s_stop) {
        unsigned stage, part;

        svcSleepThread(SAMPLE_NS);
        stage = CoreSampleStage;
        part  = CoreSamplePart;
        if (stage < CS_STAGES && part < CS_PARTS)
            s_count[stage][part]++;
    }
}

bool coresample_start(void (*log)(const char* fmt, ...))
{
    bool n3ds = false;
    s32  prio = 0x30;

    if (s_thread || s_stop)
        return s_thread != NULL;
    APT_CheckNew3DS(&n3ds);
    if (n3ds) {
        // Above the game's own, on a core the game does not use: it only
        // has to wake on time.
        svcGetThreadPriority(&prio, CUR_THREAD_HANDLE);
        prio = prio > 0x19 ? prio - 1 : 0x18;
        s_thread = threadCreate(sample_main, NULL, 4 << 10, prio, 2, false);
    }
    if (log)
        log("coresample: %s", s_thread ? "sampling from the third core"
                                       : "no third core, no samples");
    return s_thread != NULL;
}

void coresample_stop(void)
{
    s_stop = true;
    if (!s_thread)
        return;
    threadJoin(s_thread, U64_MAX);
    threadFree(s_thread);
    s_thread = NULL;
}

// "stage n%" for each stage sampled, then, for each parted stage with
// samples, "stage: part n%" for its parts, the shares of that stage's.
bool coresample_line(char* buf, size_t n)
{
    uint32_t d[CS_STAGES][CS_PARTS], stage[CS_STAGES], total = 0;
    size_t   len = 0;
    int      s, p, k;

    if (!s_thread)
        return false;
    for (s = 0; s < CS_STAGES; s++) {
        stage[s] = 0;
        for (p = 0; p < CS_PARTS; p++) {
            uint32_t c = s_count[s][p];

            d[s][p]      = c - s_last[s][p];
            s_last[s][p] = c;
            stage[s]    += d[s][p];
        }
        total += stage[s];
    }
    if (total == 0)
        return false;

#define ADD(...)                                                          \
    do {                                                                  \
        if (len < n) {                                                    \
            int w_ = snprintf(buf + len, n - len, __VA_ARGS__);           \
            if (w_ > 0)                                                   \
                len += (size_t)w_;                                        \
        }                                                                 \
    } while (0)

    ADD("samples: %lu; stages", (unsigned long)total);
    for (s = 0; s < CS_STAGES; s++) {
        if (stage[s])
            ADD(" %s %.1f%%", kStage[s], 100.0 * stage[s] / total);
    }
    for (k = 0; k < (int)(sizeof kParted / sizeof kParted[0]); k++) {
        s = kParted[k];
        if (!stage[s])
            continue;
        ADD("\nsamples, %s:", kStage[s]);
        for (p = 0; p < CS_PARTS; p++) {
            if (d[s][p])
                ADD(" %s %.1f%%", kPart[p], 100.0 * d[s][p] / stage[s]);
        }
    }
#undef ADD
    return true;
}
