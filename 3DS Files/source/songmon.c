// tNewSongMonitor: the EA TRAX box. See songmon.h.
#include "songmon.h"

#include <stdio.h>

#include "bchunk.h"
#include "jukebox.h"

#define H (m->hooks)

// gp-21244's neighbour gp-21264: 1 in the image, and nothing writes it. It
// is the only thing between the timer and the screen being shown.
#define SHOW_CHYRON 1

// 0x7fffffff: the start a monitor has before any tune.
#define NO_START 0x7fffffffu

// How long the box stays up. Retail's is 5.0; the port keeps it up a little
// longer (the user, 2026-10-11: it went away too quickly). The checker
// builds with -DCHYRON_SECONDS=5.0f to run against retail's.
#ifndef CHYRON_SECONDS
#define CHYRON_SECONDS 8.0f
#endif

void bsm_init(BSongMonitor* m, const BSongMonitorHooks* hooks)
{
    m->hooks = hooks;
    m->screen = bchunk_hash("CHYRON");
    m->track = 0xffffffffu;
    m->start = NO_START;
    m->starts = 0;
    m->printed = 0;
    // gp-21244's value in the image. Update writes it before reading it.
    m->titleWidth = 16;
}

// Retail's Reset deletes the feAlphaAnimation at +20, which nothing makes,
// and so does nothing. The port's also takes the box down and forgets the
// tune: UnlaunchFrontendMenus calls it as the jukebox stops, and the box
// would otherwise sit on the loading screen with the stopped tune's name
// for the rest of its five seconds. The next tune to start shows it again.
void bsm_reset(BSongMonitor* m)
{
    H->setScreenVisible(H->user, m->screen, 0);
    m->start = NO_START;
    m->starts = 0;
}

// FlailerPrintf's bVSPrintf, which spells a NULL string "(null)".
static void print_line(BSongMonitor* m, const char* object, const char* fmt,
                       const char* s)
{
    char buf[128];
    snprintf(buf, sizeof buf, fmt, s ? s : "(null)");
    H->printText(H->user, m->screen, bchunk_hash(object), buf);
}

static int32_t width_of(BSongMonitor* m, const char* object)
{
    return H->getWidth(H->user, m->screen, bchunk_hash(object));
}

// The lines in and the strips to fit them, once a tune.
static void print_tune(BSongMonitor* m)
{
    const char* name = H->track(H->user, JB_TRACK_NAME);
    const char* artist = H->track(H->user, JB_TRACK_ARTIST);
    const char* label = H->track(H->user, JB_TRACK_LABEL);
    print_line(m, "RECORD_LABEL", "%s", label);
    print_line(m, "ARTIST_NAME", "%s", artist);
    print_line(m, "SONG_TITLE", "\"%s\"", name);
    m->printed = 1;

    m->titleWidth = width_of(m, "RECORD_TITLE");
    int32_t widest = width_of(m, "RECORD_LABEL");
    int32_t w = width_of(m, "ARTIST_NAME");
    if (widest < w) {
        widest = w;
    }
    w = width_of(m, "SONG_TITLE");
    if (widest < w) {
        widest = w;
    }
    if (widest < m->titleWidth) {
        widest = m->titleWidth;
    }

    // Each strip's width over its own scale is the texture's; the scale
    // that makes it the widest line and 20 more is the one it gets.
    for (int i = 1; i <= 5; i++) {
        char strip[16];
        snprintf(strip, sizeof strip, "CHYRON_BG_%d", i);
        uint32_t hash = bchunk_hash(strip);
        float texW = (float)H->getWidth(H->user, m->screen, hash);
        float sx = 1.0f, sy = 1.0f;
        H->getScale(H->user, m->screen, hash, &sx, &sy);
        texW = texW / sx;
        float scale = ((float)widest + 20.0f) / texW;
        H->setScaleX(H->user, m->screen, hash, scale);
    }
}

void bsm_update(BSongMonitor* m)
{
    if (!H->isPlaying(H->user)) {
        m->starts = 0;
    } else {
        uint32_t track = H->currentTrack(H->user);
        if (track != m->track || m->starts == 0) {
            m->track = track;
            m->start = H->realTimer(H->user);
            m->starts++;
            m->printed = 0;
        }
    }
    if (m->start == 0 || m->start == NO_START) {
        return;
    }
    float t = (float)(int32_t)(H->realTimer(H->user) - m->start) * 0.00025f;
    if (!(0.0f < t) || !(t < CHYRON_SECONDS)) {
        H->setScreenVisible(H->user, m->screen, 0);
        return;
    }
    if (SHOW_CHYRON) {
        H->setScreenVisible(H->user, m->screen, 1);
    }
    if (!m->printed) {
        print_tune(m);
    }
}
