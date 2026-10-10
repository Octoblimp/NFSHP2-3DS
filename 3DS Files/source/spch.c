// spch -- spchrslv.o, sputil.o, spchinit.o, spchlog.o, spdprint.o,
// spabort.o and sptick.o of SPP2A380.A: the event dats, the setup, the
// debug output and the clock. See spch.h.

#include <stdarg.h>
#include <stdio.h>

#include "spchi.h"

SpchState gSpch = {
    .clearCycle = 1,                        // 0x0032b730
    // 0x0032be88: EAC_SeedRandom(0)'s, until SPCH_Init seeds it
    .seed = { 0xf22d0e56u, 0x883126e9u, 0xc624dd2fu, 0x0702c49cu,
              0x9e353f7du, 0x6fdf3b64u },
};

// ---- spdprint, spabort, sptick

#define SPCH_MSG 512

void spchi_print(const char *fmt, ...)
{
    char buf[SPCH_MSG];
    va_list ap;

    buf[0] = 0;
    if (fmt != NULL) {
        va_start(ap, fmt);
        vsnprintf(buf, sizeof(buf), fmt, ap);
        va_end(ap);
    }
    if (gSpch.ext.print != NULL)
        gSpch.ext.print(buf);
    else
        printf("%s", buf);
}

// Retail's abort without a vector saves the log, prints and exits; the
// port prints and goes on, as the callers do with a vector.
void spchi_abort(const char *fmt, ...)
{
    char buf[SPCH_MSG];
    va_list ap;

    buf[0] = 0;
    if (fmt != NULL) {
        va_start(ap, fmt);
        vsnprintf(buf, sizeof(buf), fmt, ap);
        va_end(ap);
    }
    // Retail appends "FILE %s LINE %d" when gAbortFile and gAbortLine
    // are set; nothing sets them.
    if (gSpch.ext.abort != NULL)
        gSpch.ext.abort(buf);
    else
        fprintf(stderr, "\n******** SPCH LIBRARY ABORTED ********\n %s\n", buf);
}

uint32_t spchi_gettick(void)
{
    if (gSpch.ext.gettick != NULL)
        return gSpch.ext.gettick();
    spchi_print("gettick vector not installed.");
    return 0;
}

// ---- spchrslv

void spch_get_event_dat_info(const uint8_t *dat, uint32_t *a, uint32_t *b)
{
    *a = dat[8];
    *b = dat[9];
}

int32_t spchi_bind_data(const uint8_t *dat, uint32_t channel)
{
    uint32_t a, b;
    int32_t i;

    if (spch_u16(dat) != 0x803) {
        spchi_abort("event.dat version mismatch.  This event dat goes with SED %d.%d",
                    dat[0], dat[1]);
        return 0;
    }
    spch_get_event_dat_info(dat, &a, &b);
    for (i = 0; i < SPCH_EVENT_DATS; i++) {
        const uint8_t *d = gSpch.eventDats[i].dat;

        if (d != NULL && d[9] == b && d[8] == a) {
            spchi_abort("iSPCH_BindData - tried to load 2 event.dat files with the same project and dat IDs.");
            return 0;
        }
    }
    for (i = 0; i < SPCH_EVENT_DATS; i++) {
        if (gSpch.eventDats[i].dat == NULL) {
            gSpch.eventDats[i].dat = dat;
            gSpch.eventDats[i].channel = channel;
            return 1;
        }
    }
    spchi_abort("iSPCH_BindData - tried to load more than the maximum (%d) event.dat files.",
                SPCH_EVENT_DATS);
    return 0;
}

int32_t spch_add_event_db(const uint8_t *dat, uint32_t channel)
{
    if (channel >= SPCH_CHANNELS) {
        spchi_abort("channel must be 0..%ld.", (long)SPCH_CHANNELS);
        return 0;
    }
    return spchi_bind_data(dat, channel);
}

int32_t spch_resolve_data(const uint8_t *dat)
{
    return spch_add_event_db(dat, 0);
}

// ---- sputil

SpchExtVecs *spch_get_ext_vecs(void)
{
    return &gSpch.ext;
}

// ---- spchinit

void spchi_init_in_game(void)
{
    int32_t i;

    // Only the ID; the word's upper half is left as it is.
    for (i = 0; i < SPCH_CHANNELS; i++) {
        gSpch.inGame[i].count = 0;
        gSpch.inGame[i].word = (gSpch.inGame[i].word & 0xffff0000u) | 0xffff;
    }
}

int32_t spch_get_sample_data_rate(int32_t rate, int32_t bits, int32_t mode)
{
    int32_t v = (int32_t)((uint32_t)rate * (uint32_t)bits);

    v = (v < 0 ? v + 7 : v) >> 3;
    if (mode == 1)
        return v / 10;
    if (mode == 2)
        return v * 2 / 7;
    return v;
}

void spch_init_rule_callbacks(SpchRuleTestFn test, SpchRuleSetFn set)
{
    if (gSpch.initialized != SPCH_MAGIC) {
        spchi_abort("SPCH_InitRuleCallbacks - call SPCH_Init first.\n");
        return;
    }
    gSpch.ruleSet = set;
    gSpch.ruleTest = test;
}

void spchi_init_ext_vecs(void)
{
    gSpch.ext.abort = NULL;
    gSpch.ext.gettick = NULL;
    gSpch.ext.print = NULL;
}

// The request and the rules' callbacks; not the event rule's or the
// reparm's.
void spchi_init_callbacks(void)
{
    gSpch.request = NULL;
    gSpch.ruleSet = NULL;
    gSpch.ruleTest = NULL;
}

void spch_init_reparm_callback(SpchReparmFn fn)
{
    if (gSpch.initialized != SPCH_MAGIC) {
        spchi_abort("SPCH_InitReparmCallback - call SPCH_Init first.\n");
        return;
    }
    gSpch.reparm = fn;
}

void spch_init_event_rule_callback(SpchEventRuleFn fn)
{
    if (gSpch.initialized != SPCH_MAGIC) {
        spchi_abort("SPCH_InitEventRuleCallback - call SPCH_Init first.\n");
        return;
    }
    gSpch.eventRule = fn;
}

// Retail also sets gSPCH_AddEvent (0x0032b72c) to SPCH_AddEventV, which
// nothing reads.
int32_t spch_init(SpchRequestFn request, int32_t game, int32_t rate)
{
    int32_t i;

    spchi_init_callbacks();
    spchi_init_ext_vecs();
    gSpch.request = request;
    gSpch.dataRate = rate;
    gSpch.gameNum = game;
    spchi_init_random(game);
    spchi_init_sentence_choice();
    spch_set_pre_load_ticks(0);
    for (i = SPCH_CHANNELS - 1; i >= 0; i--)
        gSpch.filter[i] = 0;
    spchi_init_event_dat();
    spchi_init_in_game();
    spchi_init_banks();
    spchi_init_event_queue();
    gSpch.initialized = SPCH_MAGIC;
    return 1;
}

void spch_deinit(void)
{
    if (gSpch.initialized != SPCH_MAGIC) {
        spchi_abort("SPCH_Deinit - not initialized.");
        return;
    }
    gSpch.initialized = 0;
    spchi_init_callbacks();
    spchi_dispose_banks();
    spchi_init_event_dat();
    spch_save_evlog();
    spch_deinit_evlog();
}

// ---- spchlog: the debug log, dropped but for InitEvlog's check

int32_t spch_init_evlog(void *buf, int32_t size, void (*write)(char *, int32_t))
{
    (void)buf;
    (void)size;
    (void)write;
    if (gSpch.initialized != SPCH_MAGIC) {
        spchi_abort("SPCH_Init must be called before SPCH_InitEvlog\n");
        return 0;
    }
    return 1;
}

void spch_deinit_evlog(void)
{
}

void spch_save_evlog(void)
{
}
