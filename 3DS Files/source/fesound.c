#include "fesound.h"

#include "bticker.h"
#include "jukebox.h"

// SoundEnabled (gp-23056), carinit.c's.
extern int32_t SoundEnabled;

// Each entry's bSample, the table's fourth word in the image (+12).
static BSample* s_sample[FESOUND_EVENT_COUNT];
// MakeFrontendSound's last sample and when it played (gp-21204, gp-21208).
static BSample* s_lastSample;
static uint32_t s_lastTime;

void fesound_init_global(void)
{
    int i;

    if (!SoundEnabled)
        return;
    for (i = 0; i < FESOUND_EVENT_COUNT; i++) {
        // CommonRegion is asked for again on every pass.
        BRegion* r = bsound_common_region(bsound_get());
        const FeSoundEntry* e = &fesound_events[i];

        if (e->fromFrontEnd != 0 || e->name == NULL)
            continue;
        s_sample[i] = bregion_sample(r, e->name);
        bsample_set_category(s_sample[i], JB_CAT_MENU_SFX);
    }
}

void fesound_init_frontend(void)
{
    int i;

    if (!SoundEnabled)
        return;
    for (i = 0; i < FESOUND_EVENT_COUNT; i++) {
        BRegion* r = bsound_region(bsound_get(), "FrontEnd");
        const FeSoundEntry* e = &fesound_events[i];

        // No SetCategory here: MakeFrontendSound sets it on every play.
        if (e->fromFrontEnd != 1 || e->name == NULL)
            continue;
        s_sample[i] = bregion_sample(r, e->name);
    }
}

void fesound_uninit_frontend(void)
{
    int i;

    for (i = 0; i < FESOUND_EVENT_COUNT; i++)
        if (fesound_events[i].fromFrontEnd == 1)
            s_sample[i] = NULL;
}

void fesound_play(int soundEvent, void* user)
{
    BSample* s;

    (void)user;
    if (!SoundEnabled)
        return;
    // Retail indexes the table unbounded; every event bmenu.c raises is in
    // it. The bound is the port's.
    if (soundEvent < 0 || soundEvent >= FESOUND_EVENT_COUNT)
        return;
    s = s_sample[soundEvent];
    if (s == NULL)
        return;
    if (s == s_lastSample
        && bGetTickerDifference(s_lastTime, bGetTicker()) < 34.0f)
        return;
    s_lastTime = bGetTicker();
    bsample_set_category(s, JB_CAT_MENU_SFX);
    bsample_play(s, 1.0f, 0.0f, 0.0f);
    s_lastSample = s;
}

void fesound_stop(int soundEvent)
{
    BSample* s;

    if (!SoundEnabled)
        return;
    if (soundEvent < 0 || soundEvent >= FESOUND_EVENT_COUNT)
        return;                     // the port's, as fesound_play's
    s = s_sample[soundEvent];
    if (s != NULL)
        bsample_stop(s);
}
