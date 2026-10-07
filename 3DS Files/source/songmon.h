#pragma once
// tNewSongMonitor (0x0016bd30 .. 0x0016c214): the EA TRAX box. FlailerScreenList
// owns one (+416) and ticks it every frame, after the menus' movie. When the
// jukebox starts a tune -- a new one, or any after a stretch of silence --
// it shows GLOBALB's CHYRON screen for five seconds, prints the tune's album,
// artist and "title" into it, and stretches the five CHYRON_BG_n strips to
// the widest of those lines and the EA GAMES TRAX one, plus 20.
//
// Free of <3ds.h>, like jukebox.c: tools/songmon_check.py runs it next to
// retail's Update in mipsemu. See docs/formats/jukebox.md, "The EA TRAX box".
#include <stdbool.h>
#include <stdint.h>

// What Update asks of the rest of the game. Screens and objects are
// bStringHash values, as the Flailer calls take them.
typedef struct {
    void* user;
    // sound::jukebox::IsPlaying (0x001aecb0), which runs the player's Update.
    int (*isPlaying)(void* user);
    // GetCurrentTrack (0x001af040): (category << 16) + tune.
    uint32_t (*currentTrack)(void* user);
    // GetTrackName / GetTrackArtist / GetTrackLabel (-1, -1): the current
    // tune's fields, JB_TRACK_NAME, _ARTIST and _LABEL. NULL for none.
    const char* (*track)(void* user, int field);
    // RealTimer (gp-19608), 4000 a second.
    uint32_t (*realTimer)(void* user);
    // FlailerSetScreenVisibility, as a bool: 1 shows it. Retail passes the
    // enum, VISIBLE 0 and INVISIBLE 1 (see gameflow.h).
    void (*setScreenVisible)(void* user, uint32_t screen, int visible);
    // FlailerPrintf (0x00143e70): the finished string into a text object.
    void (*printText)(void* user, uint32_t screen, uint32_t object,
                      const char* s);
    // FlailerGetWidth (0x00144190): FlailerObjectChunk::GetWidth, 0 for no
    // such object.
    int32_t (*getWidth)(void* user, uint32_t screen, uint32_t object);
    // FlailerGetScale (0x001444e8): the object's scale, or the two left
    // alone if there is no such object.
    void (*getScale)(void* user, uint32_t screen, uint32_t object,
                     float* sx, float* sy);
    // FlailerSetScaleX (0x00144530).
    void (*setScaleX)(void* user, uint32_t screen, uint32_t object, float sx);
} BSongMonitorHooks;

// 24 bytes on the PS2.
typedef struct {
    uint32_t track;      // +0, the tune it last saw start
    uint32_t start;      // +4, the RealTimer then; 0x7fffffff for none yet
    uint32_t screen;     // +8, bStringHash("CHYRON")
    int32_t  starts;     // +12, 0 while the jukebox is quiet
    int32_t  printed;    // +16, the lines are in for this tune
    // +20 is an feAlphaAnimation the destructor and Reset delete. Nothing in
    // retail makes one, so it is always NULL and neither does anything else.
    // The width Update keeps of RECORD_TITLE, gp-21244; only Update reads it.
    int32_t  titleWidth;
    const BSongMonitorHooks* hooks;
} BSongMonitor;

// The constructor (0x0016bd30). +16 is not set: the list is a static, so
// it starts at 0.
void bsm_init(BSongMonitor* m, const BSongMonitorHooks* hooks);
// Update (0x0016be20).
void bsm_update(BSongMonitor* m);
// Reset (0x0016bde8), from UnlaunchFrontendMenus: retail's does nothing
// (see +20 above); the port's hides the box and forgets the tune.
void bsm_reset(BSongMonitor* m);
