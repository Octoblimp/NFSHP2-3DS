#include "sound.h"

#include <string.h>

#include "bmath.h"
#include "bticker.h"

// SoundEnabled (gp-23056), carinit.c's.
extern int32_t SoundEnabled;

// SetPath's string, and the bFileExists path the loader builds round a
// region's name.
#define SOUND_DIR   "sound\\"
#define SOUND_EXT   ".msh"

// SaveVolumesForSpeech's categories (0x00313890), the order the saved
// volumes are kept in.
static const uint32_t kSavedCategory[5] = {0, 1, 2, 5, 4};

static SoundModule* s_instance;

// ------------------------------------------------------------ the hooks

#define H (m->hooks)
#define CALL0(fn) do { if (H && H->fn) H->fn(H->ctx); } while (0)
#define CALL1(fn, a) do { if (H && H->fn) H->fn(H->ctx, a); } while (0)

static int game_state(const SoundModule* m)
{
    return H && H->game_state ? H->game_state(H->ctx) : 0;
}

static int paused(const SoundModule* m)
{
    return H && H->paused ? H->paused(H->ctx) : 0;
}

static uint32_t vblank(const SoundModule* m)
{
    return H && H->vblank ? H->vblank(H->ctx) : 0;
}

static int helicopter(const SoundModule* m)
{
    return H && H->helicopter ? H->helicopter(H->ctx) : 0;
}

static const char* sound_path(const SoundModule* m)
{
    return H && H->sound_path ? H->sound_path : SOUND_DIR;
}

static void flash(const SoundModule* m, int r, int g, int b, const char* why,
                  float seconds)
{
    if (H && H->flash) H->flash(H->ctx, r, g, b, why, seconds);
}

// bStrCpy into a region's name, which retail does not bound.
static void copy_name(char* dst, const char* src)
{
    size_t n = strlen(src);
    if (n > sizeof(((SoundRegionSlot*)0)->name) - 1)
        n = sizeof(((SoundRegionSlot*)0)->name) - 1;
    memcpy(dst, src, n);
    dst[n] = '\0';
}

// ---------------------------------------------------------- the statics

void sound_init(SoundModule* m, BSound* bs, BsndDriver* driver, JBSound* jb,
                const uint8_t* audioOptions, const SoundHooks* hooks)
{
    memset(m, 0, sizeof *m);
    m->bsound = bs;
    m->driver = driver;
    m->jb = jb;
    m->audioOptions = audioOptions;
    m->hooks = hooks;
    m->muffleCurrent = 1.0f;
    m->muffleTarget = 1.0f;
    m->lastScale = -1.0f;
    m->audioMode = 1;
    m->speechEnabled = 1;
    s_instance = m;
}

SoundModule* sound_get(void)
{
    return s_instance;
}

const char* sound_get_path(const SoundModule* m)
{
    return sound_path(m);
}

// ------------------------------------------------------------ the regions

static void load_region(SoundModule* m, const char* name);

// The callback's second half: the first region asked for and not in, one
// at a time, as bSound holds one pending region.
static void load_next(SoundModule* m)
{
    int i;

    for (i = 0; i < SOUND_REGIONS; i++) {
        if (m->region[i].name[0] != '\0' && !m->region[i].loaded) {
            bsound_set_path(m->bsound, sound_path(m));
            load_region(m, m->region[i].name);
            return;
        }
    }
}

// 0x001ae340: a region whose .msh is not on the disc is a blue flash and
// nothing more.
static void load_region(SoundModule* m, const char* name)
{
    char path[sizeof(SOUND_DIR) + 32 + sizeof(SOUND_EXT)];
    int exists, i;

    copy_name(path, SOUND_DIR);
    strcat(path, name);
    strcat(path, SOUND_EXT);
    exists = H && H->file_exists ? H->file_exists(H->ctx, path) : 1;
    if (!exists)
        flash(m, 0, 0, 250, "Cannot Find Sound Region", 1.0f);
    else if (bsound_load_region(m->bsound, name))
        return;
    if (!(H && H->skip_missing))
        return;
    // The port's (SoundHooks.skip_missing): what will not come is taken as
    // come, and the rest are asked for.
    for (i = 0; i < SOUND_REGIONS; i++)
        if (strcmp(name, m->region[i].name) == 0)
            m->region[i].loaded = 1;
    load_next(m);
}

void sound_driver_callback(uint32_t event, void* what, void* data)
{
    SoundModule* m = (SoundModule*)data;
    BRegion* r = (BRegion*)what;
    int i;

    // Only a region's arrival; a sample's stop (8) and the rest pass by.
    if (event != BSOUND_REGION_LOADED)
        return;
    if (r == bsound_common_region(m->bsound))
        m->commonLoaded = 1;
    for (i = 0; i < SOUND_REGIONS; i++)
        if (strcmp(bregion_name(r), m->region[i].name) == 0)
            m->region[i].loaded = 1;
    load_next(m);
}

void sound_initialize_driver(SoundModule* m)
{
    // gp-23044 first, bSound::DisablePrintf: its debug output, which the
    // port does not have.
    if (!SoundEnabled)
        return;
    m->seed = (uint32_t)bRandomI(-1, &bDefaultSeed);
    // bSound::Initialize(callback, 0, 256 regions' room, 50, 16, 1, 1,
    // 0x10000): the sizes are bsound.c's own.
    bsound_init(m->bsound, m->driver, sound_driver_callback, m);
    sound_set_audio_mode(m, 1);
    // bEffect::SetType(1) and PlatSetEffectVolume(all, 1, 0, 0): the
    // SPU2's reverb, which bsnd does not have.
    bsound_set_path(m->bsound, sound_path(m));
    load_region(m, "common");
    if (bsound_get_status(m->bsound) == 1 && !m->commonLoaded) {
        uint32_t last = 0;
        do {
            CALL0(service_files);
            if (last != vblank(m)) {
                bsound_update(m->bsound);
                last = vblank(m);
            }
            // The port's: with nothing pending, nothing is coming.
        } while (!m->commonLoaded && m->bsound->pendingCount > 0);
    }
    // The demo disc's launcher picked JukeboxMDemoDisk.JBC here.
    if (m->jb->musicEnabled)
        jb_load_cartridge(&m->jb->jukebox, "SOUND\\JukeboxM.JBC", false);
    CALL0(sed_create);
    jb_default_category_volumes(m->jb);
}

void sound_load_regions_in_game(SoundModule* m, SoundDoneFn done,
                                intptr_t param)
{
    const char* track;
    int slot, i, j;

    m->done = done;
    m->doneParam = param;
    m->loading = 1;
    m->loadStart = bGetTicker();
    if (!SoundEnabled)
        return;
    m->inGameRegion = NULL;
    m->frontEndRegion = NULL;
    m->jb->delayedStart = 0.0f;
    m->jb->muted = 0;
    jb_music_set_selection(m->jb, m->audioOptions, JB_CAT_RACING_MUSIC);
    for (i = 0; i < SOUND_REGIONS; i++) {
        m->region[i].name[0] = '\0';
        m->region[i].loaded = 0;
    }
    copy_name(m->region[0].name, "InGame");
    track = H && H->track_region ? H->track_region(H->ctx) : NULL;
    slot = 1;
    if (track != NULL) {
        slot = 2;
        copy_name(m->region[1].name, track);
    }
    // The two drivers' cars' regions, each once.
    for (i = 0; i < 2; i++) {
        const char* car = H && H->driver_region
            ? H->driver_region(H->ctx, i) : NULL;
        int found = 0;

        if (car == NULL || car[0] == '\0')
            continue;
        for (j = 0; j < SOUND_REGIONS; j++) {
            if (strcmp(car, m->region[j].name) == 0) {
                found = 1;
                break;
            }
        }
        if (!found)
            copy_name(m->region[slot++].name, car);
    }
    load_region(m, m->region[0].name);
    CALL0(collision_register);
    CALL0(noise_request);
    CALL0(oneshot_init);
}

void sound_load_regions_front_end(SoundModule* m, SoundDoneFn done,
                                  intptr_t param)
{
    int i;

    m->done = done;
    m->doneParam = param;
    m->loading = 1;
    m->loadStart = bGetTicker();
    if (!SoundEnabled)
        return;
    m->inGameRegion = NULL;
    m->frontEndRegion = NULL;
    m->jb->delayedStart = 0.0f;
    jb_music_set_selection(m->jb, m->audioOptions, JB_CAT_MENU_MUSIC);
    for (i = 0; i < SOUND_REGIONS; i++) {
        m->region[i].name[0] = '\0';
        m->region[i].loaded = 0;
    }
    copy_name(m->region[0].name, "FrontEnd");
    load_region(m, m->region[0].name);
    m->jb->muted = 0;
}

int sound_real_is_region_loading_complete(const SoundModule* m)
{
    int i;

    if (!SoundEnabled)
        return 1;
    for (i = 0; i < SOUND_REGIONS; i++)
        if (m->region[i].name[0] != '\0' && !m->region[i].loaded)
            return 0;
    return 1;
}

int sound_is_region_loading_complete(const SoundModule* m)
{
    return !m->loading;
}

// 0x001af308. A joylog replay waits here for the regions the recording
// found in, so the replay's frames line up; recording, it notes whether
// they were in. Twenty seconds without them is an orange flash, and the
// game goes on.
static void poll_regions(SoundModule* m)
{
    int32_t ready;

    if (!m->loading)
        return;
    if (H && H->joylog_replaying && H->joylog_replaying(H->ctx)) {
        ready = H->joylog_get ? H->joylog_get(H->ctx, 1, 5) : 0;
        if (ready) {
            uint32_t last = 0;
            while (!sound_real_is_region_loading_complete(m)) {
                CALL0(service_files);
                if (last != vblank(m)) {
                    bsound_update(m->bsound);
                    last = vblank(m);
                }
            }
        }
    } else {
        ready = sound_real_is_region_loading_complete(m);
        if (H && H->joylog_add)
            H->joylog_add(H->ctx, ready, 1, 5);
    }
    if (20.0f < bGetTickerDifference(m->loadStart, bGetTicker()) * 0.001f) {
        flash(m, 128, 84, 0, "Hang loading sound", 0.5f);
        ready = 1;
    }
    if (ready) {
        m->loading = 0;
        if (m->done != NULL) {
            m->done(m->doneParam);
            m->done = NULL;
        }
    }
}

void sound_unload_regions(SoundModule* m)
{
    int i;

    if (!SoundEnabled)
        return;
    CALL0(collision_unregister);
    CALL0(noise_unload);
    CALL0(speech_flush);
    CALL0(oneshot_close);
    // Last first. "common" is not one of them, and stays.
    for (i = SOUND_REGIONS - 1; i >= 0; i--) {
        if (m->region[i].name[0] != '\0') {
            bsound_unload_region(m->bsound, m->region[i].name);
            m->region[i].name[0] = '\0';
            m->region[i].loaded = 0;
        }
    }
    m->inGameRegion = NULL;
    m->frontEndRegion = NULL;
    m->jb->delayedStart = 0.0f;
}

// ------------------------------------------------------------- the update

void sound_update(SoundModule* m)
{
    JBSound* jb = m->jb;

    poll_regions(m);
    if (!SoundEnabled)
        return;
    // Retail takes the difference once before the test above as well, and
    // throws it away. Nothing runs more often than every 8 ms.
    if (!(8.0f < bGetTickerDifference(m->lastUpdate, bGetTicker())))
        return;
    m->lastUpdate = bGetTicker();
    CALL0(speech_update);
    CALL0(sed_update);
    jb_update(&jb->jukebox);
    if (!paused(m) && game_state(m) != JB_STATE_IN_FRONTEND && !jb->muted) {
        CALL0(car_sounds_update);
        // DelayedStart's count (0x001aec88 sets it): by the world's step,
        // then the jukebox's Start once it passes zero.
        if (0.0f < jb->delayedStart)
            jb->delayedStart -= H && H->dt ? H->dt(H->ctx) : 0.0f;
        if (jb->delayedStart < 0.0f) {
            jb_music_start(jb, m->audioOptions, 0);
            jb->delayedStart = 0.0f;
        }
        CALL0(collision_update);
        CALL0(oneshot_update);
        CALL0(scape_update);
        CALL0(noise_update);
        if (helicopter(m))
            CALL0(chopper_update);
    }
    bsound_update(m->bsound);
    sound_update_volume_muffler(m);
    // bVoiceMgr::PrintVoiceUsage, a debug print, when the flag is up.
    if (m->printVoiceUsage)
        m->printVoiceUsage = 0;
}

// smooth<float> (0x00136630): `a` a step of at most `step` towards `b`.
static float smooth(float a, float b, float step)
{
    float up = a + step;
    float down;

    if (up < b)
        return up;
    down = a - step;
    if (b < down)
        return down;
    return b;
}

void sound_update_volume_muffler(SoundModule* m)
{
    float rate = 0.1f;
    float volume = -1.0f;
    int any = 0;
    int n = H && H->num_players ? H->num_players(H->ctx) : 0;
    int i;

    // Any player in a muffling zone muffles; the volume is the first such
    // player's -- or, should that be -1, the next player's, muffling or
    // not.
    for (i = 0; i < n; i++) {
        int muffle = 0, zone = 0;
        float v = 0.0f;

        if (H->player_zone)
            H->player_zone(H->ctx, i, &muffle, &zone, &v);
        any = any || (muffle && zone);
        if (any && volume == -1.0f)
            volume = v;
    }
    if (!m->jb->muted
        && (H && H->race_state ? H->race_state(H->ctx) : -1) == 7) {
        // RCSTATE_POSTRACE: half volume.
        m->muffleTarget = 0.5f;
    } else if (!m->jb->muted && any) {
        rate = 0.05f;
        m->muffleTarget = volume;
    } else if (!m->jb->muted && H && H->speech_sed_playing
               && H->speech_sed_playing(H->ctx)) {
        // Under a speech: a touch quieter in a race, much in the menus.
        m->muffleTarget = game_state(m) != JB_STATE_IN_FRONTEND ? 0.95f : 0.3f;
    } else {
        rate = 0.2f;
        m->muffleTarget = 1.0f;
    }
    {
        float v = smooth(m->muffleCurrent, m->muffleTarget, rate);

        if (!(v == m->muffleCurrent)) {
            m->muffleCurrent = v;
            sound_scale_category_volumes(m, v, 0);
        }
    }
}

void sound_scale_category_volumes(SoundModule* m, float scale, int speechToo)
{
    const JBSound* jb = m->jb;
    int i;

    if (!(scale == m->lastScale)) {
        for (i = 0; i < 5; i++)
            bsound_set_category_volume(m->bsound, kSavedCategory[i],
                                       jb->savedVolume[i] * scale);
        bsound_set_category_volume(m->bsound, JB_CAT_SPEECH,
                                   speechToo ? jb->savedSpeechVolume * scale
                                             : jb->savedSpeechVolume);
    }
    m->lastScale = scale;
}

// ---------------------------------------------------------------- muting

void sound_mute(SoundModule* m, int32_t on)
{
    JBSound* jb = m->jb;

    if (!SoundEnabled)
        return;
    jb->muted = on;
    if (jb->musicEnabled) {
        JBPlayer* p = &jb->jukebox;
        // A category turned down to nothing stays paused either way.
        int32_t pause = on;

        if (!(0.0f < bsound_get_category_volume(m->bsound, p->soundCategory))
            && on == 0)
            pause = 1;
        jb_pause(p, (uint32_t)pause);
    }
    if (m->speechEnabled) {
        CALL1(speech_mute, on);
        CALL1(noise_mute, on);
    }
    CALL1(scape_mute, on);
    sound_mute_car_sounds(m, on);
    CALL1(oneshot_mute, on);
    CALL1(collision_mute, on);
    if (helicopter(m))
        CALL1(chopper_mute, on);
}

void sound_mute_replay(SoundModule* m, int32_t on)
{
    if (!SoundEnabled)
        return;
    m->jb->muted = on;
    sound_mute_car_sounds(m, on);
    CALL1(oneshot_mute, on);
    CALL1(collision_mute, on);
    CALL1(scape_mute, on);
    if (helicopter(m))
        CALL1(chopper_mute, on);
}

void sound_mute_car_sounds(SoundModule* m, int32_t on)
{
    int n = H && H->num_cars ? H->num_cars(H->ctx) : 0;
    int i;

    for (i = 0; i < n; i++) {
        void* s = H->car_sound ? H->car_sound(H->ctx, i) : NULL;

        if (s != NULL && H->car_sound_mute)
            H->car_sound_mute(H->ctx, s, on);
    }
}

// --------------------------------------------------------------- samples

BSample* sound_get_in_game_sample(SoundModule* m, const char* name)
{
    if (m->inGameRegion == NULL) {
        m->inGameRegion = bsound_region(m->bsound, "InGame");
        if (m->inGameRegion == NULL)
            return NULL;
    }
    return bregion_sample(m->inGameRegion, name);
}

void sound_play_common_region_sample(SoundModule* m, const char* name,
                                     float volume)
{
    BSample* s;

    if (!SoundEnabled)
        return;
    s = bregion_sample(bsound_common_region(m->bsound), name);
    bsample_set_category(s, JB_CAT_MENU_SFX);
    bsample_play(s, volume, 0.0f, 0.0f);
}

void sound_trigger_finish_line_sound(SoundModule* m)
{
    BSample* s = sound_get_in_game_sample(m, "FinishLine");

    if (s != NULL)
        bsample_play(s, 1.0f, 0.0f, 0.0f);
}

// ------------------------------------------------------------ the rest

int32_t sound_random_int(SoundModule* m, int32_t range)
{
    return bRandomI(range, &m->seed);
}

float sound_random_float(SoundModule* m, float range)
{
    return bRandomF(range, &m->seed);
}

void sound_set_audio_mode(SoundModule* m, int32_t mode)
{
    bsound_set_mode(m->bsound, mode);
    m->audioMode = mode;
}

int32_t sound_get_audio_mode(const SoundModule* m)
{
    return m->audioMode;
}
