#include "fesound.h"

#include <string.h>

// The one bSound the frontend talked to (gp-23628, tested at the head of
// every function in this family). A static here for the same reason: the
// BMenuSoundFn signature passes BMenu::user, which belongs to the screen.
static BsndDriver* gDriver;

// InitGlobalMenuSound (0x00169160) and InitFrontendSounds (0x001691e8) walk
// the same table twice, once per region, building a bSample for every entry
// that belongs to theirs. Here the bank is the unit, so the walk is only to
// find out which banks the table mentions at all -- two, on this disc, but the
// loop does not assume that.
void fesound_init(BsndDriver* d)
{
    int i, j;

    gDriver = d;
    if (!d) return;

    for (i = 0; i < FESOUND_EVENT_COUNT; i++) {
        const char* bank = fesound_events[i].bank;
        if (!bank) continue;
        for (j = 0; j < i; j++)
            if (fesound_events[j].bank
                && strcmp(fesound_events[j].bank, bank) == 0) break;
        if (j < i) continue;                    // already asked for this one
        bsnd_bank_load(d, bank);                // false just means silence
    }
}

void fesound_play(int soundEvent, void* user)
{
    BsndDriver* d = gDriver;
    const FeSoundEntry* e;

    (void)user;

    // MakeFrontendSound returns without touching anything when the event has
    // no sample (0x001692e8), and every callback that does not pick a noise
    // leaves BScreenCallbackData::noise at 0 -- so this is the path most menu
    // input takes.
    if (!d || soundEvent <= 0 || soundEvent >= FESOUND_EVENT_COUNT) return;
    e = &fesound_events[soundEvent];
    if (!e->bank || !e->patch) return;

    // The patch's own rate, volume and pan, an azimuth of 0, and any free
    // voice: the disc's Play(1.0f, 0.0f, 0.0f) is full volume, centred, and
    // bSample::Play picks the channel. A miss -- bank not on the card, no free
    // voice -- is silence, which is the right failure for a menu bleep.
    bsnd_voice_play(d, e->bank, e->patch, BSND_RATE_PATCH, BSND_VOLUME_PATCH,
                    0, BSND_VOICE_ALLOC);
}
